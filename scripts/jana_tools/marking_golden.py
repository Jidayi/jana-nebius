"""The marking suite's golden cases (CUR-14, CUR-15, CUR-18; TABLE EVL-01a, Marking).

`evals/marking/<type>.yaml` holds items of one type of TABLE CUR-14a and student responses with the verdict each must
get, each case tagged with the rows of TABLE CUR-15a it covers (`<row>.<facet>`); a case with `hints` also closes an
opportunity at that hint rung and states whether it may count towards mastery (the bottom-out row). The items and
responses are synthetic, written for the suite: no student's work and no examination text.

`evals/marking/signatures.yaml` is the seeded misconception set: a small misconception library, the items it probes
and wrong answers labelled with the misconception that produced them, each worked out by hand from the item's
quantities (the `label` says how), never by the matcher; cases labelled `none` hold no misconception and must match
nothing. Every case is marked by `marking.mark`, as the app marks, with the worker's checkers run in-process.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

MARKING = REPO_ROOT / "evals" / "marking"
SIGNATURES = "signatures"
# The marking suite's criterion for the seeded misconception set (CUR-18): the harness writes it into the suite report
# and the S2 release gate "Misconception signatures match labelled answers" reads it (TABLE EVL-17a).
SIGNATURE_CRITERION = "signature_match"
RULE_ROWS = ("numeric_tolerance", "units", "algebraic_form", "chemical_equations", "journal_entries",
             "structured_parts", "hints")  # fmt: skip
RULE_FACETS = (
    "numeric_tolerance.default", "numeric_tolerance.sig_figs", "numeric_tolerance.item_override",
    "units.equivalent", "units.missing", "units.wrong_dimension",
    "algebraic_form.equivalent", "algebraic_form.not_in_form",
    "chemical_equations.species", "chemical_equations.balance", "chemical_equations.non_lowest",
    "chemical_equations.states_required", "chemical_equations.states_optional", "chemical_equations.states_ignored",
    "journal_entries.line_order", "journal_entries.alias", "journal_entries.amounts_exact",
    "journal_entries.currency_symbol", "journal_entries.narration",
    "structured_parts.mark_points", "structured_parts.b_independent", "structured_parts.ecf",
    "structured_parts.no_ecf",
    "hints.bottom_out",
)  # fmt: skip
_COUNTER = itertools.count()
RETRIES = 3


@dataclass(frozen=True)
class Result:
    case_id: str
    item_type: str
    passed: bool
    detail: str = ""
    rows: tuple[str, ...] = ()
    kind: str = ""
    check_ids: tuple[str, ...] = ()
    digest: str = ""  # the verdict's record: outcome, marks, category, misconception and criteria


async def run_tool(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The worker's checker, in-process: the result value and a check id, or nothing when it refuses."""
    from tool_worker.functions import FUNCTIONS
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    check_id = f"chk_golden_{name}_{next(_COUNTER)}"
    context = CallContext("golden", check_id, {}, {}, lambda: False, settings={})
    try:
        value, _ = FUNCTIONS[name].implementation(args, context)
        for _ in range(RETRIES):  # a cold or loaded in-process checker can overrun its time slice: ask again
            if value.get("reason") != "timeout":
                break
            value, _ = FUNCTIONS[name].implementation(args, context)
    except WorkerError:
        return None, None
    return value, check_id


async def convert(quantity: str, to: str) -> Any:
    """The worker's unit conversion, in-process."""
    from agent_core.engine.marking import Converted
    from tool_worker.functions.units import units_convert
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    check_id = f"chk_golden_units_{next(_COUNTER)}"
    try:
        value, _ = units_convert({"quantity": quantity, "to": to}, CallContext("golden", check_id, {}, {},
                                                                               lambda: False, settings={}))  # fmt: skip
    except WorkerError:
        return None
    return Converted(Decimal(value["value"]["decimal"]), check_id)


def load(root: Path = MARKING) -> dict[str, dict[str, Any]]:
    """The item-type golden files by name (the seeded misconception set is read by `load_signatures`)."""
    return {p.stem: yaml.safe_load(p.read_text()) for p in sorted(root.glob("*.yaml")) if p.stem != SIGNATURES}


def load_signatures(root: Path = MARKING) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((root / f"{SIGNATURES}.yaml").read_text())
    return data


