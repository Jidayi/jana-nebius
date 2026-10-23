"""The perception suite for printed questions (EVL-12).

A photo set of printed questions (synthetic or licensed question sheets, never students) is read by the production
pipeline (`agent_core.engine.vision.PhotoReader`: made safe, then the vision slot) and each transcription is compared
with its typed original after normalisation (whitespace and equivalent LaTeX spellings). A photo counts as read when
the two are equal after normalisation; the gate is the share read, per hardware class, on that class's reference
laptop (`evl12_printed_gate`). The set lives at `evals/perception/printed/` as `set.json` (each item: photo file, its
sha256, the typed original, its source) beside the photos; the lab's per-class results go in each laptop's
device-lab file as `perception`.

`synthetic_sheet` renders a question as a captured-looking sheet (tilt, uneven light, blur) for smoke runs of the
pipeline; such sheets are labelled synthetic and are not the EVL-12 set, which is ordinary photos.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import random
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from . import report as rep

PRINTED = REPO_ROOT / "evals" / "perception" / "printed"
SOURCES = ("synthetic", "licensed")

# Spellings of the same LaTeX: each pattern is replaced by its canonical form before comparing.
_EQUIVALENT = (
    (re.compile(r"\\[dt]frac"), r"\\frac"),
    (re.compile(r"\\left\s*|\\right\s*"), ""),
    (re.compile(r"\\[,;:! ]"), " "),
    (re.compile(r"\\(?:text|mathrm|operatorname)\{([^{}]*)\}"), r"\1"),
    (re.compile("\\\\cdot|\\\\times|\u00d7|\u00b7"), r"\\times "),
    (re.compile("\u2212|\u2013"), "-"),
    (re.compile(r"\^\{(\w)\}"), r"^\1"),
    (re.compile(r"_\{(\w)\}"), r"_\1"),
    (re.compile(r"\\\(|\\\)|\\\[|\\\]|\$\$"), " "),
)


def normalise(text: str) -> str:
    """Whitespace and equivalent LaTeX spellings made one, so only a real misreading differs."""
    out = text.strip()
    for pattern, replacement in _EQUIVALENT:
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s*([=+\-*/^_(){}\[\],.:;])\s*", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def read_correctly(transcribed: str | None, original: str) -> bool:
    """Equal after normalisation; whitespace is not compared at all, so spacing inside mathematics never counts."""
    if transcribed is None:
        return False
    return re.sub(r"\s+", "", normalise(transcribed)) == re.sub(r"\s+", "", normalise(original))


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The share of photos read correctly, with its Wilson interval (`report.result`)."""
    passed = sum(bool(r["correct"]) for r in results)
    return rep.result(passed, len(results))


def set_errors(folder: Path = PRINTED) -> list[str]:
    """Validate ordinary-camera provenance, independent originals and immutable bounded fixture files."""
    from agent_core.config import Settings

    manifest = folder / "set.json"
    if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size > 2_000_000:
        return [f"no bounded printed photo manifest at {manifest}"]
    try:
        document = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return ["printed photo manifest cannot be read"]
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        return ["printed photo manifest must contain an items array"]
    items = document["items"]
    size = Settings().evl12_printed_set_size
    errors = []
    if not size <= len(items) <= 10_000:
        errors.append(f"the printed set has {len(items)} photos; needs {size} to 10000")
    hashes, names = set(), set()
    licences = {"LicenseRef-Own", "CC0-1.0", "LicenseRef-PublicDomain", "CC-BY-3.0", "CC-BY-4.0"}
    for item in items:
        if not isinstance(item, dict):
            errors.append("printed photo item must be an object")
            continue
        name = item.get("photo")
        if (
            item.get("source") not in SOURCES
            or not isinstance(item.get("licence"), str)
            or item["licence"] not in licences
        ):
            errors.append(f"{name}: synthetic or licensed sheet provenance and approved licence are required")
        if item.get("acquisition") != "camera":
            errors.append(f"{name}: EVL-12 requires an ordinary camera photograph, not a rendered smoke fixture")
        if not isinstance(item.get("original"), str) or not 1 <= len(item["original"].strip()) <= 8000:
            errors.append(f"{name}: no bounded typed original")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in hashes:
            errors.append(f"{name}: unique SHA-256 required")
        hashes.add(str(digest))
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:jpg|jpeg|png|webp)", name)
            or name in names
        ):
            errors.append("printed photos must have unique local basenames")
            continue
        names.add(name)
        path = folder / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 20 * 1024 * 1024:
            errors.append(f"{name}: missing, linked or oversized fixture")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"{name}: changed since the set was locked")
    return errors


Reader = Callable[[bytes], Awaitable[str | None]]


async def transcribe(items: list[dict[str, Any]], read: Reader, folder: Path) -> list[dict[str, Any]]:
    """Each photo through `read` (the production pipeline), compared with its typed original."""
    out = []
    for item in items:
        name = item["photo"]
        if not isinstance(name, str) or Path(name).name != name or (folder / name).is_symlink():
            raise ValueError("photo fixture must be a regular local file")
        path = folder / name
        if not 0 < path.stat().st_size <= 20 * 1024 * 1024:
            raise ValueError("photo fixture size is outside the capture bounds")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError("photo fixture changed before reading")
        text = await read(data)
        out.append({"photo": item["photo"], "correct": read_correctly(text, item["original"])})
    return out


