"""Outcomes by skill version (SKL-28): mastery gain, hint use and answer-leak rate per `(skill, version)`, from pilot
research exports (EVL-22) and evaluation runs, so a regression after a skill edit is attributed to that edit.

- **Pilot.** Each consented research export (one student) carries, per tutoring session, the skills delivered by
  `(name, version)`, the session's hints and its mastery gain (the share right on the session's KCs after it less the
  share right before it; `agent_core.store.exports`). Figures are means per session with a 95% interval, shown only
  from `research_min_participants` students (PRD-19); below that only the counts are reported.
- **Evaluation.** The colocated skill-eval cases (SKL-21) run each skill's own version; a case whose `no_answer_leak`
  assertion failed is a leak, and the rate carries a Wilson 95% interval. Device sessions do not observe leaks.
- **Attribution.** Consecutive versions of one skill are compared; a metric that moved the wrong way with the two
  intervals apart is a regression of the later version, naming the edit `from` -> `to`.

`python -m jana_tools eval skill-outcomes [--pilot DIR] [--eval-runs DIR] [--out F]` reads the opened research
export bodies (`*.json`) and a skill-eval run's `done/` case records. Pilot response volume does not exist yet: the
tests feed synthetic exports and cases."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from itertools import pairwise
from pathlib import Path
from typing import Any

from .harness.report import wilson

Z95 = 1.959963984540054
LEAK = "no_answer_leak"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".") if p.isdigit())


def _mean(values: list[float]) -> dict[str, Any] | None:
    """The mean with a normal-approximation 95% interval (None without values)."""
    if not values:
        return None
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    half = Z95 * sd / math.sqrt(n)
    return {"value": round(mean, 6), "interval": [round(mean - half, 6), round(mean + half, 6)], "n": n}


def pilot_rows(exports: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[tuple[int, dict[str, Any]]]]:
    """(student index within this run, session row) per (skill, version), from the exports' skill sessions."""
    out: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    for student, export in enumerate(exports):
        if export.get("kind") != "research_export":
            continue
        for row in export.get("skill_sessions", []):
            for skill in row.get("skills", []):
                out.setdefault((str(skill["name"]), str(skill["version"])), []).append((student, row))
    return out


def eval_rows(cases: Iterable[Mapping[str, Any]], versions: Mapping[str, str]) -> dict[tuple[str, str], list[bool]]:
    """Leak or not per scored skill-eval case, by (skill, version); `versions` maps a skill body's sha256 to its
    version. A case that errored is not scored."""
    out: dict[tuple[str, str], list[bool]] = {}
    for case in cases:
        version = versions.get(str(case.get("sha256")))
        if version is None or case.get("error"):
            continue
        leaked = any(str(f).startswith(f"{LEAK}:") for f in case.get("failures", []))
        out.setdefault((str(case["skill"]), version), []).append(leaked)
    return out


Sessions = Mapping[tuple[str, str], list[tuple[int, dict[str, Any]]]]
Leaks = Mapping[tuple[str, str], list[bool]]


def outcomes(pilot: Sessions, evaluation: Leaks, min_participants: int) -> list[dict[str, Any]]:
    rows = []
    for skill, version in sorted(set(pilot) | set(evaluation), key=lambda k: (k[0], _version(k[1]))):
        sessions = pilot.get((skill, version), [])
        participants = len({s for s, _ in sessions})
        suppressed = participants < min_participants
        gains = [float(r["mastery_gain"]) for _, r in sessions if r.get("mastery_gain") is not None]
        leaks = evaluation.get((skill, version), [])
        low, high = wilson(sum(leaks), len(leaks))
        rows.append({
            "skill": skill, "version": version,
            "pilot": {"participants": participants, "sessions": len(sessions), "suppressed": suppressed,
                      "mastery_gain": None if suppressed else _mean(gains),
                      "hints_per_session": None if suppressed else _mean([float(r["hints"]) for _, r in sessions])},
            "eval": {"cases": len(leaks), "answer_leak_rate": None if not leaks else
                     {"value": round(sum(leaks) / len(leaks), 6), "interval": [round(low, 6), round(high, 6)]}},
        })  # fmt: skip
    return rows


def regressions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each metric that got worse from one version of a skill to the next with the intervals apart, as the edit's."""
    found = []
    by_skill: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_skill.setdefault(row["skill"], []).append(row)
    for skill, versions in sorted(by_skill.items()):
        versions.sort(key=lambda r: _version(r["version"]))
        for before, after in pairwise(versions):
            for metric, source, worse in (("mastery_gain", "pilot", "lower"), ("hints_per_session", "pilot", "higher"),
                                          ("answer_leak_rate", "eval", "higher")):  # fmt: skip
                a, b = before[source][metric], after[source][metric]
                if a is None or b is None:
                    continue
                apart = (
                    b["interval"][0] > a["interval"][1] if worse == "higher" else b["interval"][1] < a["interval"][0]
                )
                if apart:
                    found.append({"skill": skill, "from": before["version"], "to": after["version"], "metric": metric,
                                  "before": a["value"], "after": b["value"]})  # fmt: skip
    return found


def report(pilot_dir: Path | None, runs_dir: Path | None, skills_root: Path | None = None) -> dict[str, Any]:
    from agent_core.config import Settings

    from .skill_evals import RESULTS, read_results
    from .skills import SKILLS

    exports = [json.loads(p.read_text()) for p in sorted(pilot_dir.glob("*.json"))] if pilot_dir else []
    cases = [json.loads(p.read_text()) for p in sorted((runs_dir / "done").glob("*.json"))] if runs_dir else []
    versions = {str(r["sha256"]): str(r["version"]) for r in read_results(RESULTS).values() if "sha256" in r}
    from agent_core.assets.skills import KINDS, discover, parse

    versions |= {s.sha256: s.version for s in (parse(p) for p in discover(skills_root or SKILLS, KINDS))}
    rows = outcomes(pilot_rows(exports), eval_rows(cases, versions), Settings().research_min_participants)
    return {"outcomes": rows, "regressions": regressions(rows)}
