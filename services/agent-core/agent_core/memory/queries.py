"""The fixed read queries of the learner model and the episodic layer (MEM-04).

Every read of memory for a prompt, a tool or a view goes through one of these, with parameters set by code: a model
never writes query text (MEM-05). Content labels (KC statements, topic names, misconception names) come from the
verified installed pack through `ContentLabels` (`agent_core.store.pack_index.PackIndex` implements it).

A note's owner and version are read from the event log, not a column: the first `note_written` says who asked for
it (envelope source `student` for a note saved at the student's request, MEM-11), a `correction` on the note by the
student or the device adult makes it theirs (MEM-09), and the newest event touching the note is the version a review
is pinned to. Every query is ordered on stable keys, so the same tables always give the same answer (LRN-05).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from agent_core.config import Settings

HintUse = Literal["low", "medium", "high"]
# A KC's state (LRN-09); its student-facing label is the string catalogue's (G99), never a probability.
StateLabel = Literal["not_started", "learning", "ready_to_check", "mastered", "needs_review", "moved_on"]
NoteOrigin = Literal["reflector", "student_request", "corrected"]
OWNER_SOURCES = frozenset({"student", "adult"})


class ContentLabels(Protocol):
    """What the queries need from the installed packs to name things in the student's words."""

    def kc_statement(self, kc_id: str) -> str | None: ...
    def topic_of(self, kc_id: str) -> str | None: ...
    def kcs_in_topic(self, topic_id: str) -> Sequence[str]: ...
    def misconception_name(self, misconception_id: str) -> str | None: ...
    def prerequisites(self) -> Mapping[str, Sequence[str]]: ...


@dataclass(frozen=True)
class ProfileSummary:
    level: str
    subjects: tuple[str, ...]
    exam_distance: str | None  # "in N days" to the nearest exam from the session date, or "past"; never the date
    reading_level: str | None
    support_level: str | None
    solution_policy: str


@dataclass(frozen=True)
class KcLine:
    kc_id: str
    statement: str
    state: StateLabel
    hint_use: HintUse


@dataclass(frozen=True)
class MisconceptionLine:
    misconception_id: str
    name: str  # the pack's student-facing name (the id when no installed pack names it)
    status: Literal["active", "resolving"]
    evidence: int


@dataclass(frozen=True)
class NoteRecord:
    """A stored note as the readers see it. `origin` decides who may change it (MEM-09); `last_event_id` pins a
    review to the version shown."""

    note_id: str
    text: str
    status: Literal["active", "pending_review"]
    subject: str | None
    kc_ids: tuple[str, ...]
    created_at: int
    origin: NoteOrigin
    last_event_id: str
    updated_at: int = 0  # the last write of its text (an update keeps the note id and its created_at)
    source_event_ids: tuple[str, ...] = ()

    @property
    def day(self) -> str:
        """The date the note's current text was written (UTC; G95)."""
        return datetime.fromtimestamp((self.updated_at or self.created_at) / 1000, UTC).date().isoformat()


@dataclass(frozen=True)
class Preference:
    key: str
    value: str
    origin: Literal["override", "inferred"]
    confidence: float | None = None


@dataclass(frozen=True)
class DueReview:
    kc_id: str
    due_at: int


@dataclass(frozen=True)
class TranscriptLine:
    turn_ref: int  # the turn's position in the session, 1-based
    source: Literal["student", "tutor", "board"]
    text: str


# --- profile -----------------------------------------------------------------------------------------------------


def _setting(conn: sqlite3.Connection, name: str) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (name,)).fetchone()
    return json.loads(row[0]) if row is not None else None


def memory_saving(conn: sqlite3.Connection, settings: Settings) -> bool:
    """Whether the student has memory saving on (MEM-06; a student preference, on by default)."""
    stored = _setting(conn, "memory_saving")
    return bool(stored) if isinstance(stored, bool) else bool(settings.memory_saving)


def _exam_distance(dates: Iterable[str], today: str | None) -> str | None:
    if today is None:
        return None
    try:
        now = date.fromisoformat(today)
    except ValueError:
        return None
    parsed = []
    for text in dates:
        try:
            parsed.append(date.fromisoformat(text))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    ahead = sorted(d for d in parsed if d >= now)
    return f"in {(ahead[0] - now).days} days" if ahead else "past"