def pipeline_reader(router: Any, hardware_class: str) -> Reader:
    """Use the same native preprocessing, privacy/quality checks and structured capture path as the app."""
    from .capture_pipeline import CapturePipeline

    async def read(data: bytes) -> str | None:
        async with CapturePipeline(hardware_class, router) as pipeline:
            observed = await pipeline.capture(data, override_quality=True)
            record = observed.get("record", {})
            return str(record["text"]) if record.get("status") == "awaiting_confirmation" else None

    return read


def run_local(server: Path, gguf: Path, projector: Path, model_id: str, items: list[dict[str, Any]], folder: Path,
              hardware_class: str) -> dict[str, Any]:  # fmt: skip
    """Read `items` with llama-server serving `gguf` and its projector as `model_id`, through the shipped router and
    photo reader; the result block for a laptop's device-lab file."""
    from agent_core.config import Settings
    from agent_core.providers.llama import LlamaServerProvider

    from .memfit import serving

    errors = set_errors(folder)
    if errors:
        raise ValueError("invalid EVL-12 set: " + "; ".join(errors[:5]))
    if json.loads((folder / "set.json").read_text())["items"] != items:
        raise ValueError("EVL-12 items do not match their locked manifest")
    settings = Settings()
    index = ("low", "mid", "high").index(hardware_class)
    context = (settings.context_cap_low, settings.context_cap_mid, settings.context_cap_high)[index]
    with serving(server, gguf, context, projector, alias=model_id) as served:

        async def go() -> list[dict[str, Any]]:
            provider = LlamaServerProvider(served.url, served.key)
            router = model_router(provider, model_id, hardware_class)
            try:  # each read runs in its own job scope inside the photo reader (ARC-20)
                return await transcribe(items, pipeline_reader(router, hardware_class), folder)
            finally:
                await provider.close()

        results = asyncio.run(go())
    return {
        "hardware_class": hardware_class,
        "model": model_id,
        "printed": score(results),
        "items": results,
        "evidence_kind": "ordinary_camera",
        "pipeline": "capture-v1",
        "set_sha256": hashlib.sha256((folder / "set.json").read_bytes()).hexdigest(),
    }


def gate_errors(laptop: dict[str, Any]) -> list[str]:
    """Reject smoke-only, stale-shape, duplicate or inconsistent evidence; then apply EVL-12's size/rate gates."""
    from agent_core.config import Settings

    settings = Settings()
    name, block = laptop.get("name", "?"), laptop.get("perception")
    if not isinstance(block, dict):
        return [f"{name}: no printed-photo results (python -m jana_tools lab perception)"]
    errors = []
    if block.get("evidence_kind") != "ordinary_camera" or block.get("pipeline") != "capture-v1":
        errors.append(f"{name}: requires ordinary-camera evidence through the complete capture pipeline")
    if not isinstance(block.get("set_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", block["set_sha256"]):
        errors.append(f"{name}: no frozen printed-set manifest digest")
    hardware = block.get("hardware_class")
    if hardware not in ("low", "mid", "high") or laptop.get("hardware_class", hardware) != hardware:
        errors.append(f"{name}: missing or inconsistent hardware class")
    items, printed = block.get("items"), block.get("printed")
    if not isinstance(items, list) or not isinstance(printed, dict):
        return [*errors, f"{name}: no bounded per-photo outcomes"]
    if len(items) > 10_000 or any(
        not isinstance(item, dict) or not isinstance(item.get("photo"), str) or type(item.get("correct")) is not bool
        for item in items
    ):
        return [*errors, f"{name}: malformed per-photo outcomes"]
    if len({item["photo"] for item in items}) != len(items):
        errors.append(f"{name}: duplicate per-photo outcomes")
    calculated = score(items)
    if printed != calculated:
        errors.append(f"{name}: aggregate transcription score disagrees with per-photo outcomes")
    if len(items) < settings.evl12_printed_set_size:
        errors.append(f"{name}: {len(items)} photos read, fewer than the set's {settings.evl12_printed_set_size}")
    if (calculated["rate"] or 0.0) < settings.evl12_printed_gate:
        errors.append(
            f"{name}: printed transcription {(calculated['rate'] or 0):.1%} is under the gate of "
            f"{settings.evl12_printed_gate:.0%}"
        )
    return errors


def model_router(provider: Any, model_id: str, hardware_class: str) -> Any:
    """Pin every inherited vision tier to the model actually served by this lab invocation."""
    import yaml
    from agent_core.config import Settings
    from agent_core.router import Router
    from agent_core.router.config import load

    config = yaml.safe_load(
        (REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "router.yaml").read_text()
    )
    config["tiers"] = {tier: [f"local:{model_id}"] for tier in config["tiers"]}
    return Router(load(config), Settings(), {"local": provider}, hardware_class=hardware_class)


def synthetic_sheet(text: str, seed: int) -> bytes:
    """A question rendered as a captured-looking sheet: dark text on paper, slightly tilted, unevenly lit and soft.
    Synthetic: for smoke runs of the pipeline, never part of the EVL-12 set."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    rng = random.Random(seed)  # noqa: S311 - render variation, not a secret
    font = ImageFont.load_default(size=34)
    lines = _wrap(text, 46)
    sheet = Image.new("RGB", (1400, 140 + 56 * len(lines)), (246, 244, 236))
    draw = ImageDraw.Draw(sheet)
    for n, line in enumerate(lines):
        draw.text((70, 70 + 56 * n), line, fill=(28, 28, 32), font=font)
    sheet = sheet.rotate(rng.uniform(-4, 4), expand=True, fillcolor=(120, 118, 110))
    sheet = ImageEnhance.Brightness(sheet).enhance(rng.uniform(0.7, 1.05))
    sheet = sheet.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.1)))
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=rng.randint(70, 90))
    return out.getvalue()


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines
