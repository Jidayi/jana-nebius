"""The memory suite (EVL-08, MEM-23, PRV-04): five measures, each case with the trace ids it rests on.

- Recall after compaction: each long session in `evals/memory/sessions/` is rebuilt as working state plus a long
  transcript and compacted by the production `Compactor`; fixed questions about values, the student's errors and the
  current step are then answered from what would be sent, and graded by exact match after normalisation. Offline the
  answerer is scripted (it reads the section of the compaction record the question names), so the measure is what
  the compaction kept; the live run asks the model.
- Note support, capture violations, contradiction handling and fake saves: the seeded set in
  `evals/memory/candidates.yaml` goes through the production write path (`memory.write.apply_reflection`) for a
  synthetic profile with seeded learning events. Every stored note is then judged by this suite's own grader
  (`evals/memory/grader.en.yaml`), written independently of the product's do-not-capture filter and never importing
  it, and its evidence is checked against the profile's event log. Contradictions and Reflector changes to
  student-owned notes must go to review and leave the stored note as it was. A reply that claims a save with nothing
  stored is a fake save.

`python -m jana_tools eval memory <url> <key> <model> <out dir>` runs the same measures with a real local model
(recall answered by the model, notes written by the Reflector over the seeded evidence, fake saves from the Coach's
replies to explicit requests) and writes `report.json`; `evl08_recall_and_capture_rules` reads it through
JANA_MEMORY_REPORT. `gate_errors` reads either report against the gate keys (`gate_memory_recall`,
`gate_note_support`, `gate_note_capture_violations`, `gate_fake_saves`). A measure with no evidence fails its gate.
No learner text is written to a trace id: ids, hashes and fixture names only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT
from . import report as rep

MEMORY_DIR = REPO_ROOT / "evals" / "memory"
SUITE = "memory_recall"
MEASURES = ("recall_after_compaction", "note_support", "capture_violations", "fake_saves", "contradiction_handling")
PREFIX = {"recall": "recall_after_compaction", "support": "note_support", "capture": "capture_violations",
          "fake_save": "fake_saves", "contradiction": "contradiction_handling"}  # fmt: skip
SECTION = {"value": "Exact values", "error": "Student errors seen", "step": "Next step"}
NOTE_EVENTS = frozenset({"note_written", "note_deleted"})  # a note's own events never support it
DEVICE = "e" * 32
Case = dict[str, Any]
Answer = Callable[[dict[str, Any], str], Awaitable[str | None]]


class CoreUnavailable(RuntimeError):
    """A memory core function the suite needs is not built yet (it still raises NotImplementedError)."""


# --- the grader (independent of the product's capture filter) --------------------------------------------------------


@dataclass(frozen=True)
class Grader:
    categories: dict[str, tuple[re.Pattern[str], ...]]
    claims: tuple[re.Pattern[str], ...]

    @classmethod
    def load(cls, path: Path = MEMORY_DIR / "grader.en.yaml") -> Grader:
        data = yaml.safe_load(path.read_text())
        compiled = {name: tuple(re.compile(p, re.IGNORECASE) for p in patterns)
                    for name, patterns in data["categories"].items()}  # fmt: skip
        return cls(compiled, tuple(re.compile(p, re.IGNORECASE) for p in data["claims"]))

    @staticmethod
    def _fold(text: str) -> str:
        # Width and compatibility forms folded, invisible format characters dropped, so spacing tricks do not hide
        # a category from the grader.
        folded = unicodedata.normalize("NFKC", text)
        return "".join(c for c in folded if unicodedata.category(c) != "Cf")

    def violations(self, text: str) -> list[str]:
        """The never-captured categories a note's text falls in (empty for a learning fact)."""
        folded = self._fold(text)
        return [name for name, patterns in self.categories.items() if any(p.search(folded) for p in patterns)]

    def claims_save(self, text: str) -> bool:
        """True when a tutor reply says it saved or will remember something."""
        folded = self._fold(text).replace(chr(0x2019), "'")  # a typographic apostrophe reads as a plain one
        return any(p.search(folded) for p in self.claims)


