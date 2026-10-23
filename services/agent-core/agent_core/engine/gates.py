"""Stop gates before a reply is accepted (AGT-08, the S1 forms of AGT-09 and AGT-10; PED-08, PED-10 H1 and H2).

Order: schema, verified (number provenance), no answer leak, budget. A gate that fires rejects the draft (it stays
in the private buffer and the trace), adds a short nudge and the engine loops. Limits: nudges per gate and per turn,
and a regeneration limit for leaks by hardware class; at a limit the gate's exhaustion action applies. The pending
answer is the latest candidate that passed every rejecting gate; an early end ships it or the canned turn."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from agent_core.assets.visual_kinds import claim_numbers
from agent_core.config import Settings
from agent_core.engine.claims import evaluate
from agent_core.engine.pointing import strip_markers
from agent_core.engine.spoken import latex_to_plain, to_written
from agent_core.engine.state import NUMBER, SessionState, numbers_in

GATES = ("schema", "verified", "no_answer_leak", "one_ask", "budget")
UNITS_SCALE: dict[str, dict[str, Fraction]] = {
    # Unit-converted forms of a withheld value (S1 subset: length, time, speed, mass, acceleration).
    "m": {"cm": Fraction(100), "mm": Fraction(1000), "km": Fraction(1, 1000)},
    "s": {"ms": Fraction(1000), "min": Fraction(1, 60)},
    "m/s": {"km/h": Fraction(18, 5), "cm/s": Fraction(100)},
    "kg": {"g": Fraction(1000)},
    "m/s^2": {"cm/s^2": Fraction(100)},
}
ONES = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
}
TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
ELIMINATION = re.compile(r"\b(it'?s not|it is not|isn'?t|not)\b[^.?!]{0,80}\b(or|nor)\b[^.?!]{0,40}", re.I)


def words_to_numbers(text: str) -> list[Fraction]:
    """Spelled-out numbers ("twenty-four point five", "one hundred and two")."""
    found: list[Fraction] = []
    tokens = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    i = 0
    while i < len(tokens):
        if tokens[i] not in ONES and tokens[i] not in TENS:
            i += 1
            continue
        whole = 0
        current = 0
        while i < len(tokens) and (
            tokens[i] in ONES or tokens[i] in TENS or tokens[i] in ("hundred", "thousand", "and")
        ):
            word = tokens[i]
            if word in ONES:
                current += ONES[word]
            elif word in TENS:
                current += TENS[word]
            elif word == "hundred":
                current *= 100
            elif word == "thousand":
                whole += current * 1000
                current = 0
            i += 1
        value = Fraction(whole + current)
        if i < len(tokens) and tokens[i] == "point":
            i += 1
            digits = ""
            while i < len(tokens) and tokens[i] in ONES and ONES[tokens[i]] < 10:
                digits += str(ONES[tokens[i]])
                i += 1
            if digits:
                value += Fraction(int(digits), 10 ** len(digits))
        found.append(value)
    return found


def _close(a: Fraction, b: Fraction, rel: float) -> bool:
    if a == b:
        return True
    # Exact arithmetic: an expression in a draft may be far outside the float range.
    return abs(a - b) <= Fraction(rel) * max(abs(b), Fraction(1, 10**12))


def _rounded_match(written: str, value: Fraction) -> bool:
    """A written number that equals the withheld value rounded half up to its own precision (at least 2 s.f.)."""
    digits = written.replace("-", "").replace(".", "").lstrip("0")
    if len(digits) < 2 or value == 0 or "/" in written:  # a written fraction is exact: never a rounded form
        return False
    decimals = len(written.split(".")[1]) if "." in written else 0
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP) == Decimal(written)


@dataclass
class LeakFinding:
    kind: str  # exact, rounded, unit_converted, spelled_out, elimination
    surface: str
    detail: str


def leak_findings(
    surfaces: dict[str, str],
    withheld: list[tuple[Fraction, str | None]],
    settings: Settings,
    options: list[str] | None = None,
    givens: set[Fraction] | None = None,
    texts: list[str] | None = None,
) -> list[LeakFinding]:
    """Every way a draft reveals a withheld value, on every scanned surface (say, board, card, visual labels): the
    value as written, rounded, unit-converted, spelled out or spoken (VOC-08 read back), as LaTeX or any expression
    equal to it, by elimination, and a withheld equation or expression by normalised string match (AGT-09)."""
    findings: list[LeakFinding] = []
    if texts:
        findings.extend(_text_leaks(surfaces, texts))
    if not withheld:
        return findings
    rel = settings.leak_relative_tolerance
    for surface, text in surfaces.items():
        findings.extend(_expression_leaks(surface, text, withheld, rel, givens))
        text = _written_form(text)
        written = [m.group(0) for m in re.finditer(r"-?\d+(?:\.\d+)?(?:/\d+)?", text.replace("\u2212", "-"))]
        for value, unit in withheld:
            for token, parsed in zip(written, numbers_in(" ".join(written)), strict=False):
                if givens and parsed in givens and not _close(parsed, value, rel):
                    continue  # a value the question or the student gave is never a leak by rounding or units
                if _close(parsed, value, rel):
                    findings.append(LeakFinding("exact", surface, token))
                elif _rounded_match(token, value):
                    findings.append(LeakFinding("rounded", surface, token))
                elif unit in UNITS_SCALE and any(_close(parsed, value * k, rel) for k in UNITS_SCALE[unit].values()):
                    findings.append(LeakFinding("unit_converted", surface, token))
            for spelled in words_to_numbers(text):
                if _close(spelled, value, rel):
                    findings.append(LeakFinding("spelled_out", surface, str(spelled)))
        if options and ELIMINATION.search(text):
            named = [o for o in options if o.lower() in text.lower()]
            if len(named) >= max(1, len(options) - 1):
                findings.append(LeakFinding("elimination", surface, "rules out all but one option"))
    return findings


def _written_form(text: str) -> str:
    """The surface with LaTeX arithmetic and spoken numbers as plain digits ("forty-nine over two" is 49/2)."""
    written = to_written(latex_to_plain(text))
    return re.sub(r"(?<=\d)\s*/\s*(?=\d)", "/", written) if written != text else text


_ARITHMETIC_SPAN = re.compile(r"[\d(][\d.\s+\-*/^()]*[\d)]")
_HAS_OPERATOR = re.compile(r"\d\s*[-+*/^(]|\)\s*[-+*/^(\d]")


def _expression_leaks(surface: str, text: str, withheld: list[tuple[Fraction, str | None]], rel: float,
                      givens: set[Fraction] | None) -> list[LeakFinding]:  # fmt: skip
    """Any arithmetic expression on the surface whose exact value is withheld (symbolic equivalence, AGT-09)."""
    findings = []
    plain = latex_to_plain(to_written(text)) if text else ""
    for match in _ARITHMETIC_SPAN.finditer(plain):
        span = match.group(0)
        if not _HAS_OPERATOR.search(span):
            continue  # a lone number is handled as a written value
        value = evaluate(span)
        if value is None or (givens and value in givens):
            continue
        for hidden, _ in withheld:
            if _close(value, hidden, rel):
                findings.append(LeakFinding("symbolic", surface, span.strip()[:80]))
    return findings


def normalised(text: str) -> str:
    """Equations, formulas and ledger totals compared as strings: case, spacing and LaTeX spelling removed."""
    plain = latex_to_plain(text).lower().replace("**", "^").replace("\u2212", "-")
    return re.sub(r"[\s$]|\\[a-z]+", "", plain)


MIN_TEXT_LEAK = 3  # shorter normalised strings ("x=") match too much prose to mean anything


def _text_leaks(surfaces: dict[str, str], texts: list[str]) -> list[LeakFinding]:
    findings = []
    wanted = [n for n in (normalised(t) for t in texts) if len(n) >= MIN_TEXT_LEAK]
    for surface, text in surfaces.items():
        seen = normalised(text)
        for hidden in wanted:
            if hidden in seen:
                findings.append(LeakFinding("string", surface, hidden[:80]))
    return findings


def withheld_texts(state: SessionState) -> list[str]:
    """Withheld results that are not single numbers (an equation, an expression, a factorised form), by the same
    reach rule as `SessionState.withheld` (PED-08)."""
    plan = state.plan
    if plan is None or state.mode != "guided" or state.solved:
        return []
    shown_through = state.step if state.rung >= 4 else state.step - 1
    found = [s.value for s in plan.steps if s.index > shown_through and s.value and _symbolic(s.value, s.unit)]
    last = plan.steps[-1].index if plan.steps else 0
    if shown_through < last and _symbolic(plan.final_value, plan.final_unit):
        found.append(plan.final_value)
    derived = [normalised(line) for line in state.student_lines]
    return [t for t in found if not any(normalised(t) in d for d in derived)]


def _symbolic(value: str, unit: str | None) -> bool:
    """A result written with letters beyond its unit: an expression or equation, not a number."""
    bare = value.replace(unit, "") if unit else value
    bare = re.sub(r"\\[A-Za-z]+|\{|\}", " ", bare.rsplit("=", 1)[-1])
    return bool(re.search(r"[A-Za-z]", bare))


def surfaces(draft: dict[str, Any]) -> dict[str, str]:
    """Every surface of a tutor turn a student can read, see or hear: `say`, `say_spoken`, board lines, reasons,
    terms and prompts, the card's prompt and options, and every label-like text in a visual request."""
    found = {"say": draft.get("say") or ""}
    for n, op in enumerate(draft.get("board") or []):
        for key in ("latex", "prompt", "reason"):
            if op.get(key):
                found[f"board/{n}/{key}"] = op[key]
        for k, term in enumerate(op.get("terms") or []):
            found[f"board/{n}/terms/{k}"] = term
    card = draft.get("card") or {}
    if card.get("prompt"):
        found["card/prompt"] = card["prompt"]
    for n, option in enumerate(card.get("options") or []):
        found[f"card/option/{n}"] = f"{option.get('label', '')} {option.get('latex') or ''}"
    for n, visual in enumerate(draft.get("visual") or []):
        for path, text in _visual_texts(visual, f"visual/{n}"):
            found[path] = text
    if draft.get("say_spoken"):
        # Cue markers are ids, never heard: the spoken surface is gated as it is spoken (VOC-07, VOC-10).
        found["say_spoken"] = strip_markers(draft["say_spoken"])
    return found