def _digest(verdict: Any) -> str:
    record = {"outcome": verdict.outcome, "marks": verdict.marks_awarded, "of": verdict.marks_available,
              "error_category": verdict.error_category, "misconception_id": verdict.misconception_id,
              "criteria": list(verdict.criteria)}  # fmt: skip
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def _verdict_problems(verdict: Any, expect: dict[str, Any]) -> list[str]:
    problems = []
    if verdict.outcome != expect["outcome"]:
        problems.append(f"outcome {verdict.outcome}, expected {expect['outcome']}")
    if "marks_awarded" in expect and abs(verdict.marks_awarded - float(expect["marks_awarded"])) > 1e-9:
        problems.append(f"marks {verdict.marks_awarded}, expected {expect['marks_awarded']}")
    for name in ("error_category", "misconception_id"):
        if name in expect and getattr(verdict, name) != expect[name]:
            problems.append(f"{name} {getattr(verdict, name)}, expected {expect[name]}")
    results = {c["criterion_id"]: c["result"] for c in verdict.criteria}
    for criterion, result in (expect.get("criteria") or {}).items():
        if results.get(str(criterion)) != result:
            problems.append(f"criterion {criterion} {results.get(str(criterion))}, expected {result}")
    if "follow_through" in expect:
        carried = any(c.get("follow_through") for c in verdict.criteria)
        if carried != expect["follow_through"]:
            problems.append(f"follow_through {carried}, expected {expect['follow_through']}")
    if verdict.outcome != "unverifiable" and not verdict.provenance:
        problems.append("no check id or key criterion (ASM-02)")
    return problems


def _payload_problems(verdict: Any) -> list[str]:
    from agent_core.contracts import errors

    payload = verdict.payload(verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                              closes_opportunity=True)  # fmt: skip
    return [f"payload: {e}" for e in errors("learning/learning-event#/$defs/payload_verdict", payload)]


def _mastery_problems(verdict: Any, hints: dict[str, Any], settings: Any) -> list[str]:
    """The opportunity closed at the case's hint rung: whether it counts as a success towards mastery (CUR-15a)."""
    from agent_core.learner.mastery import MasteryParams, Opportunity, observations

    rows = observations(Opportunity("practice", (verdict.outcome,), int(hints["max_rung"])),
                        MasteryParams.from_settings(settings))  # fmt: skip
    success = any(y == 1 for y, _ in rows)
    return [] if success == bool(hints["mastered"]) else [f"mastery success {success}, expected {hints['mastered']}"]


def run_item_cases(root: Path = MARKING) -> list[Result]:
    from agent_core.config import Settings
    from agent_core.engine.marking import mark

    settings = Settings()
    out = []
    for name, data in load(root).items():
        for case in data["cases"]:
            item = data["items"][case["item"]]
            verdict = asyncio.run(mark(item, str(case.get("part", "a")), case["response"], convert, settings,
                                       run_tool))  # fmt: skip
            problems = _verdict_problems(verdict, case["expect"]) + _payload_problems(verdict)
            if "hints" in case:
                problems += _mastery_problems(verdict, case["hints"], settings)
            out.append(Result(f"{name}/{case['id']}", str(item["type"]), not problems, "; ".join(problems),
                              tuple(case.get("rows") or ()), check_ids=verdict.check_ids,
                              digest=_digest(verdict)))  # fmt: skip
    return out


def run_signature_cases(root: Path = MARKING) -> list[Result]:
    """Each seeded answer marked with the misconception library: `passed` when the verdict names the labelled
    misconception (or none for a case labelled `none`)."""
    from agent_core.config import Settings
    from agent_core.engine.marking import mark
    from agent_core.engine.signatures import SignatureContext

    settings = Settings()
    data = load_signatures(root)
    out = []
    for case in data["cases"]:
        item = data["items"][case["item"]]
        context = SignatureContext(misconceptions=data["misconceptions"], conventions=data.get("conventions") or {},
                                   chart=data.get("chart"), step_error=case.get("step_error"))  # fmt: skip
        verdict = asyncio.run(mark(item, str(case.get("part", "a")), case["response"], convert, settings, run_tool,
                                   signatures=context))  # fmt: skip
        expected = case["expect"]
        problems = [] if verdict.misconception_id == expected else [
            f"matched {verdict.misconception_id}, expected {expected} ({verdict.outcome})"]  # fmt: skip
        if expected is not None and verdict.outcome not in ("incorrect", "partial"):
            problems.append(f"outcome {verdict.outcome}: a labelled answer is wrong")
        problems += _payload_problems(verdict)
        out.append(Result(f"{SIGNATURES}/{case['id']}", str(item["type"]), not problems, "; ".join(problems),
                          kind=str(case["kind"]), check_ids=verdict.check_ids, digest=_digest(verdict)))  # fmt: skip
    return out


def signature_share(results: list[Result]) -> tuple[int, int]:
    """Labelled `answer_transform` and `structural` cases whose misconception was named, of all such cases (CUR-18)."""
    labelled = [r for r in results if r.kind in ("answer_transform", "structural")]
    return sum(r.passed for r in labelled), len(labelled)