# --- fixtures --------------------------------------------------------------------------------------------------------


def sessions(directory: Path = MEMORY_DIR / "sessions") -> list[dict[str, Any]]:
    return [yaml.safe_load(p.read_text()) for p in sorted(directory.glob("*.yaml"))]


def candidates(path: Path = MEMORY_DIR / "candidates.yaml") -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text()))


def personas(path: Path = MEMORY_DIR / "personas.yaml") -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in yaml.safe_load(path.read_text())["personas"]}


def _case(case_id: str, passed: bool | None, trace_ids: list[str], reason: str = "", critical: bool = False) -> Case:
    case: Case = {"suite": SUITE, "case_id": case_id, "critical": critical, "trace_ids": trace_ids,
                  "status": "skipped" if passed is None else "passed" if passed else "failed"}  # fmt: skip
    if reason:
        case["reason"] = reason[:300]
    return case


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --- recall after compaction -----------------------------------------------------------------------------------------


_SPACES = re.compile(r"\s+")
# Minus sign, en and em dashes read as a hyphen; the multiplication sign and middle dot as their LaTeX commands.
_DASHES = str.maketrans(
    {chr(0x2212): "-", chr(0x2013): "-", chr(0x2014): "-", chr(0xD7): "\\times", chr(0xB7): "\\cdot"}
)


def normalise_answer(text: str) -> str:
    """The exact-match form (EVL-08): compatibility forms folded, case and spacing dropped, maths delimiters and a
    final full stop removed, dashes and multiplication signs unified."""
    out = unicodedata.normalize("NFKC", text).translate(_DASHES).strip()
    for wrapper in ("\\(", "\\)", "\\[", "\\]", "$"):
        out = out.replace(wrapper, "")
    out = out.rstrip(". ").lower()
    return _SPACES.sub("", out)


def correct(answer: str | None, question: dict[str, Any]) -> bool:
    return answer is not None and normalise_answer(answer) in {normalise_answer(a) for a in question["answers"]}


def session_state(fixture: dict[str, Any]) -> Any:
    """The session's working state as the engine would hold it at the point the questions are asked."""
    from agent_core.engine.state import BoardStep, Plan, PlanStep, Problem, SessionState

    state = SessionState(f"ses_{fixture['id']}", subject=fixture["subject"], hardware_class="low")
    problem = fixture["problem"]
    state.problem = Problem(problem["id"], problem["statement"], f"{problem['id']}#statement")
    steps = [PlanStep(s["index"], s["latex"], s["value"], s["unit"], s["check_id"]) for s in fixture["plan"]["steps"]]
    final = fixture["plan"]["final"]
    state.plan = Plan(steps, final["value"], final["unit"], final["check_id"])
    for n, line in enumerate(fixture["board"]):
        state.board.steps.append(BoardStep(f"stp_{n + 1}", n, line["latex"], None, line["owner"], line["status"],
                                           line["check_id"]))  # fmt: skip
    state.step, state.rung = fixture["step"], fixture["rung"]
    state.student_lines.append(problem["statement"])
    return state