def claim_surfaces(draft: dict[str, Any]) -> dict[str, str]:
    """The numbers a visual request shows through its parameters (a graph's points, a force's magnitude), one surface
    each: what the student reads off the picture is leak-scanned like any label (AGT-09, VSL-12). Only the leak gate
    reads these; the visual's own resolution traces them to their checks."""
    found: dict[str, str] = {}
    for n, visual in enumerate(draft.get("visual") or []):
        params = visual.get("params") if isinstance(visual, dict) else None
        if isinstance(params, dict):
            for written, where in claim_numbers(str(visual.get("type")), params):
                found[f"visual/{n}/{where}"] = written
    return found


VISUAL_TEXT_KEYS = frozenset({"caption", "label", "labels", "text", "title", "note", "alt", "alt_text", "legend",
                              "annotation", "annotations", "tick_labels"})  # fmt: skip


def _visual_texts(node: Any, path: str) -> list[tuple[str, str]]:
    """Student-visible strings in a visual request: the values under label-like keys, at any depth."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in VISUAL_TEXT_KEYS and isinstance(value, str):
                found.append((f"{path}/{key}", value))
            elif key in VISUAL_TEXT_KEYS and isinstance(value, list):
                found.extend((f"{path}/{key}/{i}", v) for i, v in enumerate(value) if isinstance(v, str))
                found.extend(_visual_texts([v for v in value if not isinstance(v, str)], f"{path}/{key}"))
            elif isinstance(value, dict | list):
                found.extend(_visual_texts(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(_visual_texts(item, f"{path}/{i}"))
    return found


CHECK_STATUSES = ("correct", "incorrect", "equivalent_unsimplified")


def verdict_problems(draft: dict[str, Any], state: SessionState) -> list[str]:
    """Board operations that would hide or change what a check decided (AGT-14, API-41): a step checked `incorrect`
    stays incorrect (never re-marked or revised), and a check status needs the step's own check id."""
    problems = []
    steps = state.board.steps
    for n, op in enumerate(draft.get("board") or []):
        kind, index = op.get("op"), op.get("step")
        step = steps[index - 1] if isinstance(index, int) and 1 <= index <= len(steps) else None
        if step is None:
            continue
        downgraded = kind == "revise_step" or (kind == "mark_step" and op.get("status") != "incorrect")
        if step.status == "incorrect" and downgraded:
            problems.append(f"board/{n}: step {index} was checked incorrect and stays incorrect")
        elif (
            kind == "mark_step"
            and op.get("status") in CHECK_STATUSES
            and (step.check_id is None or op.get("check_id") != step.check_id)
        ):
            problems.append(f"board/{n}: {op.get('status')} needs the check id of step {index}")
    return problems