def profile_summary(
    conn: sqlite3.Connection, *, today: str | None = None, settings: Settings | None = None
) -> ProfileSummary:
    """Level, subjects, exam distance from `today` (the session date), reading and support level, and the adult's
    answer policy (tier 6, never cut). An empty profile reads as blanks rather than failing."""
    policy = "on_request"
    row = conn.execute("SELECT level, subjects, exam_date, reading_level, support_level FROM profile").fetchone()
    if row is None:
        return ProfileSummary("", (), None, None, None, str(policy))
    subjects: list[str] = []
    exam_dates: list[str] = [row[2]] if row[2] else []
    for entry in json.loads(row[1] or "[]"):
        if isinstance(entry, str):
            subjects.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("subject"), str):
            subjects.append(entry["subject"])
            if isinstance(entry.get("exam_date"), str):
                exam_dates.append(entry["exam_date"])
    return ProfileSummary(str(row[0]), tuple(subjects), _exam_distance(exam_dates, today), row[3], row[4], str(policy))


# --- knowledge components and misconceptions -------------------------------------------------------------------------


def hint_use(hints: int, attempts: int, settings: Settings) -> HintUse:
    """How much the student leans on hints for a KC: hints per closed attempt against the two thresholds."""
    if attempts <= 0:
        return "low"
    share = hints / attempts
    if share >= settings.snapshot_hint_use_high:
        return "high"
    return "medium" if share >= settings.snapshot_hint_use_medium else "low"


def _kc_rows(conn: sqlite3.Connection) -> dict[str, tuple[str, int, int, int]]:
    """Per KC: state, hints, closed attempts, and when the student last attempted it directly (a neighbour's
    evidence moves the mastery row's own time, so the attempts table is the measure of "recently practised")."""
    practised = dict(
        conn.execute(
            "SELECT json_extract(value, '$.kc_id'), max(occurred_at) FROM attempts, json_each(attempts.kc_ids)"
            " GROUP BY 1"
        ).fetchall()
    )
    rows = conn.execute("SELECT kc_id, status, hints_used, attempts FROM kc_mastery")
    return {r[0]: (r[1], r[2], r[3], int(practised.get(r[0]) or 0)) for r in rows}


def kc_line(kc_id: str, row: tuple[str, int, int, int] | None, content: ContentLabels, settings: Settings) -> KcLine:
    statement = content.kc_statement(kc_id) or kc_id
    if row is None:
        return KcLine(kc_id, statement, "not_started", "low")
    return KcLine(kc_id, statement, cast(StateLabel, row[0]), hint_use(row[1], row[2], settings))


def top_kcs(
    conn: sqlite3.Connection,
    content: ContentLabels,
    topic_id: str | None,
    n: int,
    settings: Settings,
    *,
    focus: Sequence[str] = (),
) -> list[KcLine]:
    """The n most relevant KCs of the topic with state label and hint-use band (`snapshot_hint_use_*`).

    Relevance, in order: the KCs of the current problem (`focus`), then the topic's KCs the student has practised,
    most recently seen first, then the rest of the topic's KCs (not started, even where a neighbour's evidence has
    reached them) in id order. Without a topic, every KC with a row is a candidate."""
    if n <= 0:
        return []
    rows = _kc_rows(conn)
    pool = list(content.kcs_in_topic(topic_id)) if topic_id is not None else list(rows)
    in_pool = set(pool)
    chosen: list[str] = [kc for kc in dict.fromkeys(focus) if topic_id is None or kc in in_pool]
    seen = set(chosen)
    practised = {kc for kc, row in rows.items() if row[2] > 0}
    with_evidence = sorted((kc for kc in pool if kc in practised and kc not in seen), key=lambda k: (-rows[k][3], k))
    fresh = sorted(kc for kc in pool if kc not in practised and kc not in seen)
    chosen += with_evidence + fresh
    return [kc_line(kc, rows.get(kc), content, settings) for kc in chosen[:n]]


def all_kcs(conn: sqlite3.Connection, content: ContentLabels, settings: Settings) -> list[KcLine]:
    """Every KC with evidence, in id order (the knows page groups them by state)."""
    rows = _kc_rows(conn)
    return [kc_line(kc, rows[kc], content, settings) for kc in sorted(rows)]


