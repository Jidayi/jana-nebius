"""The Reflector's task, built by code (MEM-06, MEM-08, AGT-26), and its output mapped back (MEM-08).

The input is numbered: existing notes inside the records wrapper, evidence lines rendered from event payloads and
pack labels (never the student's free text), and the KCs touched, each list with its own ref table so the output's
integers map back to ids. For an explicit request the escaped request text goes in a student-message block, to be
paraphrased. At most `reflector_max_evidence_lines` evidence lines, the newest kept.

`actions_from_reflection` maps a Reflection's integers back to ids. Any integer outside the list it refers to fails
the whole output (`RefOutOfRange`): nothing from that Reflection is applied, and the engine may retry once.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_core.config import Settings
from agent_core.memory.queries import ContentLabels, subject_notes
from agent_core.memory.refs import RefOutOfRange, RefTable
from agent_core.memory.render import escape_note, note_line, wrap_notes
from agent_core.memory.write import NoteAction, NoteActionKind
from agent_core.store.events import COLUMNS, MERGE_ORDER, StoredEvent
from agent_core.store.supersession import read_log

WritePoint = Literal["problem_end", "session_end", "idle", "onboarding_end", "explicit_request"]
EVIDENCE_TYPES = ("attempt", "verdict", "hint", "misconception_evidence", "mastery_check", "review",
                  "diagnostic_item", "detour")  # fmt: skip
ACTIONS: tuple[NoteActionKind, ...] = ("add", "update", "keep", "drop", "contradiction")
POINT_WORDS = {"problem_end": "the end of a problem", "session_end": "the end of the session",
               "idle": "a pause in the session", "onboarding_end": "the end of onboarding",
               "explicit_request": "the student asked to remember something"}  # fmt: skip
STUDENT_OPEN, STUDENT_CLOSE = "<student-message>", "</student-message>"


@dataclass(frozen=True)
class JobKey:
    """A Reflector job's identity: re-triggering the same key with no new events is skipped (AGT-26)."""

    profile_id: str
    session_id: str
    point: WritePoint
    cursor_seq: int


@dataclass(frozen=True)
class ReflectorInput:
    task: str  # the user message for the Reflector call
    notes: RefTable
    events: RefTable
    kcs: RefTable
    session_date: str
    key: JobKey


class ReflectionInvalid(ValueError):
    """A Reflection whose shape is wrong (an unknown action, a missing ref where one is needed)."""


def _kcs_of(type_: str, payload: Mapping[str, Any]) -> list[str]:
    if type_ == "attempt":
        return [k["kc_id"] for k in payload.get("kc_ids", []) if isinstance(k, dict) and "kc_id" in k]
    if type_ == "hint":
        return [k for k in payload.get("kc_ids", []) if isinstance(k, str)]
    kc = payload.get("kc_id")
    return [kc] if isinstance(kc, str) else []


def _evidence_line(
    type_: str, payload: Mapping[str, Any], content: ContentLabels, kc_refs: RefTable, attempts: Mapping[str, int]
) -> str:
    """One event in words built from its fields and pack labels only. A student's answer is never copied in."""
    skills = ", ".join(f"skill {kc_refs.ref_of(k)}" for k in _kcs_of(type_, payload)) or "the current step"
    if type_ == "attempt":
        seconds = round(int(payload.get("time_ms", 0)) / 1000)
        return (f"attempt {payload.get('attempt_index', 1)} on {skills} ({payload.get('response_kind')} answer, "
                f"{seconds} s, {payload.get('mode')} mode)")  # fmt: skip
    if type_ == "verdict":
        parts = [f"checked {payload.get('outcome')}"]
        if payload.get("error_category"):
            parts.append(f"error type {payload['error_category']}")
        mc = payload.get("misconception_id")
        if isinstance(mc, str):
            parts.append(f"mistake: {escape_note(content.misconception_name(mc) or mc)}")
        target = attempts.get(str(payload.get("attempt_id")))
        return "; ".join(parts) + (f" (for evidence {target})" if target else "")
    if type_ == "hint":
        return f"hint at rung {payload.get('rung')} on {skills} ({str(payload.get('trigger', '')).replace('_', ' ')})"
    if type_ == "misconception_evidence":
        mc = str(payload.get("misconception_id"))
        name = escape_note(content.misconception_name(mc) or mc)
        return f"mistake matched: {name} on {skills} (by {str(payload.get('evidence_source')).replace('_', ' ')})"
    if type_ == "mastery_check":
        return (f"mastery check on {skills}: item {payload.get('item_index')} {payload.get('item_result')}, "
                f"check {str(payload.get('check_state')).replace('_', ' ')}")  # fmt: skip
    if type_ == "review":
        return f"review of {skills}: rated {payload.get('rating')}"
    if type_ == "diagnostic_item":
        return f"diagnostic item on {skills}: {str(payload.get('response')).replace('_', ' ')}"
    return f"detour to a prerequisite of {skills}: {payload.get('action')}"


