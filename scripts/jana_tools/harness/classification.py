"""The classification suite (EVL-13): top-1 topic from the Diagnoser against the bank's labels, nightly.

`python -m jana_tools eval classify <url> <key> <model> <set.yaml> <out dir> [--open] [--jobs N]` runs a labelled
question set through retrieval and the shipped Diagnoser prompt on a local model and writes `<out dir>/report.json`.
For each question the pack search index proposes candidate topics (`agent_core.retrieval.classify`), the Diagnoser
picks one from the numbered list, and the topic it names is compared with the label; the gate is the share correct
(`gate_topic_top1`, TABLE EVL-17a). By default the session's subject is the question's subject, as in the app; with
`--open` candidates come from every installed subject.

The question set is evaluation data: it lives outside the repository (or sealed under `evals/held-out/` once the
release key holds it) and is never written into a pack, a fixture or a commit. The report holds question ids,
labels and choices only, never question text.
"""

from __future__ import annotations

import asyncio
import json
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT

SUITE = "classification"
FIELDS = ("id", "subject", "topic", "text")


def load_set(path: Path) -> list[dict[str, str]]:
    """The labelled questions: a YAML list of {id, subject, topic, text}; a malformed entry fails the whole set."""
    items = yaml.safe_load(path.read_text())
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path.name}: expected a non-empty list of questions")
    seen = set()
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict) or any(not isinstance(item.get(f), str) or not item[f] for f in FIELDS):
            raise ValueError(f"{path.name}: entry {n} needs {', '.join(FIELDS)}")
        if item["id"] in seen:
            raise ValueError(f"{path.name}: duplicate id {item['id']}")
        seen.add(item["id"])
    return [{f: str(i[f]) for f in FIELDS} for i in items]


def content_index() -> Any:
    """The search index over the repository's four O level packs, built from their sources as the build would."""
    from agent_core.retrieval.index import KnowledgeIndex
    from pack_builder.build import load_source

    sources = sorted(p.parent for p in (REPO_ROOT / "content" / "curriculum").glob("*/*/pack.yaml"))
    packs = []
    for directory in sources:
        source = load_source(directory)
        if source.pack.get("pack_id") != "pack.ref":
            packs.append((source.pack, source.tables))
    return KnowledgeIndex.from_tables(packs)


@cache
def _shipped() -> tuple[Any, dict[str, Any], set[str]]:
    """The shipped agent files, the Diagnoser's output contract and the registered tool names."""
    from agent_core.assets.agent import AgentAssets
    from agent_core.engine.assembly import DEV_SKILL_STATUSES, bundled_schemas
    from agent_core.tools.specs import registry

    assets = AgentAssets.load(REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", DEV_SKILL_STATUSES)
    return assets, bundled_schemas()["agents/diagnosis"], set(registry().specs)


def _family(model: str) -> str:
    return "gemma3" if "gemma" in model.lower() else "qwen3"


async def _diagnose(provider: Any, model: str, item: dict[str, str], candidates: list[Any],
                    hardware_class: str) -> dict[str, Any] | None:  # fmt: skip
    """One Diagnoser call through the shipped role prompt and output contract; None when the reply is unusable."""
    from agent_core.config import Settings
    from agent_core.prompts.builder import PromptSession, build_prompt
    from agent_core.providers import model_json
    from agent_core.providers.base import Message
    from agent_core.providers.openai_compat import grammar_friendly
    from agent_core.retrieval.classify import diagnoser_task

    assets, schema, known = _shipped()
    session = PromptSession(subject=item["subject"], level="O", session_date="2026-10-13",
                            task=diagnoser_task(item["text"], candidates), hardware_class=hardware_class,
                            session_tools=frozenset(known))  # fmt: skip
    build = build_prompt("diagnoser", _family(model), session, [], set(), known, assets, Settings(), schema)
    messages = [Message(m.role, m.content) for m in build.messages]  # type: ignore[arg-type]
    structured = {"mode": "json_schema", "schema": grammar_friendly(schema), "name": "diagnosis"}
    try:
        turn = await provider.complete(model, messages, [], structured=structured, max_tokens=600, effort="none",
                                       temperature=0.0)  # fmt: skip
        found = model_json.loads(turn.text)
    except Exception:  # an unusable reply counts as wrong, never as right
        return None
    return found if isinstance(found, dict) else None


async def _run(url: str, key: str, model: str, items: list[dict[str, str]], scoped: bool, jobs: int,
               hardware_class: str) -> tuple[list[Any], int]:  # fmt: skip
    from agent_core.config import Settings
    from agent_core.providers.llama import LlamaServerProvider
    from agent_core.retrieval.classify import Case, topic_candidates, topic_of
    from agent_core.retrieval.index import SUBJECT_SLUGS

    settings = Settings()
    index = content_index()
    provider = LlamaServerProvider(url, key)
    pool = asyncio.Semaphore(max(1, jobs))
    unusable = 0

    async def one(item: dict[str, str]) -> Case:
        nonlocal unusable
        subjects = {SUBJECT_SLUGS[item["subject"]]} if scoped and item["subject"] in SUBJECT_SLUGS else None
        candidates = topic_candidates(index, item["text"], settings, subjects=subjects)
        async with pool:
            diagnosis = await _diagnose(provider, model, item, candidates, hardware_class)
        if diagnosis is None:
            unusable += 1
        chosen = topic_of(diagnosis, candidates) if diagnosis is not None else None
        return Case(item["id"], item["topic"], tuple(c.topic_id for c in candidates), chosen)

    try:
        cases = await asyncio.gather(*(one(i) for i in items))
    finally:
        await provider.close()
    return list(cases), unusable


def run_live(url: str, key: str, model: str, set_path: Path, out: Path, *, scoped: bool = True, jobs: int = 3,
             hardware_class: str = "mid") -> dict[str, Any]:  # fmt: skip
    """The live run; writes `<out>/report.json` and returns it with its gate errors."""
    from agent_core.retrieval.classify import summary

    items = load_set(set_path)
    cases, unusable = asyncio.run(_run(url, key, model, items, scoped, jobs, hardware_class))
    report = {"suite": SUITE, "model": model, "hardware_class": hardware_class,
              "mode": "session_subject" if scoped else "open", "unusable_replies": unusable, **summary(cases),
              "cases": [{"id": c.id, "label": c.label, "chosen": c.chosen, "retrieved": list(c.retrieved)}
                        for c in cases]}  # fmt: skip
    report["gate_errors"] = gate_errors(report)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


def gate_errors(report: dict[str, Any]) -> list[str]:
    """EVL-13: top-1 topic accuracy at or above `gate_topic_top1`."""
    from agent_core.config import Settings

    gate = Settings().gate_topic_top1
    if not report.get("total"):
        return ["classification: no questions were classified"]
    if report["top1"] < gate:
        return [f"classification: top-1 topic {report['top1']:.3f} is below the gate {gate:.2f} "
                f"({report['correct']}/{report['total']})"]  # fmt: skip
    return []
