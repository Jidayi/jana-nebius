"""Build the unsigned English speech pack `sp.en.<version>` outside the repository (VOC-01, VOC-02, VOC-03, D95).

    uv run python -m jana_tools.release.speech_pack build --version 1_0 [--out ~/.jana/release/speech]
    uv run python -m jana_tools.release.speech_pack check PACK_DIR

The pack holds the voices D95 chose and the runtime that speaks them, as a read-aloud-only pack (TABLE VOC-03a
`stt: none`): no speech-to-text, VAD or turn model is in it yet.

- low, mid: Kokoro-82M (`af_heart` only) on the CPU through torch, `bin/jana-voice-kokoro`;
- high (Apple silicon): Qwen3-TTS 0.6B CustomVoice, speaker `Ryan`, on MLX, `bin/jana-voice-qwen3`.

Inputs are files already on this computer: the owner-approved model downloads with their manifests
(`~/.jana/models/speech`), the two speech runtimes resolved offline from the approved wheels
(`~/.jana/speech-env/pack-runtimes`), the uv-managed CPython the runtimes were built with, the launcher's own code
(`agent_core`) and the few core libraries it imports, taken from the repository's environment. Nothing is downloaded.

Every file gets a licence record from a reviewed table (an unknown distribution fails the build), the PyPI or model
source it came from, its size and SHA-256. Python distributions are checked against their wheel RECORD hashes, so an
LGPL library ships unmodified as its own folder (D95). The manifest is unsigned; the owner signs it with the Updater
key (`python -m signing_service sign-speech-pack`, D88) and the gate of `agent_core.store.speech_packs` re-runs.
"""

from __future__ import annotations

import argparse
import base64
import csv
import email
import hashlib
import json
import os
import shutil
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

HOME = Path.home()
MODELS = HOME / ".jana" / "models" / "speech"
RUNTIMES = HOME / ".jana" / "speech-env" / "pack-runtimes"
PYTHON = HOME / ".local" / "share" / "uv" / "python" / "cpython-3.12.13-macos-aarch64-none"
OUT = HOME / ".jana" / "release" / "speech"
PLATFORM = "macos-aarch64"
SITE = "lib/python3.12/site-packages"
PROJECT = "https://jana.dev/"  # the project's namespace (the contracts' $id); the launcher is this product's own code
UPSTREAM_COMMIT = "619e3fe4f71d1c6f35c15870d588a3638de34722"
ALL = ["low", "mid", "high"]