def untraced_numbers(surfaces: dict[str, str], state: SessionState, context_numbers: set[Fraction]) -> list[str]:
    """Numbers a student could read that trace to no check, the question, the student or engine state (H1)."""
    allowed = state.provenance() | context_numbers

    def traced(value: Fraction) -> bool:
        return any(_close(value, a, 1e-9) for a in allowed)

    missing = []
    for surface, text in surfaces.items():
        for match in NUMBER.finditer(text.replace("\u2212", "-")):
            token = match.group(0)
            values = numbers_in(token)
            # A fraction written "a/b" reads as \frac{a}{b} does, part by part: a formula's coefficient
            # ("E_k = 1/2 mv^2") traces whichever notation the Coach chose.
            parts = [numbers_in(part) for part in token.lstrip("-").split("/")] if "/" in token else []
            if values and not traced(values[0]) and not (parts and all(p and traced(p[0]) for p in parts)):
                missing.append(f"{surface}: {values[0]}")
    return missing


@dataclass
class GateRecord:
    gate: str
    fired: bool = False
    nudges: int = 0
    attempt: int = 0
    outcome: str = "skipped"

    def as_trace(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "fired": self.fired,
            "nudges": self.nudges,
            "attempt": max(1, self.attempt),
            "outcome": self.outcome,
        }