def active_misconceptions(
    conn: sqlite3.Connection, content: ContentLabels, topic_id: str | None, n: int
) -> list[MisconceptionLine]:
    """Active and resolving misconceptions of the topic, with evidence counts and student-facing names: active ones
    first, then by evidence, then most recently seen."""
    if n <= 0:
        return []
    rows = conn.execute(
        "SELECT misconception_id, kc_id, status, evidence_count FROM learner_misconceptions"
        " WHERE status IN ('active', 'resolving')"
        " ORDER BY status = 'resolving', evidence_count DESC, last_seen_at DESC, misconception_id"
    ).fetchall()
    out: list[MisconceptionLine] = []
    for mc_id, kc_id, status, evidence in rows:
        if topic_id is not None and content.topic_of(kc_id) != topic_id:
            continue
        name = content.misconception_name(mc_id) or mc_id
        out.append(MisconceptionLine(mc_id, name, status, int(evidence)))
    return out[:n]


def weak_prerequisites(conn: sqlite3.Connection, content: ContentLabels, kc_id: str, settings: Settings) -> list[str]:
    """Prerequisite KCs of `kc_id` below the mastery threshold (the engine's detour decision): those with evidence
    that are not confirmed and whose probability is under `mastery_ready_p`. A prerequisite never practised has no
    evidence either way and is not called weak."""
    needs = list(dict.fromkeys(content.prerequisites().get(kc_id, ())))
    out = []
    for need in needs:
        row = conn.execute("SELECT status, p_mastery, attempts FROM kc_mastery WHERE kc_id = ?", (need,)).fetchone()
        if row is not None and row[2] > 0 and row[0] != "mastered" and row[1] < settings.mastery_ready_p:
            out.append(need)
    return out


# --- notes -------------------------------------------------------------------------------------------------------


@dataclass
class NoteHistory:
    """What the event log says about one note: who first wrote it, whether its owner corrected it, its newest
    event, and the review links that point at it."""

    first_source: str | None = None
    corrected: bool = False
    last_seq: int = 0
    last_event_id: str = ""
    events: list[tuple[int, str, str, str, dict[str, Any]]] = field(default_factory=list)  # seq, id, type, source, p


def note_histories(conn: sqlite3.Connection, note_ids: Collection[str] | None = None) -> dict[str, NoteHistory]:
    """The note events of the log grouped by note: writes, deletions and corrections aimed at a note (MEM-09)."""
    out: dict[str, NoteHistory] = {}
    rows = conn.execute(
        "SELECT seq, event_id, type, source, payload FROM events WHERE erased_at IS NULL"
        " AND (type IN ('note_written', 'note_deleted')"
        " OR (type = 'correction' AND json_extract(payload, '$.target') = 'note')) ORDER BY seq"
    )
    for seq, event_id, type_, source, raw in rows:
        payload = json.loads(raw)
        note_id = payload.get("note_id") if type_ != "correction" else payload.get("target_id")
        if not isinstance(note_id, str) or (note_ids is not None and note_id not in note_ids):
            continue
        history = out.setdefault(note_id, NoteHistory())
        if type_ == "note_written" and history.first_source is None:
            history.first_source = source
        if type_ == "correction" and source in OWNER_SOURCES:
            history.corrected = True
        history.last_seq, history.last_event_id = seq, event_id
        history.events.append((seq, event_id, type_, source, payload))
    return out


def origin_of(history: NoteHistory | None) -> NoteOrigin:
    if history is not None and history.corrected:
        return "corrected"
    if history is not None and history.first_source == "student":
        return "student_request"
    return "reflector"


def last_event_id(conn: sqlite3.Connection, note_id: str) -> str | None:
    """The newest event touching a note: the version a review item is pinned to (MEM-09)."""
    history = note_histories(conn, {note_id}).get(note_id)
    return history.last_event_id if history is not None else None


_NOTE_COLUMNS = "note_id, text, status, subject, kc_ids, created_at, updated_at, source_event_ids"