# The SPDX licence of every distribution the runtimes may hold, reviewed by hand from each wheel's METADATA and
# licence files (2026-10-16). LGPL is allowed only as a separate library (D95); the gate re-checks every record.
DIST_LICENCES: dict[str, str] = {
    "addict": "MIT",
    "annotated-doc": "MIT",
    "annotated-types": "MIT",
    "anyio": "MIT",
    "attrs": "MIT",
    "blis": "BSD-3-Clause",
    "catalogue": "MIT",
    "certifi": "MPL-2.0",
    "cffi": "MIT-0",
    "charset-normalizer": "MIT",
    "click": "BSD-3-Clause",
    "cloudpathlib": "MIT",
    "confection": "MIT",
    "cryptography": "Apache-2.0 OR BSD-3-Clause",
    "cymem": "MIT",
    "docopt": "MIT",
    "en-core-web-sm": "MIT",
    "filelock": "MIT",
    "fsspec": "BSD-3-Clause",
    "h11": "MIT",
    "hf-xet": "Apache-2.0",
    "httpcore": "BSD-3-Clause",
    "httpcore2": "BSD-3-Clause",
    "httpx": "BSD-3-Clause",
    "httpx2": "BSD-3-Clause",
    "huggingface-hub": "Apache-2.0",
    "idna": "BSD-3-Clause",
    "jinja2": "BSD-3-Clause",
    "jsonschema": "MIT",
    "jsonschema-specifications": "MIT",
    "kokoro": "Apache-2.0",
    "loguru": "MIT",
    "markdown-it-py": "MIT",
    "markupsafe": "BSD-3-Clause",
    "mdurl": "MIT",
    "miniaudio": "MIT",
    "misaki": "Apache-2.0",
    "mlx": "MIT",
    "mlx-audio": "MIT",
    "mlx-metal": "MIT",
    "mpmath": "BSD-3-Clause",
    "murmurhash": "MIT",
    "networkx": "BSD-3-Clause",
    "num2words": "LGPL-2.1-or-later",
    "numpy": "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "preshed": "MIT",
    "pycparser": "BSD-3-Clause",
    "pydantic": "MIT",
    "pydantic-core": "MIT",
    "pygments": "BSD-2-Clause",
    "pyyaml": "MIT",
    "referencing": "MIT",
    "regex": "Apache-2.0 AND CNRI-Python",
    "requests": "Apache-2.0",
    "rich": "MIT",
    "rpds-py": "MIT",
    "safetensors": "Apache-2.0",
    "scipy": "BSD-3-Clause",
    "setuptools": "MIT",
    "shellingham": "ISC",
    "smart-open": "MIT",
    "sounddevice": "MIT",
    "spacy": "MIT",
    "spacy-legacy": "MIT",
    "spacy-loggers": "MIT",
    "srsly": "MIT",
    "sympy": "BSD-3-Clause",
    "thinc": "MIT",
    "tokenizers": "Apache-2.0",
    "torch": "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT",
    "tqdm": "MPL-2.0 AND MIT",
    "transformers": "Apache-2.0",
    "truststore": "MIT",
    "typer": "MIT",
    "typing-extensions": "PSF-2.0",
    "typing-inspection": "MIT",
    "urllib3": "MIT",
    "wasabi": "MIT",
    "weasel": "MIT",
    "websockets": "BSD-3-Clause",
    "wrapt": "BSD-2-Clause",
}
SOURCES = {
    "en-core-web-sm": "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/"
    "en_core_web_sm-3.8.0-py3-none-any.whl",
}
# The launcher's core imports (VOC-23) that neither runtime carries: copied from the repository's locked environment.
APP_DEPS = (
    "websockets",
    "cryptography",
    "cffi",
    "pycparser",
    "jsonschema",
    "jsonschema-specifications",
    "referencing",
    "rpds-py",
    "attrs",
)
RUNTIME_CLASSES = {"kokoro-cpu": ["low", "mid"], "qwen3-mlx": ["high"]}
# Files a runtime never needs at run time: headers and build files, byte-code caches, uv's venv shim, and misaki's
# wrapper around the GPL espeak-ng, which the gate refuses by name (the launcher stands in for it, VOC-02).
PRUNE = ("torch/include/", "torch/share/", "_virtualenv.py", "_virtualenv.pth", "misaki/espeak.py")
# The interpreter: CPython from python-build-standalone, without Tk, IDLE, the test suite, pip or headers.
PYTHON_KEEP = ("bin/python3.12", "lib/libpython3.12.dylib", "lib/python3.12/")
PYTHON_PRUNE = (
    "lib/python3.12/test/",
    "lib/python3.12/idlelib/",
    "lib/python3.12/tkinter/",
    "lib/python3.12/turtledemo/",
    "lib/python3.12/ensurepip/",
    "lib/python3.12/lib2to3/",
    "lib/python3.12/site-packages/",
    "lib/python3.12/config-3.12-darwin/",
    "lib/python3.12/lib-dynload/_tkinter",
)
PYTHON_ATTRIBUTION = (
    "CPython 3.12.13 (python-build-standalone build), Python Software Foundation License 2.0 and the Python licence "
    "stack (lib/python3.12/LICENSE.txt). The build links third-party libraries statically, each under its own "
    "permissive licence (OpenSSL Apache-2.0, libffi MIT, zlib, bzip2, xz, SQLite public domain, mpdecimal, expat, "
    "libedit); their inventory is a release item before the pack is signed for pilot or production."
)


class BuildError(RuntimeError):
    pass


@dataclass
class Entry:
    source: Path
    path: str
    role: str
    engine: str
    classes: list[str]
    spdx: str
    source_url: str
    attribution: str
    mode: int = 0o644
    expected_sha256: str | None = None


@dataclass
class Plan:
    entries: list[Entry] = field(default_factory=list)

    def add(self, entry: Entry) -> None:
        self.entries.append(entry)


def canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def record_hash(value: str) -> str | None:
    if not value.startswith("sha256="):
        return None
    raw = base64.urlsafe_b64decode(value[7:] + "=" * (-len(value[7:]) % 4))
    return raw.hex()


def distributions(site: Path) -> Iterator[tuple[str, str, Path, list[tuple[str, str | None]]]]:
    """(name, version, dist-info, [(site-relative path, sha256 from RECORD)]) for each wheel installed in `site`."""
    for info in sorted(site.glob("*.dist-info")):
        meta = email.message_from_bytes((info / "METADATA").read_bytes())
        rows = []
        with (info / "RECORD").open(newline="") as handle:
            for row in csv.reader(handle):
                if not row or row[0].startswith("..") or row[0].startswith("/"):
                    continue  # console scripts outside site-packages: the pack ships none
                rows.append((row[0], record_hash(row[1]) if len(row) > 1 else None))
        yield str(meta["Name"]), str(meta["Version"]), info, rows