@dataclass
class GateBook:
    """Firings, nudges and limits for one turn."""

    settings: Settings
    hardware_class: str = "mid"
    records: dict[str, GateRecord] = field(default_factory=lambda: {g: GateRecord(g) for g in GATES})
    nudges_total: int = 0
    pending: Any = None  # the latest candidate that passed every rejecting gate

    def regeneration_limit(self, gate: str) -> int:
        if gate == "no_answer_leak":
            return (
                self.settings.leak_regenerations_low
                if self.hardware_class == "low"
                else self.settings.leak_regenerations
            )
        if gate == "one_ask" and self.hardware_class in self.settings.lean_classes:
            return self.settings.one_ask_regenerations_lean  # the repaired reply is shipped (D128)
        return self.settings.gate_nudges_per_gate

    def may_nudge(self, gate: str) -> bool:
        record = self.records[gate]
        return record.nudges < self.regeneration_limit(gate) and self.nudges_total < self.settings.gate_nudges_per_turn

    def fire(self, gate: str) -> bool:
        """Record a firing; True when a nudge may be sent (else the gate is exhausted)."""
        record = self.records[gate]
        record.fired = True
        record.attempt += 1
        if self.may_nudge(gate):
            record.nudges += 1
            self.nudges_total += 1
            return True
        return False

    def passed(self, gate: str) -> None:
        record = self.records[gate]
        record.attempt += 1
        if record.outcome in ("skipped", "passed", "passed_after_nudge"):
            record.outcome = "passed_after_nudge" if record.fired else "passed"

    def exhausted(self, gate: str, outcome: str) -> None:
        self.records[gate].outcome = outcome

    def as_trace(self) -> list[dict[str, Any]]:
        return [r.as_trace() for r in self.records.values()]


NUDGES = {
    "schema": "Your reply did not match the output format: {errors}. Reply again with the JSON object only.",
    "verified": "Use only checked values: {detail} has no check. Leave it out or use a value from the board.",
    "claim": "Your draft claims something its checks do not support ({detail}). Use the checked working exactly.",
    "term": "Your draft names a term wrongly: {detail} Use the course's term and meaning.",
    "verdict": "Your draft changes a checked result ({detail}). Keep the checked status on the board.",
    "no_answer_leak": "Your draft gives a result the student has not reached yet. Give a rung-{rung} hint instead.",
    "budget": "Budget nearly used: finish this step.",
    "one_ask": "End with exactly one short question or instruction for the student, with nothing after it.",
}

WAITING = ("student_answer", "student_choice")  # a turn that waits for the student (PED-28)
_SENTENCES = re.compile(r"[^.?!]+[.?!]+[\"')\]]*|[^.?!]+$")


def ask_problem(draft: dict[str, Any], *, spoken: bool = False) -> str | None:
    """PED-28: a turn that waits for the student ends with exactly one question or instruction and nothing after it.
    Returns the surface and fault (`two_asks`, `ask_not_last`), or None. A turn whose last sentence is not a question
    is taken as ending with its instruction: only question marks are counted, never guessed imperatives."""
    if draft.get("expects") not in WAITING:
        return None
    for name in ("say", "say_spoken") if spoken else ("say",):
        text = draft.get(name)
        if not text:
            continue
        parts = [p.strip() for p in _SENTENCES.findall(strip_markers(text)) if p.strip()]
        asks = [n for n, p in enumerate(parts) if p.rstrip("\"')]").endswith("?")]
        if len(asks) > 1:
            return f"{name}: two_asks"
        if asks and asks[0] != len(parts) - 1:
            return f"{name}: ask_not_last"
    return None