def _records(conn: sqlite3.Connection, rows: Sequence[Sequence[Any]]) -> list[NoteRecord]:
    histories = note_histories(conn, {r[0] for r in rows})
    out = []
    for note_id, text, status, subject, kc_ids, created_at, updated_at, sources in rows:
        history = histories.get(note_id)
        out.append(
            NoteRecord(
                note_id=note_id,
                text=text,
                status=status,
                subject=subject,
                kc_ids=tuple(json.loads(kc_ids)) if kc_ids else (),
                created_at=int(created_at),
                origin=origin_of(history),
                last_event_id=history.last_event_id if history is not None else "",
                updated_at=int(updated_at),
                source_event_ids=tuple(json.loads(sources)),
            )
        )
    return out


def notes_by_id(conn: sqlite3.Connection, note_ids: Collection[str]) -> dict[str, NoteRecord]:
    """Active and pending notes by id (deleted notes are gone)."""
    if not note_ids:
        return {}
    marks = ", ".join("?" for _ in note_ids)
    rows = conn.execute(
        f"SELECT {_NOTE_COLUMNS} FROM notes WHERE status <> 'deleted' AND note_id IN ({marks})",  # noqa: S608
        tuple(note_ids),
    ).fetchall()
    return {r.note_id: r for r in _records(conn, rows)}


def _subject_clause(subject: str | None) -> tuple[str, tuple[Any, ...]]:
    # A note with no subject (from onboarding, say) belongs to every subject.
    return (" AND (subject = ? OR subject IS NULL)", (subject,)) if subject is not None else ("", ())


def recent_notes(conn: sqlite3.Connection, subject: str | None, n: int) -> list[NoteRecord]:
    """The n newest active notes of the subject (pending notes never reach a prompt, MEM-09)."""
    if n <= 0:
        return []
    return subject_notes(conn, subject)[:n]


def subject_notes(conn: sqlite3.Connection, subject: str | None) -> list[NoteRecord]:
    """Every active note of the subject, newest first: the source of index mode (MEM-13)."""
    clause, params = _subject_clause(subject)
    rows = conn.execute(
        f"SELECT {_NOTE_COLUMNS} FROM notes WHERE status = 'active'{clause}"  # noqa: S608 - fixed clause
        " ORDER BY updated_at DESC, note_id DESC",
        params,
    ).fetchall()
    return _records(conn, rows)


def stored_notes(
    conn: sqlite3.Connection, statuses: Collection[str] = ("active", "pending_review")
) -> list[NoteRecord]:
    """Notes in the given statuses across subjects, newest first (bounds, the knows page, the snapshot)."""
    marks = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT {_NOTE_COLUMNS} FROM notes WHERE status IN ({marks})"  # noqa: S608 - placeholders only
        " ORDER BY updated_at DESC, note_id DESC",
        tuple(statuses),
    ).fetchall()
    return _records(conn, rows)