def add_site(plan: Plan, site: Path, prefix: str, classes: list[str], only: tuple[str, ...] | None = None) -> None:
    """Every file of every distribution in `site` (or of `only`), with its distribution's licence and source."""
    seen: set[str] = set()
    for name, version, info, rows in distributions(site):
        key = canonical(name)
        if only is not None and key not in only:
            continue
        spdx = DIST_LICENCES.get(key)
        if spdx is None:
            raise BuildError(f"{name} {version}: no reviewed licence; add it to DIST_LICENCES or leave it out")
        source = SOURCES.get(key, f"https://pypi.org/project/{key}/{version}/")
        # One short line per file (the manifest holds tens of thousands): the licence texts sit in the dist-info.
        attribution = f"{name} {version}, {spdx}. Licence texts: {prefix}/{info.name}/."
        if spdx.startswith("LGPL"):
            attribution += (
                " A separate library in its own folder, shipped unmodified (D95): to use a modified version, rebuild"
                " the runtime with it (jana_tools.release.speech_pack) and install the pack under a development key."
            )
        for relative, digest in rows:
            if "__pycache__/" in relative or relative.endswith(".pyc") or relative.startswith(PRUNE):
                continue
            file = site / relative
            if not file.is_file():
                continue
            if spdx.startswith("LGPL") and digest is None and not relative.endswith(("RECORD", "INSTALLER")):
                raise BuildError(f"{name}: {relative} has no RECORD hash; cannot show the library is unmodified")
            seen.add(relative)
            plan.add(
                Entry(
                    file,
                    f"{prefix}/{relative}",
                    "sidecar",
                    "speech-to-speech",
                    classes,
                    spdx,
                    source,
                    attribution,
                    file.stat().st_mode & 0o755 | 0o644,
                    digest if spdx.startswith("LGPL") else None,
                )
            )
    if only is None:
        stray = [
            p.relative_to(site).as_posix()
            for p in site.rglob("*")
            if p.is_file()
            and p.relative_to(site).as_posix() not in seen
            and "__pycache__" not in p.parts
            and not p.relative_to(site).as_posix().startswith(PRUNE)
            and not p.name.endswith(".pyc")
        ]
        if stray:
            raise BuildError(f"{site}: files owned by no distribution: {stray[:5]}")


def add_python(plan: Plan, root: Path) -> None:
    for file in sorted(root.rglob("*")):
        relative = file.relative_to(root).as_posix()
        if not file.is_file() or file.is_symlink() or "__pycache__" in file.parts:
            continue
        if not relative.startswith(PYTHON_KEEP) or relative.startswith(PYTHON_PRUNE):
            continue
        plan.add(
            Entry(
                file,
                f"runtime/python/{relative}",
                "sidecar",
                "speech-to-speech",
                list(ALL),
                "Python-2.0",
                "https://github.com/astral-sh/python-build-standalone/releases/tag/20260303",
                PYTHON_ATTRIBUTION,
                file.stat().st_mode & 0o755 | 0o644,
            )
        )