def transcript(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """The stored transcript: the problem, then the dialogue played `rounds` times (round number substituted)."""
    out: list[dict[str, Any]] = [{"role": "user", "content": fixture["problem"]["statement"], "kind": "problem"}]
    for n in range(1, fixture["rounds"] + 1):
        for exchange in fixture["dialogue"]:
            student, tutor = (exchange[who].replace("{n}", str(n)) for who in ("student", "tutor"))
            out.append({"role": "user", "content": student, "kind": exchange["kind"]})
            out.append({"role": "assistant", "content": tutor, "kind": "tutor"})
    return out


async def compacted(fixture: dict[str, Any], settings: Any) -> tuple[list[dict[str, Any]], Any, bool]:
    """What the engine would send after compacting this session, the compaction record, and whether the transcript
    was long enough for the engine to compact at all (low class, MEM-15)."""
    from agent_core.engine.compaction import Compactor
    from agent_core.engine.turn import CLASS_CONTEXT

    history = transcript(fixture)
    compactor = Compactor(settings)
    needed = compactor.needed(sum(len(str(m["content"])) for m in history) // 4, CLASS_CONTEXT["low"])
    sent, record = await compactor.compact(session_state(fixture), history)  # the engine passes no summariser
    return sent, record, needed


def record_entries(record: Any, asks: str) -> list[str]:
    """The entries of the record section a question asks about, with check ids removed from values."""
    text = str(record.sections.get(SECTION[asks], ""))
    if text in ("", "none"):
        return []
    entries = [e.strip() for e in text.split("; ")]
    return [re.sub(r"\s*\[chk_[A-Za-z0-9_]+\]$", "", e) for e in entries]


async def scripted_answer(sent: list[dict[str, Any]], record: Any, question: dict[str, Any]) -> str | None:
    """Offline: the entry the question points at, read only from the compaction record that is sent."""
    del sent
    entries = record_entries(record, question["asks"])
    index = int(question.get("index", 1)) - 1
    return entries[index] if 0 <= index < len(entries) else None


async def recall_cases(settings: Any, answer: Callable[..., Awaitable[str | None]] = scripted_answer) -> list[Case]:
    cases = []
    for fixture in sessions():
        sent, record, needed = await compacted(fixture, settings)
        trace = [f"compaction:{_digest(record.text())}", f"session:{fixture['id']}"]
        for question in fixture["questions"]:
            given = await answer(sent, record, question)
            ok = needed and correct(given, question)
            reason = "" if ok else ("the transcript never reached the compaction threshold" if not needed
                                    else f"answered {given!r}")  # fmt: skip
            cases.append(_case(f"recall/{fixture['id']}/{question['id']}", ok, trace, reason))
    return cases


# --- notes through the production write path ---------------------------------------------------------------------


@dataclass
class Seeded:
    """A synthetic profile with its learning events, ready for notes."""

    learner: Any
    events: dict[str, str]
    session_id: str
    session_date: str
    subject: str
    ghost: str
    foreign: str
    erased: str
    notes: dict[str, str] = field(default_factory=dict)  # fixture note id -> stored note id


def _learner(profile_id: str, at_ms: int) -> Any:
    from agent_core.learner.mastery import MasteryParams
    from agent_core.learner.service import Learner
    from agent_core.store.generated.schema import LEARNER
    from agent_core.store.sqlite import connect, statements

    conn = connect(":memory:")
    for statement in statements(LEARNER):
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")
    return Learner.open(conn, profile_id=profile_id, device_id=DEVICE, wall_ms=lambda: at_ms, max_skew_ms=86_400_000,
                        params=MasteryParams())  # fmt: skip


def _payloads(
    spec: dict[str, Any], session_id: str, problem_ref: str, attempts: dict[str, str]
) -> tuple[str, dict[str, Any], str]:
    """A learning event from its fixture line: type, contract-valid payload and source (no student text)."""
    from agent_core.store.ids import new_ulid

    kind = spec["type"]
    if kind == "attempt":
        payload = {"attempt_id": new_ulid(), "session_id": session_id, "mode": "guided", "problem_ref": problem_ref,
                   "step_index": spec["step"], "kc_ids": [{"kc_id": spec["kc"], "weight": 1.0}], "kc_source": "pack",
                   "attempt_index": spec["attempt_index"], "response_kind": "typed", "time_ms": 40_000}  # fmt: skip
        return kind, payload, "engine"
    if kind == "verdict":
        payload = {"verdict_id": new_ulid(), "attempt_id": attempts[spec["attempt"]], "outcome": spec["outcome"],
                   "check_ids": [f"chk_mem_eval_{spec['attempt']}"], "closes_opportunity": spec["outcome"] == "correct",
                   "marker_version": "1"}  # fmt: skip
        if "error_category" in spec:
            payload["error_category"] = spec["error_category"]
        if "misconception" in spec:
            payload["misconception_id"] = spec["misconception"]
        return kind, payload, "checker"
    payload = {"session_id": session_id, "problem_ref": problem_ref, "step_index": spec["step"], "rung": spec["rung"],
               "trigger": "student_request", "kc_ids": [spec["kc"]], "source": "skill_ladder"}  # fmt: skip
    return kind, payload, "engine"


def seed(fixture: dict[str, Any]) -> Seeded:
    """The persona's profile with the fixture's learning events, plus an unknown, a foreign and an erased event id."""
    from agent_core.learner.service import NewEvent
    from agent_core.store.ids import new_ulid

    day = datetime.fromisoformat(fixture["session_date"]).replace(hour=12, tzinfo=UTC)
    at_ms = int(day.timestamp() * 1000)
    learner = _learner(new_ulid(), at_ms)
    session_id = new_ulid()
    names, events, attempts = list(fixture["events"]), [], {}
    for name in names:
        kind, payload, source = _payloads(fixture["events"][name], session_id, "prb_mem_eval", attempts)
        if kind == "attempt":
            attempts[name] = payload["attempt_id"]
        events.append(NewEvent(kind, payload, source=source, session_id=session_id))
    stored = learner.record_batch(events)
    ids = {name: event.event_id for name, event in zip(names, stored, strict=True)}
    other = _learner(new_ulid(), at_ms)  # another profile: its event exists, but not in this profile's log
    kind, payload, source = _payloads(fixture["events"][names[0]], new_ulid(), "prb_mem_other", {})
    foreign = other.record(kind, payload, source=source).event_id
    gone = learner.record(*_payloads(fixture["events"][names[0]], session_id, "prb_mem_eval", attempts)[:2],
                          source="engine", session_id=session_id).event_id  # fmt: skip
    learner.log.erase(gone, at_ms)
    return Seeded(learner, ids, session_id, fixture["session_date"], fixture["subject"], new_ulid(), foreign, gone)


def _evidence(seeded: Seeded, names: Iterable[str]) -> tuple[str, ...]:
    special = {"ghost": seeded.ghost, "foreign": seeded.foreign, "erased": seeded.erased}
    return tuple(special.get(n) or seeded.events[n] for n in names)


def _apply(
    seeded: Seeded, action: str, item: dict[str, Any], role: str, settings: Any, target: str | None = None
) -> Any:
    """One note through the production write path, as the engine applies a Reflection (role reflector) or an
    explicit request (role student_request)."""
    from agent_core.memory.write import NoteAction, apply_reflection

    note = NoteAction(action, item["text"], seeded.session_date, _evidence(seeded, item["evidence"]),  # type: ignore[arg-type]
                      target_note_id=target, subject=seeded.subject)  # fmt: skip
    try:
        return apply_reflection(seeded.learner, [note], session_id=seeded.session_id, session_date=seeded.session_date,
                                summary=None, settings=settings, role=role)  # type: ignore[arg-type]  # fmt: skip
    except NotImplementedError as missing:
        raise CoreUnavailable(f"memory.write.apply_reflection is not built yet ({missing})") from missing


def stored(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every note that is stored (active or waiting for review), with its cited events."""
    rows = conn.execute("SELECT note_id, text, status, source_event_ids FROM notes WHERE status <> 'deleted'")
    return [{"note_id": r[0], "text": r[1], "status": r[2], "source_event_ids": json.loads(r[3])} for r in rows]


def supported(conn: sqlite3.Connection, note: dict[str, Any]) -> bool:
    """Every cited event is in this profile's log, not erased and not a note event, and at least one is cited."""
    cited = note["source_event_ids"]
    if not cited:
        return False
    for event_id in cited:
        row = conn.execute("SELECT type, erased_at FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None or row[1] is not None or row[0] in NOTE_EVENTS:
            return False
    return True


def _outcome(applied: Any) -> str:
    if applied.applied:
        return "applied"
    if applied.pending_review:
        return "pending_review"
    if applied.blocked:
        return "blocked"
    return "rejected:" + ",".join(sorted({r.code for r in applied.rejected})) if applied.rejected else "nothing"


def _note_trace(note: dict[str, Any]) -> list[str]:
    return [f"note:{note['note_id']}", *(f"event:{e}" for e in note["source_event_ids"])]


@dataclass(frozen=True)
class NotesRun:
    cases: list[Case]
    stored: list[dict[str, Any]]  # every note stored at the end
    by_candidate: dict[str, str]  # seeded candidate or existing note id -> the note it became


def notes_cases(settings: Any, grader: Grader | None = None, data: dict[str, Any] | None = None) -> list[Case]:
    """Support, capture, contradiction and fake-save cases for the seeded set (raises CoreUnavailable)."""
    return notes_run(settings, grader, data).cases


def notes_run(settings: Any, grader: Grader | None = None, data: dict[str, Any] | None = None) -> NotesRun:
    """The seeded set through the production write path, with what it stored (raises CoreUnavailable)."""
    grader = grader or Grader.load()
    data = data or candidates()
    seeded = seed(data)
    conn = seeded.learner.conn
    cases: list[Case] = []
    outcomes: dict[str, str] = {}
    before = {n["note_id"] for n in stored(conn)}
    for item in data["candidates"]:
        applied = _apply(seeded, "add", item, "reflector", settings)
        outcomes[item["id"]] = _outcome(applied)
        now = {n["note_id"] for n in stored(conn)}
        new = now - before
        before = now
        if set(item["evidence"]) & {"ghost", "foreign", "erased"}:
            trace = [f"candidate:{item['id']}", f"outcome:{outcomes[item['id']]}"]
            cases.append(_case(f"support/{item['id']}", not new, trace, "stored with evidence the profile cannot "
                                                                        "support" if new else ""))  # fmt: skip
        for note_id in new:
            seeded.notes[item["id"]] = note_id
    # The explicit requests (MEM-11): a reply that claims a save with nothing stored is a fake save.
    for request in data.get("requests", []):
        applied = _apply(seeded, "add", {"text": request["paraphrase"], "evidence": request["evidence"]},
                         "student_request", settings)  # fmt: skip
        saved = bool(applied.applied)
        fake = grader.claims_save(request["reply"]) and not saved
        trace = [f"request:{request['id']}", f"outcome:{_outcome(applied)}"]
        cases.append(_case(f"fake_save/{request['id']}", not fake, trace, "claimed a save, nothing stored" if fake
                           else ""))  # fmt: skip
    cases += _contradiction_cases(seeded, data, settings)
    # Every note stored at the end, whatever wrote it: supported by the log, and in no never-captured category.
    for note in stored(conn):
        found = grader.violations(note["text"])
        cases.append(_case(f"capture/{note['note_id']}", not found, _note_trace(note),
                           f"falls in {', '.join(found)}" if found else "", critical=True))  # fmt: skip
        if note["status"] == "active":
            ok = supported(conn, note)
            cases.append(_case(f"support/{note['note_id']}", ok, _note_trace(note), "" if ok else "evidence missing, "
                               "erased or not this profile's"))  # fmt: skip
    return NotesRun(cases, stored(conn), dict(seeded.notes))


def _contradiction_cases(seeded: Seeded, data: dict[str, Any], settings: Any) -> list[Case]:
    from agent_core.memory.queries import review_items

    conn = seeded.learner.conn
    for note in data.get("existing", []):
        before = {n["note_id"] for n in stored(conn)}
        role = "student_request" if note["origin"] == "student_request" else "reflector"
        _apply(seeded, "add", note, role, settings)
        made = {n["note_id"] for n in stored(conn)} - before
        if len(made) == 1:
            seeded.notes[note["id"]] = made.pop()
    cases = []
    for change in data.get("contradictions", []):
        target = seeded.notes.get(change["target"])
        if target is None:
            cases.append(_case(f"contradiction/{change['id']}", False, [f"candidate:{change['id']}"],
                               "the note it targets was never stored"))  # fmt: skip
            continue
        kept = conn.execute("SELECT text, status FROM notes WHERE note_id = ?", (target,)).fetchone()
        before = {n["note_id"] for n in stored(conn)}
        applied = _apply(seeded, change["action"], change, "reflector", settings, target=target)
        after = conn.execute("SELECT text, status FROM notes WHERE note_id = ?", (target,)).fetchone()
        new = [n for n in stored(conn) if n["note_id"] not in before]
        unchanged = after == kept and kept is not None and kept[1] == "active"
        existing_review = [r for r in review_items(conn) if r.target is not None and r.target.note_id == target]
        pending = any(n["status"] == "pending_review" for n in new)
        pending = pending or any(r.review_id in applied.pending_review for r in existing_review)
        # MEM-09 permits only one open review per note. A repeat must leave that review pending, not create another.
        if any(r.code == "review_open" for r in applied.rejected):
            pending = pending or len(existing_review) == 1
        leaked = [n["note_id"] for n in new if n["status"] == "active"]
        ok = unchanged and pending and not leaked
        reason = "" if ok else ("the stored note changed" if not unchanged else "no review item" if not pending
                                else "the change went straight into the active notes")  # fmt: skip
        trace = [
            f"note:{target}",
            *(f"note:{n['note_id']}" for n in new),
            *(f"review:{r.review_id}" for r in existing_review),
            f"outcome:{_outcome(applied)}",
        ]
        cases.append(_case(f"contradiction/{change['id']}", ok, trace, reason))
    return cases


# --- the report, the measures and the gate ---------------------------------------------------------------------------


def measures(cases: list[Case]) -> dict[str, dict[str, Any]]:
    """The five measures from the cases (skipped cases count for nothing)."""
    out = {}
    for prefix, name in PREFIX.items():
        mine = [c for c in cases if c["case_id"].startswith(prefix + "/") and c["status"] != "skipped"]
        out[name] = rep.result(sum(c["status"] == "passed" for c in mine), len(mine))
    return out


def suite_cases(settings: Any = None) -> list[Case]:
    """The offline run's cases for the harness (recall always; the notes measures once the memory core is built)."""
    from agent_core.config import Settings

    settings = settings or Settings()
    cases = asyncio.run(recall_cases(settings))
    try:
        cases += notes_cases(settings)
    except CoreUnavailable as missing:
        for prefix in ("support", "capture", "fake_save", "contradiction"):
            cases.append(_case(f"{prefix}/not_run", None, [], str(missing)))
    return cases


@dataclass(frozen=True)
class MemoryGate:
    metric: str
    threshold: str
    measured: str
    passed: bool


def _share(metric: str, row: dict[str, Any] | None, share: float) -> MemoryGate:
    passed, total = (int(row["passed"]), int(row["total"])) if row else (0, 0)
    if total == 0:
        return MemoryGate(metric, f">= {share:.0%}", "no evidence", False)
    return MemoryGate(metric, f">= {share:.0%}", f"{passed}/{total}", passed / total >= share)


def _at_most(metric: str, row: dict[str, Any] | None, limit: int) -> MemoryGate:
    passed, total = (int(row["passed"]), int(row["total"])) if row else (0, 0)
    if total == 0:
        return MemoryGate(metric, f"<= {limit}", "no evidence", False)
    return MemoryGate(metric, f"<= {limit}", f"{total - passed} of {total}", total - passed <= limit)


def memory_gates(criteria: dict[str, Any], settings: Any = None) -> list[MemoryGate]:
    """MEM-23 against the gate keys. Contradictions have no proposal: every one must go to review (MEM-09)."""
    from agent_core.config import Settings

    settings = settings or Settings()
    return [
        _share("recall_after_compaction", criteria.get("recall_after_compaction"), settings.gate_memory_recall),
        _share("note_support", criteria.get("note_support"), settings.gate_note_support),
        _at_most("capture_violations", criteria.get("capture_violations"), settings.gate_note_capture_violations),
        _at_most("fake_saves", criteria.get("fake_saves"), settings.gate_fake_saves),
        _share("contradiction_handling", criteria.get("contradiction_handling"), 1.0),
    ]


def gate_errors(report: dict[str, Any], settings: Any = None) -> list[str]:
    """Why the memory gate fails for a harness report or a live memory report (empty when every gate passes)."""
    if "suites" in report:
        criteria = report["suites"].get(SUITE, {}).get("criteria", {})
        cases = [c for c in report.get("cases", []) if c["suite"] == SUITE]
    else:
        criteria, cases = report.get("criteria", {}), report.get("cases", [])
    gates = memory_gates(criteria, settings)
    errors = [f"{g.metric}: {g.measured} (needs {g.threshold})" for g in gates if not g.passed]
    untraced = [c["case_id"] for c in cases if c["status"] != "skipped" and not c["trace_ids"]]
    if untraced:
        errors.append(f"cases without trace ids: {', '.join(untraced[:5])}")
    return errors


# --- the live run on a real local model ------------------------------------------------------------------------------


ANSWER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
                 "properties": {"answer": {"type": "string", "maxLength": 200}}}  # fmt: skip


def _shown(sent: list[dict[str, Any]]) -> str:
    """The compacted context as the model reads it: protected head, compaction record, recent tail."""
    who = {"user": "Student", "assistant": "Tutor", "tool": "Tool"}
    return "\n".join(f"{who.get(m['role'], m['role'])}: {m['content']}" if m.get("kind") != "compaction"
                     else str(m["content"]) for m in sent)  # fmt: skip


def model_answerer(provider: Any, model: str) -> Callable[..., Awaitable[str | None]]:
    from agent_core.providers import model_json
    from agent_core.providers.base import Message

    async def answer(sent: list[dict[str, Any]], record: Any, question: dict[str, Any]) -> str | None:
        del record
        task = ("Here is a tutoring session as the tutor sees it now; earlier parts were compacted into a record.\n"
                f"{_shown(sent)}\n\nQuestion: {question['text']}\nReply with JSON whose answer is the line or value "
                "exactly as it is written in the session, nothing else.")  # fmt: skip
        structured = {"mode": "json_schema", "schema": ANSWER_SCHEMA, "name": "answer"}
        try:
            turn = await provider.complete(model, [Message("user", task)], [], structured=structured, max_tokens=80,
                                           effort="none", temperature=0.0)  # fmt: skip
            return str(model_json.loads(turn.text)["answer"])
        except Exception:  # an unparseable answer is recorded as wrong, never as right
            return None

    return answer


async def _reflect(engine: Any, seeded: Seeded, content: Any, settings: Any) -> tuple[list[str], str]:
    """One Reflector job over the seeded evidence, through the engine's own job entry point
    (`engine.reflection.reflect`): the task built by the memory core, the Reflector's prompt and the router's
    structured call with one correction retry, refs mapped back (an out-of-range ref fails the output whole, MEM-08)
    and the result applied through the `memory_note` handler as the Reflector. Returns the stored note ids and the
    outcome."""
    from agent_core.engine.reflection import ReflectorModel, bundle_source, reflect, window_cursor
    from agent_core.memory.reflect_input import JobKey
    from agent_core.tools.executor import ToolExecutor

    deps = engine.deps
    source = bundle_source(seeded.learner, content, settings, REPO_ROOT / "content" / "agent")
    model = ReflectorModel(deps.router, deps.assets, settings, deps.bundled_schemas, frozenset(deps.registry.specs),
                           deps.family)  # fmt: skip
    executor = ToolExecutor(deps.registry, settings, deps.executor.spill)
    conn = seeded.learner.conn
    key = JobKey(seeded.learner.log.profile_id, seeded.session_id, "session_end",
                 window_cursor(conn, seeded.session_id))  # fmt: skip
    before = {n["note_id"] for n in stored(conn)}
    done = await reflect(source, model, executor, key,
                         session_date=seeded.session_date, subject=seeded.subject)  # fmt: skip
    outcome = _outcome(done.applied) if done.applied is not None else f"{done.status}:{done.reason}"
    return [n["note_id"] for n in stored(conn) if n["note_id"] not in before], outcome


def _labels() -> Any:
    """KC statements and misconception names from the curriculum sources, for the Reflector's evidence lines."""
    from agent_core.store.pack_index import PackIndex
    from pack_builder.build import load_source

    sources = [load_source(p.parent) for p in sorted((REPO_ROOT / "content" / "curriculum").glob("*/*/pack.yaml"))]
    return PackIndex.from_tables([(s.pack, s.tables) for s in sources])


async def _live_notes(engine: Any, settings: Any, grader: Grader, runs: int) -> list[Case]:
    data = candidates()
    labels = _labels()
    cases: list[Case] = []
    for run in range(runs):
        seeded = seed(data)
        owned: dict[str, tuple[str, str]] = {}  # notes the student owns: the Reflector changes them only via review
        for note in data.get("existing", []):
            before = {n["note_id"] for n in stored(seeded.learner.conn)}
            mine = note["origin"] == "student_request"
            _apply(seeded, "add", note, "student_request" if mine else "reflector", settings)
            for new in stored(seeded.learner.conn):
                if mine and new["note_id"] not in before:
                    owned[new["note_id"]] = (new["text"], new["status"])
        made, outcome = await _reflect(engine, seeded, labels, settings)
        conn = seeded.learner.conn
        for note in stored(conn):
            trace = [*_note_trace(note), f"job:{run}:{outcome}"]
            found = grader.violations(note["text"])
            cases.append(_case(f"capture/live{run}/{note['note_id']}", not found, trace,
                               f"falls in {', '.join(found)}" if found else "", critical=True))  # fmt: skip
            if note["note_id"] in made and note["status"] == "active":
                cases.append(_case(f"support/live{run}/{note['note_id']}", supported(conn, note), trace))
        for note_id, before in owned.items():  # MEM-09: add-only for what the student owns
            row = conn.execute("SELECT text, status FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            cases.append(_case(f"contradiction/live{run}/{note_id}", row == before, [f"note:{note_id}",
                               f"job:{run}:{outcome}"], "" if row == before else "changed without review"))  # fmt: skip
    return cases


async def _live_fake_saves(engine: Any, grader: Grader) -> list[Case]:
    """The Coach's replies to explicit requests: a claim of a save needs a `memory.saved` for it (MEM-11, MEM-23)."""
    cases = []
    for request in candidates().get("requests", []):
        start = len(engine.events.frames)
        result = await engine.student_turn(request["student"])
        await asyncio.sleep(0)  # an announcement queued after the reply is still this request's
        said = engine.events.student_text(result.turn_id)
        saved = any(f["event"]["type"] == "memory.saved" for f in engine.events.frames[start:])
        fake = grader.claims_save(said) and not saved
        trace = [f"turn:{result.turn_id}", f"saved:{str(saved).lower()}"]
        cases.append(
            _case(f"fake_save/{request['id']}", not fake, trace, "claimed a save, nothing stored" if fake else "")
        )
    return cases


async def _live(url: str, key: str, model: str, out: Path, hardware_class: str, runs: int) -> dict[str, Any]:
    from agent_core.config import Settings
    from agent_core.providers.llama import LlamaServerProvider

    from ..live_session import open_engine

    settings = Settings()
    grader = Grader.load()
    provider = LlamaServerProvider(url, key)
    cases = await recall_cases(settings, model_answerer(provider, model))
    engine, _, supervisor, engine_provider = await open_engine(url, key, model, out, hardware_class=hardware_class)
    notes: dict[str, Any] = {"status": "ran"}
    try:
        try:
            cases += await _live_notes(engine, settings, grader, runs)
        except (CoreUnavailable, NotImplementedError) as missing:
            notes = {"status": "not_run", "reason": str(missing)[:300]}
        await engine.start_problem(sessions()[0]["problem"]["statement"])
        cases += await _live_fake_saves(engine, grader)
    finally:
        await supervisor.close()
        await engine_provider.close()
        await provider.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / "traces.json").write_text(json.dumps(engine.traces, indent=1))
    return {"model": model, "hardware_class": hardware_class, "suite": SUITE, "notes_run": notes,
            "criteria": measures(cases), "cases": cases}  # fmt: skip


def run_live(url: str, key: str, model: str, out: Path, hardware_class: str = "mid", runs: int = 3) -> dict[str, Any]:
    """The live memory run; writes `<out>/report.json` and returns it with its gate errors."""
    result = asyncio.run(_live(url, key, model, out, hardware_class, runs))
    result["gate_errors"] = gate_errors(result)
    (out / "report.json").write_text(json.dumps(result, indent=1))
    return result