# --- review items (MEM-09) ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    """A change the Reflector may not make on its own, waiting for the student or the device adult.

    `replace`: a pending note that would supersede `target` (a contradiction, or an update of a note the student
    owns); its id is the pending note's id. `drop`: a proposal to remove a note the student owns; its id is the
    proposal's event id and it has no pending note. A resolution must quote both versions shown
    (`pending_event_id`, `target_event_id`) and is refused if either has moved since."""

    review_id: str
    kind: Literal["replace", "drop"]
    pending: NoteRecord | None
    target: NoteRecord | None
    pending_event_id: str
    target_event_id: str | None


def review_items(conn: sqlite3.Connection) -> list[ReviewItem]:
    """Every open review item, oldest first. A replace item stays open while its note is pending; a drop item while
    its note exists and neither its owner has answered nor a newer drop proposal for the same note replaced it."""
    histories = note_histories(conn)
    live = {n.note_id: n for n in stored_notes(conn)}
    items: list[tuple[int, ReviewItem]] = []
    linked: set[str] = set()
    for target_id, history in histories.items():
        drop: tuple[int, str] | None = None
        for seq, event_id, type_, source, payload in history.events:
            if type_ == "correction" and source in OWNER_SOURCES:
                drop = None  # the owner answered every earlier proposal for this note
            if type_ != "correction" or source != "reflector" or payload.get("action") != "dispute":
                continue
            raw_value = payload.get("value")
            value: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
            pending_id = value.get("pending_note_id")
            if isinstance(pending_id, str):
                linked.add(pending_id)
                pending = live.get(pending_id)
                if pending is not None and pending.status == "pending_review":
                    target = live.get(target_id)
                    items.append((seq, ReviewItem(pending_id, "replace", pending, target, pending.last_event_id,
                                                  target.last_event_id if target else None)))  # fmt: skip
            elif value.get("proposal") == "drop":
                drop = (seq, event_id)
        target = live.get(target_id)
        if drop is not None and target is not None and target.status == "active":
            items.append((drop[0], ReviewItem(drop[1], "drop", None, target, drop[1], target.last_event_id)))
    for note in live.values():  # a pending note with no link (written by an older build) is still reviewable
        if note.status == "pending_review" and note.note_id not in linked:
            items.append((histories[note.note_id].last_seq if note.note_id in histories else 0,
                          ReviewItem(note.note_id, "replace", note, None, note.last_event_id, None)))  # fmt: skip
    items.sort(key=lambda item: (item[0], item[1].review_id))
    return [item for _, item in items]


# --- preferences, reviews, the transcript ----------------------------------------------------------------------------


def _shown(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def preferences(conn: sqlite3.Connection) -> list[Preference]:
    """Overrides first, then inferences, most confident first."""
    overrides: list[Preference] = []
    inferred: list[Preference] = []
    for key, raw, confidence in conn.execute("SELECT key, value, confidence FROM preferences ORDER BY key"):
        value = json.loads(raw)
        if isinstance(value, dict) and "override" in value:
            overrides.append(Preference(key, _shown(value["override"]), "override"))
        elif isinstance(value, dict) and "inferred" in value:
            inferred.append(Preference(key, _shown(value["inferred"]), "inferred", float(confidence)))
    inferred.sort(key=lambda p: (-(p.confidence or 0.0), p.key))
    return overrides + inferred


def due_reviews(conn: sqlite3.Connection, date: str) -> list[DueReview]:
    """Reviews due on or before `date` (YYYY-MM-DD, through the end of that UTC day), for the study planner."""
    day = datetime.fromisoformat(date).replace(tzinfo=UTC) + timedelta(days=1)
    end = int(day.timestamp() * 1000)
    rows = conn.execute("SELECT kc_id, due_at FROM review_cards WHERE due_at < ? ORDER BY due_at, kc_id", (end,))
    return [DueReview(r[0], int(r[1])) for r in rows]


def session_history(conn: sqlite3.Connection, session_id: str) -> list[TranscriptLine]:
    """The current session's stored transcript: student text, tutor text and board LaTeX (MEM-18), in order. A board
    step belongs to the turn of the part that drew it, or else to the last turn started before it."""
    sid = session_id.removeprefix("ses_")
    turns = conn.execute(
        "SELECT turn_id, idx, speaker, student_text, started_at FROM turns WHERE session_id = ? ORDER BY idx", (sid,)
    ).fetchall()
    ref_of = {turn_id: idx + 1 for turn_id, idx, *_ in turns}
    out: list[tuple[int, int, TranscriptLine]] = []
    for turn_id, idx, speaker, student_text, _ in turns:
        if speaker == "student" and student_text:
            out.append((idx + 1, 0, TranscriptLine(idx + 1, "student", student_text)))
        elif speaker == "tutor":
            parts = conn.execute(
                "SELECT idx, content FROM parts WHERE turn_id = ? AND kind = 'text' AND status <> 'retracted'"
                " ORDER BY idx",
                (turn_id,),
            )
            for part_idx, content in parts:
                text = json.loads(content).get("text")
                if isinstance(text, str) and text:
                    out.append((idx + 1, 1 + part_idx, TranscriptLine(idx + 1, "tutor", text)))
    starts = [(started, idx + 1) for _, idx, _, _, started in turns]
    steps = conn.execute(
        "SELECT s.latex, p.turn_id, s.created_at, s.idx FROM board_steps s LEFT JOIN parts p ON p.part_id = s.part_id"
        " WHERE s.session_id = ? ORDER BY s.created_at, s.idx, s.step_id",
        (sid,),
    )
    for latex, turn_id, created_at, step_idx in steps:
        ref = ref_of.get(turn_id) if turn_id is not None else None
        if ref is None:
            earlier = [r for started, r in starts if started <= created_at]
            ref = earlier[-1] if earlier else 1
        out.append((ref, 10_000 + step_idx, TranscriptLine(ref, "board", latex)))
    out.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, line in out]