def add_app(plan: Plan, package: Path) -> None:
    for file in sorted(package.rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
            continue
        relative = file.relative_to(package.parent).as_posix()
        plan.add(
            Entry(
                file,
                f"runtime/app/{relative}",
                "sidecar",
                "speech-to-speech",
                list(ALL),
                "Apache-2.0",
                PROJECT,
                "Jana agent core: the speech sidecar launcher and its contracts, Apache-2.0.",
            )
        )


def add_model(plan: Plan, folder: Path, target: str, engine: str, classes: list[str], wanted: list[str] | None) -> None:
    manifest = json.loads((folder / "manifest.json").read_text())
    repo, revision = manifest["repo"], manifest["revision"]
    for file in manifest["files"]:
        if (wanted is not None and file["path"] not in wanted) or file["path"] in (".gitattributes", "README.md"):
            continue
        plan.add(
            Entry(
                folder / file["path"],
                f"{target}/{file['path']}",
                "tts",
                engine,
                classes,
                manifest["licence"],
                file["source_url"],
                f"{repo} at {revision}, {manifest['licence']}; preset voices only, no voice cloning (VOC-02).",
                0o644,
                file["sha256"],
            )
        )
    if wanted is not None and {e.path for e in plan.entries if e.path.startswith(target + "/")} != {
        f"{target}/{w}" for w in wanted
    }:
        raise BuildError(f"{folder}: missing one of {wanted}")


BOOTSTRAP = '''"""Jana speech sidecar bootstrap (VOC-23). The interpreter runs isolated (-I -S -B): only the pack's own
runtime folders are importable, in this order, nothing from the user's Python or environment, and nothing is
written into the pack."""

import os
import site
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = sys.argv[1] if len(sys.argv) > 1 else ""
if RUNTIME not in ("kokoro-cpu", "qwen3-mlx"):
    raise SystemExit(2)
for folder in (RUNTIME, "common", "app"):
    site.addsitedir(os.path.join(HERE, folder))
sys.argv = [sys.argv[0]]

from agent_core.net.voice_sidecar import main  # noqa: E402

raise SystemExit(main())
'''

ENTRY = """#!/bin/sh
# Jana speech sidecar entry point (VOC-23): the pack's own interpreter, isolated from any other Python. The shell
# starts it with a cleared environment, so no command is looked up on a PATH; -B: it never writes into the verified
# pack (its byte code was compiled when the pack was built).
pack=${{0%/*}}
pack=${{pack%/*}}
exec "$pack/runtime/python/bin/python3.12" -I -S -B "$pack/runtime/launch.py" {runtime}
"""


def plan_pack(models: Path, runtimes: Path, python: Path, repo: Path) -> tuple[Plan, dict[str, str]]:
    plan = Plan()
    add_model(
        plan,
        models / "kokoro-82m",
        "models/kokoro-82m",
        "kokoro",
        ["low", "mid"],
        ["config.json", "kokoro-v1_0.pth", "voices/af_heart.pt"],
    )
    add_model(
        plan, models / "qwen3-tts-12hz-0.6b-customvoice", "models/qwen3-tts-0.6b-customvoice", "qwen3", ["high"], None
    )
    for runtime, classes in RUNTIME_CLASSES.items():
        add_site(plan, runtimes / runtime / SITE, f"runtime/{runtime}", classes)
    add_site(plan, repo / ".venv" / SITE, "runtime/common", list(ALL), APP_DEPS)
    add_python(plan, python)
    add_app(plan, repo / "services" / "agent-core" / "agent_core")
    generated = {"runtime/launch.py": BOOTSTRAP}
    for runtime in RUNTIME_CLASSES:
        generated[f"bin/jana-voice-{runtime.split('-')[0]}"] = ENTRY.format(runtime=runtime)
    # D95 condition (5): the recipe ships with the pack, so a user can rebuild the runtime with a modified library.
    generated["licences/speech_pack_build.py"] = Path(__file__).read_text()
    generated["licences/REPLACING-LIBRARIES.txt"] = REPLACING
    return plan, generated


REPLACING = """Replacing a library in this speech pack (D95)

LGPL libraries in this pack (for example num2words) are separate libraries: each sits unmodified in a folder of its
own under runtime/<runtime>/, with its licence text in its .dist-info folder, and the sidecar imports it by name.
You may use a modified version. Because every file of an installed pack is checked against its signed manifest, a
modified library goes into a rebuilt pack rather than into this folder:

1. Install your version of the library into the speech runtime the pack was built from.
2. Rebuild the pack with speech_pack_build.py (beside this file):
       python -m jana_tools.release.speech_pack build --version <new version>
3. Sign it with a development key and install it in a development build of the app:
       python -m signing_service sign-speech-pack <pack folder> --dev
"""


def profiles() -> dict[str, Any]:
    kokoro = {
        "stt": "none",
        "tts": "kokoro",
        "device": "cpu",
        "tts_path": "models/kokoro-82m",
        "sidecar_path": "bin/jana-voice-kokoro",
        "speaker": "af_heart",
    }
    qwen3 = {
        "stt": "none",
        "tts": "qwen3",
        "device": "mps",
        "tts_path": "models/qwen3-tts-0.6b-customvoice",
        "sidecar_path": "bin/jana-voice-qwen3",
        "speaker": "Ryan",
    }
    return {"low": dict(kokoro), "mid": dict(kokoro), "high": qwen3}


def bytecode(staging: Path, entry: Entry) -> Entry | None:
    """The byte code of a runtime module, compiled at build time with a hash that never goes stale (unchecked-hash).
    The sidecar runs with -B, so it never writes into its verified pack; it loads these instead of compiling torch's
    modules at every launch. A module this interpreter cannot compile is left to compile in memory."""
    import py_compile

    if entry.role != "sidecar" or not entry.path.endswith(".py"):
        return None
    source = PurePosixPath(entry.path)
    relative = source.parent / "__pycache__" / f"{source.stem}.{sys.implementation.cache_tag}.pyc"
    try:
        py_compile.compile(
            str(staging / entry.path),
            cfile=str(staging / relative),
            dfile=entry.path,
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
    except (py_compile.PyCompileError, SyntaxError, ValueError):
        return None
    os.chmod(staging / relative, 0o644)
    return Entry(
        staging / relative,
        relative.as_posix(),
        entry.role,
        entry.engine,
        entry.classes,
        entry.spdx,
        entry.source_url,
        entry.attribution,
    )


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def build(version: str, out: Path, models: Path, runtimes: Path, python: Path, repo: Path) -> Path:
    pack_id = f"sp.en.{version}"
    destination = out / pack_id
    if destination.exists():
        raise BuildError(f"{destination} exists: speech pack ids are immutable; choose a new version")
    plan, generated = plan_pack(models, runtimes, python, repo)
    out.mkdir(parents=True, exist_ok=True)
    staging = out / f".{pack_id}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    files: list[dict[str, Any]] = []
    try:
        for entry in plan.entries:
            target = staging / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry.source, target)
            os.chmod(target, entry.mode)
            sha = digest(target)
            if entry.expected_sha256 is not None and sha != entry.expected_sha256:
                raise BuildError(f"{entry.path}: bytes differ from the recorded download or wheel RECORD")
            files.append(record(entry, target.stat().st_size, sha))
            compiled = bytecode(staging, entry)
            if compiled is not None:
                files.append(record(compiled, compiled.source.stat().st_size, digest(compiled.source)))
        for relative, text in generated.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            os.chmod(target, 0o755 if relative.startswith("bin/") else 0o644)
            classes = ["high"] if relative.endswith("qwen3") else ["low", "mid"] if relative.startswith("bin/") else ALL
            entry = Entry(
                target,
                relative,
                "sidecar",
                "speech-to-speech",
                list(classes),
                "Apache-2.0",
                PROJECT,
                "Jana speech sidecar entry point and bootstrap, Apache-2.0.",
            )
            files.append(record(entry, target.stat().st_size, digest(target)))
        manifest = {
            "speech_pack_id": pack_id,
            "manifest_version": 1,
            "language": "en",
            "platform": PLATFORM,
            "upstream_commit": UPSTREAM_COMMIT,
            "min_app_version": "0.0.0",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "profiles": profiles(),
            "files": sorted(files, key=lambda f: f["path"]),
            "signature": {},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        check(staging)
        os.rename(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return destination


def record(entry: Entry, size: int, sha: str) -> dict[str, Any]:
    return {
        "path": entry.path,
        "role": entry.role,
        "engine": entry.engine,
        "classes": entry.classes,
        "size_bytes": size,
        "sha256": sha,
        "licence": {"spdx": entry.spdx, "source_url": entry.source_url, "attribution": entry.attribution},
    }


def check(folder: Path) -> dict[str, Any]:
    """The pack against the gate the app runs (licences, profiles, layout) and every byte; a short summary."""
    from agent_core.store.speech_packs import SpeechPackError, check_folder

    try:
        manifest = check_folder(folder)
    except SpeechPackError as error:
        raise BuildError(str(error)) from error
    summary: dict[str, Any] = {
        "speech_pack_id": manifest.speech_pack_id,
        "files": len(manifest.files),
        "bytes": sum(f.size_bytes for f in manifest.files),
    }
    for hardware in ALL:
        summary[f"{hardware}_bytes"] = sum(f.size_bytes for f in manifest.files if hardware in f.classes)
    summary["lgpl"] = sorted({f.licence.source_url for f in manifest.files if f.licence.spdx.startswith("LGPL")})
    summary["signed"] = bool(manifest.signature)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speech_pack")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build")
    make.add_argument("--version", required=True, help="the pack version, e.g. 1_0 (sp.en.1_0)")
    make.add_argument("--out", type=Path, default=OUT)
    make.add_argument("--models", type=Path, default=MODELS)
    make.add_argument("--runtimes", type=Path, default=RUNTIMES)
    make.add_argument("--python", type=Path, default=PYTHON)
    make.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    verify = commands.add_parser("check")
    verify.add_argument("pack", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            folder = build(args.version, args.out, args.models, args.runtimes, args.python, args.repo)
            print(json.dumps({"pack": str(folder), **check(folder)}, indent=1))
        else:
            print(json.dumps(check(args.pack), indent=1))
    except BuildError as error:
        print(f"speech pack build refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
