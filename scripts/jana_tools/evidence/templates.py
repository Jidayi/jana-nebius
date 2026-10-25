"""Fill-in templates: the hand-written M23 governance records and the M24 probe records generated from the drill
checklists, so a template always has the shape its gate reads and every value a gate needs is a FILL-IN placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_core.config import Settings

from .. import REPO_ROOT
from ..release.field_evidence import SOURCES
from .drills import DEVICE, DRILLS, Answers, Ask, Drill, Repeat
from .placeholders import FILL_IN

TEMPLATES = Path(__file__).parent / "templates"
M24_TEMPLATES = TEMPLATES / "m24"

# M23 governance records: template file -> (record kind, requirement ids, what the record is)
GOVERNANCE = {
    "counsel": ("counsel", "PRV-07, PRD-22 (decision D13)", "counsel's review of the pilot-country legal mapping"),
    "tabletop": ("tabletop", "PRV-21 (with OPS-31)", "the stage-gate SEV1 tabletop exercise and its timings"),
    "redteam": ("redteam", "PRV-23", "the red-team report and privacy audit for this candidate"),
    "security": ("security", "SEC-25", "the security test programme results for this candidate"),
    "protocol": ("protocol", "EVL-22, BIZ-15, BIZ-16", "the registered pilot protocol and frozen analysis script"),
    "wtp": ("wtp", "BIZ-13, PRD-08", "the willingness-to-pay research linked to decision D10"),
    "experiments": ("experiments", "BIZ-14", "the register of pricing experiments (may be empty)"),
    "country": ("country", "PRD-22", "the pilot-country checklist, before it is signed"),
    "contacts": ("contacts", "SEC-26", "licence-holder references for a security release"),
}


def governance_template(name: str) -> Any:
    return json.loads((TEMPLATES / f"{name}.json").read_text())


HINTS = {
    "time": "date-time with zone",
    "date": "YYYY-MM-DD",
    "yes": "true or false",
    "int": "a whole number",
    "number": "a number",
    "proof": "the SHA-256 of this raw proof file, which is also listed in the index",
    "sha": "64 lowercase hex",
    "list": "a list of strings",
    "dates": "a list of YYYY-MM-DD dates",
    "numbers": "a list of numbers",
    "steps": "a list of step names",
    "zone": "an IANA time zone",
}
INTERACTIVE = (" (Enter = now)", " (Enter for none)", "; Enter for none", " (Enter if none)", " (Enter before S4)")


def _placeholder(ask: Ask) -> str:
    """The template wording: what the stored value is, then the checklist's question without keyboard hints."""
    question = ask.question.removeprefix("Path to ")
    for hint in INTERACTIVE:
        question = question.replace(hint, "")
    kind = "one of " + ", ".join(ask.choices) if ask.kind == "choice" else HINTS.get(ask.kind, "text")
    return f"{FILL_IN}: {kind}: {question}"


def _answers(drill: Drill) -> Answers:
    answers: Answers = {}
    for item in drill.asks:
        if isinstance(item, Repeat):
            answers[item.key] = [{**item.template, **{ask.key: _placeholder(ask) for ask in item.asks}}]
        else:
            answers[item.key] = _placeholder(item)
    return answers


def m24_templates(cfg: Settings | None = None) -> dict[str, Any]:
    """file name -> template, for every JANA_M24_EVIDENCE record and the index that lists them."""
    cfg = cfg or Settings()
    result: dict[str, Any] = {}
    records: dict[str, Any] = {}
    for drill in DRILLS.values():
        for name, data in drill.build(_answers(drill), cfg, {}).items():
            if name.startswith("@"):
                continue  # governance side records have their own hand-written templates
            result[f"{name}.json"] = {
                "format": "jana.ops.probe.1",
                "test_name": name,
                "candidate_commit": f"{FILL_IN}: the 40-character commit id of the candidate tested",
                "spec_revision": f"{FILL_IN}: the specification revision in spec.lock",
                "source": SOURCES[name],
                "started_at": f"{FILL_IN}: date-time with zone when the test or drill started",
                "completed_at": f"{FILL_IN}: date-time with zone when it finished",
                "data": {**data, "device": f"{FILL_IN}: {DEVICE.question}"},
            }
            records[name] = {
                "source": SOURCES[name],
                "reviewer": f"{FILL_IN}: who checked this record against the raw proofs",
                "proofs": [
                    {"path": f"{drill.id}/{name}.probe.json", "sha256": f"{FILL_IN}: SHA-256 of the probe record"},
                    {"path": f"{FILL_IN}: each raw proof file, inside the folder", "sha256": f"{FILL_IN}: its SHA-256"},
                ],
            }
    result["evidence.json"] = {
        "format": "jana.ops.evidence.1",
        "candidate_commit": f"{FILL_IN}: the 40-character commit id of the candidate tested",
        "spec_revision": f"{FILL_IN}: the specification revision in spec.lock",
        "synthetic_data_only": True,
        "records": dict(sorted(records.items())),
    }
    return result


def render(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def stale_templates() -> list[str]:
    expected = {name: render(value) for name, value in m24_templates().items()}
    present = {p.name: p.read_text() for p in M24_TEMPLATES.glob("*.json")} if M24_TEMPLATES.is_dir() else {}
    return [
        f"{M24_TEMPLATES.relative_to(REPO_ROOT)}/{name} is stale; run: uv run python -m jana_tools evidence templates "
        "--write"
        for name in sorted(expected.keys() | present.keys())
        if expected.get(name) != present.get(name)
    ]


def write_templates(folder: Path = M24_TEMPLATES) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    expected = m24_templates()
    for stale in folder.glob("*.json"):
        if stale.name not in expected:
            stale.unlink()
    for name, value in expected.items():
        (folder / name).write_text(render(value))
    return sorted(expected)