def build_input(
    conn: sqlite3.Connection,
    content: ContentLabels,
    key: JobKey,
    settings: Settings,
    *,
    session_date: str,
    subject: str | None,
    request_text: str | None = None,
) -> ReflectorInput:
    """The Reflector's task for one job: the session's learning events up to the job's cursor (the newest
    `reflector_max_evidence_lines`), the subject's active notes and the KCs touched, each numbered from 1. A re-marked
    verdict reads as its latest re-mark, at its own place, with the misconception evidence of that marking only
    (ASM-23, CUR-36)."""
    sid = key.session_id.removeprefix("ses_")
    placeholders = ", ".join("?" for _ in EVIDENCE_TYPES)
    cursor = key.cursor_seq if key.cursor_seq > 0 else None
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM events WHERE session_id = ? AND erased_at IS NULL"  # noqa: S608
        f" AND type IN ({placeholders}) ORDER BY {MERGE_ORDER}",
        (sid, *EVIDENCE_TYPES),
    )
    read = [e for e in read_log(map(StoredEvent.from_row, rows)) if cursor is None or e.seq <= cursor]
    events = [(e.event_id, e.type, e.payload) for e in read[-settings.reflector_max_evidence_lines :]]
    kc_refs = RefTable.of(kc for _, type_, payload in events for kc in _kcs_of(type_, payload))
    event_refs = RefTable.of(event_id for event_id, _, _ in events)
    attempts = {p["attempt_id"]: event_refs.ref_of(e) for e, t, p in events if t == "attempt" and "attempt_id" in p}
    notes = subject_notes(conn, subject)
    note_refs = RefTable.of(n.note_id for n in notes)

    lines = [f"Session date: {session_date}. This job runs at {POINT_WORDS[key.point]}."]
    lines += ["Existing notes (refer to them by number as target_ref):",
              wrap_notes([note_line(n, i) for i, n in enumerate(notes, start=1)])]  # fmt: skip
    lines.append("Evidence (refer to it by number in evidence_refs):")
    lines += [f"[{event_refs.ref_of(e)}] {_evidence_line(t, p, content, kc_refs, attempts)}" for e, t, p in events]
    if not events:
        lines.append("(none)")
    lines.append("Skills touched (refer to one by number as kc_ref):")
    lines += [f"[{i}] {escape_note(content.kc_statement(kc) or kc)}" for i, kc in enumerate(kc_refs.ids, start=1)]
    if not kc_refs.ids:
        lines.append("(none)")
    if key.point == "explicit_request" and request_text:
        lines += ["The student's request, to paraphrase, never to copy:",
                  f"{STUDENT_OPEN}{escape_note(request_text)}{STUDENT_CLOSE}"]  # fmt: skip
    return ReflectorInput("\n".join(lines), note_refs, event_refs, kc_refs, session_date, key)


def _ref(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise RefOutOfRange(f"ref {value!r} is not an integer")
    return int(value)


# What a model copies into a note's text from the input's list form ("[3] 2026-10-09 · ... (evidence 12)"): a leading
# ref, a leading ISO date with its separator, and trailing evidence or ref tags. They are not part of the note.
_ECHOED_LEAD = re.compile(r"^\s*(?:\[\d+\]\s*)?(?:\d{4}-\d{2}-\d{2}\s*(?:[\u00b7\u2022\u2013\u2014:|-]\s*)?)?")
_ECHOED_TAIL = re.compile(r"(?:\s*[\(\[](?:evidence|refs?|events?)?\s*[\d,\s]+[\)\]])+\s*\.?\s*$", re.IGNORECASE)


def clean_note_text(text: str) -> str:
    """The note's sentence without list formatting echoed from the input (its date and evidence have their own
    fields). Anything else is left for the write policy to judge."""
    return _ECHOED_TAIL.sub("", _ECHOED_LEAD.sub("", text, count=1)).strip()


def actions_from_reflection(
    reflection: Mapping[str, Any], given: ReflectorInput, *, subject: str | None
) -> list[NoteAction]:
    """The Reflection's notes with every integer mapped back through the input's ref tables (MEM-08).

    One integer outside its list (an evidence ref, a target ref or a KC ref) raises `RefOutOfRange` for the whole
    output, so nothing of it is applied. `nothing_new` with no notes gives no actions."""
    notes = reflection.get("notes") or []
    if not isinstance(notes, list):
        raise ReflectionInvalid("notes must be a list")
    out: list[NoteAction] = []
    for item in notes:
        if not isinstance(item, Mapping) or item.get("action") not in ACTIONS:
            raise ReflectionInvalid("each note needs a known action")
        action = cast(NoteActionKind, item["action"])
        evidence_refs = item.get("evidence_refs") or []
        if not isinstance(evidence_refs, list):
            raise ReflectionInvalid("evidence_refs must be a list")
        evidence = given.events.resolve_all(evidence_refs)  # each must be a plain integer in the list
        target_ref, kc_ref = _ref(item.get("target_ref")), _ref(item.get("kc_ref"))
        target = given.notes.resolve(target_ref) if target_ref is not None else None
        kc = given.kcs.resolve(kc_ref) if kc_ref is not None else None
        if action != "add" and target is None:
            raise ReflectionInvalid(f"{action} needs a target_ref")
        text = clean_note_text(str(item.get("text", "")))
        out.append(NoteAction(action, text, str(item.get("date", "")), tuple(evidence),
                              target if action != "add" else None, kc, subject))  # fmt: skip
    return out
