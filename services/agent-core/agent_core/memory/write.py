"""The episodic layer's only writer (MEM-01): note writes, deletions and note corrections all go through here.

`forget` deletes a note for real (LRN-37, MEM-14): in one transaction it appends `note_deleted` with the actor and
replaces the payload of every `note_written` event for that note with the erasure tombstone, the same erasure the
retention job and profile deletion use (DAT-09). The notes projection folds the deletion into a row that keeps only
the id, status and time, and its full-text index follows by trigger. Afterwards `compact_storage` rewrites the
full-text index and truncates the write-ahead log, so no copy of the text is left in the database file, the log or
the index. An export made after that cannot carry the text either: the archive skips erased payloads and deleted
notes. Every deletion below (a Reflector drop, a bound expiry, a review) erases the same way.

`apply_reflection` applies one validated Reflection in one transaction (MEM-09, MEM-10, MEM-12, AGT-26):

- `add` stores a new note; `keep` changes nothing.
- `update` and `drop` change a note directly only when the Reflector wrote it and the action cites evidence the
  note does not already have (D71). For a note the student asked for or corrected, the change becomes a review item
  instead and the note stays as it is.
- `contradiction` never overwrites: the new text is stored `pending_review`, linked to the note it disputes by a
  `correction` (action `dispute`, value `{"pending_note_id": ...}`; G88), and stays out of every prompt.
- Every text is run through the do-not-capture filter first (a match is counted in `blocked`, never stored) and then
  the write policy (`policy.validate_candidate`; a failure is reported in `rejected`).
- Bounds are checked before anything is added (`plan_bounds`): the engine may run one consolidation call first
  (`needs_consolidation`, then `consolidation=`), and whatever still does not fit is made room for by expiring the
  oldest notes the Reflector wrote (`system_expiry`), never by an error to the student.

Review items (MEM-09, D71) are bounded: one open item per note, at most `notes_max_reviews_per_subject` open per
subject (a further one is dropped as `review_full` and counted, never stored), and a pending note never makes room for
itself by expiring another note. A pending note's text counts for the one-home rule like an active note's.

`resolve_review` answers a review item, pinned to the exact versions shown (MEM-09).

Every path that removes a note's text (a Reflector drop, a bound expiry, the old wording of an update, a review
answer) erases its `note_written` payloads in the same transaction, replaces a session summary that repeats it with
the code-built one, and then compacts storage itself, outside the transaction. `forget` leaves the compaction to its
caller, which runs it once the open sessions have dropped the note.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from agent_core.config import Settings
from agent_core.learner.projections import PREFERENCE_VALUES
from agent_core.learner.service import NOTES_WRITER, Learner, NewEvent
from agent_core.memory import policy
from agent_core.memory.capture import CaptureFilter, default_filter
from agent_core.memory.policy import Candidate, Rejection, content_hash
from agent_core.memory.queries import NoteRecord, ReviewItem, memory_saving, review_items, stored_notes
from agent_core.store.events import COLUMNS, MERGE_ORDER, StoredEvent
from agent_core.store.ids import new_ulid
from agent_core.store.supersession import read_log

Actor = Literal["student", "system_expiry"]
# The envelope source of a deletion by each actor (the learning-event contract's `source`).
SOURCE_OF: dict[str, str] = {"student": "student", "system_expiry": "engine"}
NOTES_INDEX = "notes_fts"
SUBJECTS = frozenset({"mathematics", "physics", "chemistry", "biology", "accounting"})
_KC_ID = re.compile(r"^kc\.(mth|phy|chm|bio|acc)\.(o|a)\.[a-z0-9_]+\.[a-z0-9_]+$")


@dataclass(frozen=True)
class Forgotten:
    """What a forget did: the deletion event and the write events whose payloads were erased."""

    note_id: str
    deleted_event_id: str
    erased_event_ids: tuple[str, ...]


def _erase_written(
    learner: Learner,
    conn: sqlite3.Connection,
    note_ids: Iterable[str],
    when: int,
    *,
    keep: Collection[str] = (),
) -> list[str]:
    """Erase the payload of every `note_written` event of the notes except the events in `keep` (inside the caller's
    transaction)."""
    erased: list[str] = []
    for note_id in note_ids:
        written = conn.execute(
            "SELECT event_id FROM events WHERE type = 'note_written' AND erased_at IS NULL"
            " AND json_extract(payload, '$.note_id') = ? ORDER BY seq",
            (note_id,),
        ).fetchall()
        for (event_id,) in written:
            if event_id in keep:
                continue
            learner.log.erase(event_id, when)
            erased.append(event_id)
    return erased


SUMMARY_ECHO_WORDS = 4  # a run of this many of a removed note's words in a session summary counts as repeating it


def code_summary(conn: sqlite3.Connection, session_id: str, subject: str | None) -> str:
    """The session summary built by code from the session's learning events (MEM-22): counts only, no student text."""
    sid = session_id.removeprefix("ses_")
    counts = dict(conn.execute(
        "SELECT type, count(*) FROM events WHERE session_id = ? AND erased_at IS NULL AND type IN"
        " ('attempt', 'hint') GROUP BY type", (sid,)).fetchall())  # fmt: skip
    verdicts = conn.execute(
        f"SELECT {COLUMNS} FROM events WHERE session_id = ? AND type = 'verdict' AND erased_at IS NULL"  # noqa: S608
        f" ORDER BY {MERGE_ORDER}",
        (sid,),
    )  # a re-marked answer counts as its latest marking, once (ASM-23, CUR-36)
    correct = sum(e.payload.get("outcome") == "correct" for e in read_log(map(StoredEvent.from_row, verdicts)))
    topic = f"{subject.capitalize()} session" if subject else "Session"
    attempts, hints = int(counts.get("attempt", 0)), int(counts.get("hint", 0))
    if not attempts and not hints:
        return f"{topic}: talked through the work; no answers were checked."
    return (f"{topic}: {attempts} answer{'s' if attempts != 1 else ''} checked, {correct} correct, "
            f"{hints} hint{'s' if hints != 1 else ''} used.")  # fmt: skip


def _repeats(summary: str, text: str) -> bool:
    """Whether a summary repeats a note: the whole note, or a run of `SUMMARY_ECHO_WORDS` of its words."""
    said, note = policy.normalise(summary), policy.normalise(text)
    if note and note in said:
        return True
    return policy.copied_run(summary, [text], SUMMARY_ECHO_WORDS)


def _scrub_summaries(conn: sqlite3.Connection, texts: Iterable[str]) -> int:
    """Session summaries that repeat a removed note's text are replaced by the code-built summary, in the caller's
    transaction (LRN-37, MEM-22). Returns how many were replaced."""
    removed = [t for t in texts if t]
    if not removed:
        return 0
    replaced = 0
    rows = conn.execute("SELECT session_id, subject, summary FROM sessions WHERE summary IS NOT NULL").fetchall()
    for session_id, subject, summary in rows:
        if any(_repeats(str(summary), text) for text in removed):
            conn.execute("UPDATE sessions SET summary = ? WHERE session_id = ?",
                         (code_summary(conn, session_id, subject), session_id))  # fmt: skip
            replaced += 1
    return replaced


def _replay_notes(learner: Learner) -> None:
    """Refold the notes projection (inside the caller's transaction), so a note whose older wording was erased reads
    the same as a rebuild would give."""
    notes = [p for p in learner.projector.projections if p.name == "notes"]
    if notes:
        learner.projector.replay_all(notes)


def forget(
    learner: Learner, note_id: str, actor: Actor, *, now_ms: int | None = None, disputed: bool = False
) -> Forgotten | None:
    """Delete a note and erase its text from the event log, in one transaction (LRN-37, MEM-14, MEM-11 Undo); a
    session summary that repeats it is replaced by the code-built one.

    `disputed` is "This isn't right" on a note (UXS-28): the same batch first records the student's or the adult's
    `correction` of it (action `dispute`). Only an active note can be disputed; a pending one is answered through its
    review item.

    Returns None when there is no such note or it is already deleted; nothing is written then. Call
    `compact_storage` afterwards, outside any transaction."""
    conn = learner.conn
    row = conn.execute(
        "SELECT text, status FROM notes WHERE note_id = ? AND status <> 'deleted'", (note_id,)
    ).fetchone()
    if row is None or (disputed and (row[1] != "active" or actor == "system_expiry")):
        return None
    erased: list[str] = []

    def erase_written(c: sqlite3.Connection, stored: list[StoredEvent]) -> None:
        when = now_ms if now_ms is not None else stored[0].recorded_at
        erased.extend(_erase_written(learner, c, [note_id], when))
        _scrub_summaries(c, [str(row[0])])

    deleted = NewEvent("note_deleted", {"note_id": note_id, "actor_role": actor}, source=SOURCE_OF[actor],
                       occurred_at=now_ms)  # fmt: skip
    dispute = NewEvent("correction", {"target": "note", "target_id": note_id, "action": "dispute",
                                      "actor_role": actor}, source=SOURCE_OF[actor], occurred_at=now_ms)  # fmt: skip
    stored = learner.record_batch([dispute, deleted] if disputed else [deleted], extra=erase_written,
                                  writer=NOTES_WRITER)  # fmt: skip
    return Forgotten(note_id, stored[-1].event_id, tuple(erased))


# --- the student's corrections of the learner model (LRN-37, PRV-10) ----------------------------------------------


def correct_misconception(
    learner: Learner, misconception_id: str, action: Literal["dispute", "undispute"], actor: Literal["student"]
) -> bool:
    """A misconception's "This isn't right", or its withdrawal, as a `correction` event (LRN-37): the projection
    sets it disputed until `misconception_dispute_reactivate` new matches. Only a misconception the page shows can be
    disputed (active or resolving), and only a disputed one undisputed; anything else writes nothing (False)."""
    row = learner.conn.execute(
        "SELECT status FROM learner_misconceptions WHERE misconception_id = ?", (misconception_id,)
    ).fetchone()
    allowed = ("active", "resolving") if action == "dispute" else ("disputed",)
    if row is None or row[0] not in allowed:
        return False
    learner.record("correction", {"target": "misconception", "target_id": misconception_id, "action": action,
                                  "actor_role": actor}, source=SOURCE_OF[actor])  # fmt: skip
    return True


def correct_preference(learner: Learner, key: str, value: Any, actor: Literal["student"]) -> bool:
    """Edit how the student likes to learn (LRN-37): a `correction` that overrides the inferred value, or with
    `value` None clears the override. A key or value the preference cannot take writes nothing (False)."""
    allowed = PREFERENCE_VALUES.get(key)
    if allowed is None:
        return False
    payload: dict[str, Any] = {"target": "preference", "target_id": key, "actor_role": actor}
    if value is None:
        payload["action"] = "clear_override"
    elif any(value == v and type(value) is type(v) for v in allowed):
        payload.update(action="override", value=value)
    else:
        return False
    learner.record("correction", payload, source=SOURCE_OF[actor])
    return True


@dataclass(frozen=True)
class Compacted:
    """The outcome of a compaction: whether the index was rewritten and whether the log checkpoint completed (a
    checkpoint is `busy` while another connection holds a read transaction; the next compaction finishes it)."""

    index_optimised: bool
    wal_busy: bool
    wal_frames: int
    frames_checkpointed: int


def compact_storage(conn: sqlite3.Connection) -> Compacted:
    """Rewrite the notes index into one segment and truncate the write-ahead log (LRN-37).

    With `secure_delete` on (DAT-03) every page freed by the rewrite is zeroed, and the checkpoint copies the current
    pages into the database file before the log is cut to zero bytes. Runs outside a transaction."""
    if conn.in_transaction:
        raise RuntimeError("storage is compacted outside a transaction")
    present = conn.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?", (NOTES_INDEX,)).fetchone()
    if present is not None:
        conn.execute(f"INSERT INTO {NOTES_INDEX}({NOTES_INDEX}) VALUES ('optimize')")  # noqa: S608 - fixed name
    busy, frames, done = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return Compacted(present is not None, bool(busy), int(frames), int(done))


# --- the Reflector's writes ------------------------------------------------------------------------------------


NoteActionKind = Literal["add", "update", "keep", "drop", "contradiction"]
NoteOrigin = Literal["reflector", "student_request", "corrected"]
WriterRole = Literal["reflector", "student_request"]


@dataclass(frozen=True)
class NoteAction:
    """One Reflection note with its integer refs already mapped back to ids (MEM-08)."""

    action: NoteActionKind
    text: str
    date: str  # YYYY-MM-DD, the session date (G95)
    evidence_event_ids: tuple[str, ...]
    target_note_id: str | None = None
    kc_id: str | None = None
    subject: str | None = None


@dataclass(frozen=True)
class Applied:
    """What `memory_note` returns to the engine: notes written, candidates blocked by the do-not-capture filter
    (counted, never stored, MEM-10) and candidates rejected by the write policy (MEM-07), one rejection per candidate
    (its first rule; the detail names the others). `pending_review` holds the review items created (pending note
    ids, or the proposal event id of a drop); `dropped` the notes the Reflector removed; `expired` the notes removed
    to keep within the bounds; `over_bound` the additions that still did not fit. `refused` is set, and nothing is
    written, when memory saving is off."""

    applied: tuple[str, ...] = ()
    blocked: int = 0
    rejected: tuple[Rejection, ...] = ()
    pending_review: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    expired: tuple[str, ...] = ()
    over_bound: int = 0
    summary_stored: bool = False
    refused: str | None = None


@dataclass(frozen=True)
class Bounds:
    """The episodic store's counts against its bounds (MEM-12, G99: active plus pending)."""

    subject: str | None
    notes: int
    chars: int
    total_active: int
    over: bool
    over_by: dict[str, int] = field(default_factory=dict)


def check_bounds(conn: sqlite3.Connection, subject: str | None, settings: Settings) -> Bounds:
    """Counts of active and pending notes for a subject and in total, against `notes_max_per_subject`,
    `notes_max_chars_per_subject` and `notes_max_active` (MEM-12). Notes with no subject are their own group."""
    notes, chars = conn.execute(
        "SELECT count(*), coalesce(sum(length(text)), 0) FROM notes"
        " WHERE status IN ('active', 'pending_review') AND subject IS ?",
        (subject,),
    ).fetchone()
    (total,) = conn.execute("SELECT count(*) FROM notes WHERE status IN ('active', 'pending_review')").fetchone()
    over_by = {
        name: excess
        for name, excess in (
            ("notes", notes - settings.notes_max_per_subject),
            ("chars", chars - settings.notes_max_chars_per_subject),
            ("total", total - settings.notes_max_active),
        )
        if excess > 0
    }
    return Bounds(subject, int(notes), int(chars), int(total), bool(over_by), over_by)


@dataclass(frozen=True)
class BoundsPlan:
    """Which notes to expire, oldest first, and which additions fit afterwards (in the order given)."""

    expire: tuple[str, ...]
    admit: tuple[bool, ...]


def plan_bounds(
    notes: Sequence[NoteRecord],
    additions: Sequence[tuple[str | None, int]],
    settings: Settings,
    *,
    keep: Collection[str] = (),
    reviews: Sequence[bool] = (),
) -> BoundsPlan:
    """Make room for `additions` ((subject, characters) per note to add) within the bounds: a pure function of the
    stored notes (active and pending) and the additions.

    For each addition in turn, while it does not fit, the oldest active note the Reflector wrote is expired: from
    the same subject when the subject's bound is the one exceeded, else from any subject. Notes the student owns (a
    request of theirs, or a note they corrected) are never expired (D71), nor pending review items, nor the notes in
    `keep` (those the same Reflection changes or disputes). An addition that still does not fit is not admitted.

    An addition marked in `reviews` is a review item (a pending note): it never expires another note to make room
    (MEM-09). It is admitted as it is, counted from then on, and bounded by the review cap instead."""
    count: dict[str | None, int] = {}
    chars: dict[str | None, int] = {}
    for note in notes:
        count[note.subject] = count.get(note.subject, 0) + 1
        chars[note.subject] = chars.get(note.subject, 0) + len(note.text)
    total = len(notes)
    candidates = (n for n in notes if n.status == "active" and n.note_id not in keep)
    expirable = sorted((n for n in candidates if n.origin == "reflector"), key=lambda n: (n.created_at, n.note_id))
    expire: list[str] = []
    admit: list[bool] = []

    def subject_full(subject: str | None, size: int) -> bool:
        return (
            count.get(subject, 0) + 1 > settings.notes_max_per_subject
            or chars.get(subject, 0) + size > settings.notes_max_chars_per_subject
        )

    def take(subject: str | None, same_subject: bool) -> bool:
        nonlocal total
        for note in expirable:
            if note.note_id not in expire and (not same_subject or note.subject == subject):
                expire.append(note.note_id)
                count[note.subject] -= 1
                chars[note.subject] -= len(note.text)
                total -= 1
                return True
        return False

    for index, (subject, size) in enumerate(additions):
        review = index < len(reviews) and reviews[index]
        if review:
            fits = True
        else:
            while subject_full(subject, size) or total + 1 > settings.notes_max_active:
                if not take(subject, subject_full(subject, size)):
                    break
            fits = not subject_full(subject, size) and total + 1 <= settings.notes_max_active
        admit.append(fits)
        if fits:
            count[subject] = count.get(subject, 0) + 1
            chars[subject] = chars.get(subject, 0) + size
            total += 1
    return BoundsPlan(tuple(expire), tuple(admit))


def needs_consolidation(
    conn: sqlite3.Connection, actions: Sequence[NoteAction], settings: Settings, *, subject: str | None
) -> bool:
    """Whether the Reflection's new active notes would exceed a bound (MEM-12): the engine then runs one
    consolidation call over the subject's notes in the same job and passes its output to
    `apply_reflection(consolidation=...)`. Review items need no room (they never expire a note). The check counts
    every candidate as if it passed, so it may ask for a consolidation that turns out not to be needed, never the
    reverse."""
    additions = [(a.subject or subject, len(a.text)) for a in actions if a.action == "add"]
    if not additions:
        return False
    plan = plan_bounds(stored_notes(conn), additions, settings)
    return bool(plan.expire) or not all(plan.admit)


@dataclass
class _Staged:
    """A Reflection being turned into events: nothing touches the database until the batch."""

    events: list[NewEvent] = field(default_factory=list)
    adds: list[tuple[int, NewEvent | None, str, str | None, int]] = field(default_factory=list)  # index, link, id, ...
    applied: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    drop_reviews: list[int] = field(default_factory=list)  # event indexes of drop proposals (their ids come later)
    dropped: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)  # notes rewritten in place: their older wording is erased
    rejected: list[Rejection] = field(default_factory=list)
    blocked: int = 0
    touched: set[str] = field(default_factory=set)


def _one(rejections: Sequence[Rejection]) -> Rejection:
    first = rejections[0]
    others = sorted({r.code for r in rejections[1:]} - {first.code})
    return Rejection(first.code, "; ".join(x for x in (first.detail, f"also {', '.join(others)}" if others else "")
                                           if x))  # fmt: skip


def _review_subject(item: ReviewItem) -> str | None:
    note = item.pending if item.pending is not None else item.target
    return note.subject if note is not None else None


def apply_reflection(
    learner: Learner,
    actions: Sequence[NoteAction],
    *,
    session_id: str,
    session_date: str,
    summary: str | None,
    settings: Settings,
    role: WriterRole = "reflector",
    capture: CaptureFilter | None = None,
    consolidation: Sequence[NoteAction] | None = None,
    student_texts: Collection[str] = (),
    forgotten_hashes: Collection[str] = (),
    now_ms: int | None = None,
    also: Callable[[sqlite3.Connection], object] | None = None,
) -> Applied:
    """Apply a validated Reflection in one transaction (MEM-09, MEM-12, AGT-26): add, update, keep, drop and
    contradiction, bounds and consolidation fallback, and the session summary. A Reflector change to a student-owned
    note becomes `pending_review` (add-only for student-owned notes).

    `capture` is the loaded do-not-capture filter (the engine passes the one the runtime loaded; without one, the
    source tree's is used, and if there is none nothing is written: the filter is never skipped). `consolidation` is
    the consolidation call's output, applied first under the same owner rules, except that merging the Reflector's
    own notes needs no new evidence. `student_texts` are the student's words in the window, for the copied-words
    rule. `forgotten_hashes` are the content hashes of notes deleted after the job's input was built: a candidate
    that would bring one back is rejected (`forgotten`). `also` runs inside the same transaction when anything is
    written (the engine records its job cursor there, AGT-26); it must not await. Never raises for a bad candidate:
    every outcome is in the result."""
    if role not in ("reflector", "student_request"):
        raise PermissionError(f"notes are written only by the Reflector, not {role!r} (MEM-01)")
    conn = learner.conn
    if not memory_saving(conn, settings):
        return Applied(refused="memory_saving_off")
    screen = capture or default_filter(settings)
    if screen is None:
        return Applied(refused="capture_filter_missing")
    sid = session_id.removeprefix("ses_")
    notes = {n.note_id: n for n in stored_notes(conn)}
    # One home per fact (MEM-07): active and pending notes alike.
    known = {content_hash(n.text): n.note_id for n in notes.values() if n.status in ("active", "pending_review")}
    forgotten = set(forgotten_hashes)
    open_items = review_items(conn)
    reviewed = {i.target.note_id for i in open_items if i.target is not None}  # one open item per note
    reviews_by_subject = Counter(_review_subject(i) for i in open_items)
    staged = _Staged()
    source = "student" if role == "student_request" else "reflector"
    profile_id = learner.log.profile_id

    def event(type_: str, payload: dict[str, Any], src: str = "reflector") -> NewEvent:
        return NewEvent(type_, payload, source=src, session_id=sid, occurred_at=now_ms)

    def written(
        note_id: str, action: NoteAction, evidence: Sequence[str], status: str, base: NoteRecord | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"note_id": note_id, "text": action.text, "status": status,
                                   "source_event_ids": list(dict.fromkeys(evidence))}  # fmt: skip
        subject = action.subject or (base.subject if base else None)
        if subject in SUBJECTS:
            payload["subject"] = subject
        kc_ids = [action.kc_id] if action.kc_id and _KC_ID.match(action.kc_id) else list(base.kc_ids if base else [])
        if kc_ids:
            payload["kc_ids"] = kc_ids[:5]
        return payload

    def dispute(target_id: str, value: dict[str, Any]) -> NewEvent:
        return event("correction", {"target": "note", "target_id": target_id, "action": "dispute", "value": value})

    def review_room(target: NoteRecord, action: NoteAction) -> Rejection | None:
        """A review item for `target`: refused while the note already has one open, or while the subject has
        `notes_max_reviews_per_subject` open (MEM-09). Reserves the place when there is room."""
        if target.note_id in reviewed:
            return Rejection("review_open", "the note already has an open review item")
        subject = action.subject or target.subject
        if reviews_by_subject[subject] >= settings.notes_max_reviews_per_subject:
            return Rejection("review_full", f"{settings.notes_max_reviews_per_subject} review items already open")
        reviewed.add(target.note_id)
        reviews_by_subject[subject] += 1
        return None

    def stage(action: NoteAction, consolidating: bool) -> None:
        kind = action.action
        if kind == "keep":
            return
        target: NoteRecord | None = None
        if kind in ("update", "drop", "contradiction"):
            target = notes.get(action.target_note_id or "")
            if target is None or target.status != "active" or target.note_id in staged.touched:
                staged.rejected.append(Rejection("unknown_target", f"{kind} of a note that is not active"))
                return
        if kind != "drop" and screen.check(action.text).blocked:
            staged.blocked += 1  # counted by number only: the text goes nowhere (MEM-10)
            return
        hashes = set(known) - ({content_hash(target.text)} if target is not None and kind == "update" else set())
        owned = target is not None and target.origin != "reflector"
        problems: list[Rejection]
        if kind == "drop" and consolidating and not owned and not action.evidence_event_ids:
            problems = []  # merging its own notes under the bound, the Reflector cites nothing new
        elif kind == "drop":
            problems = policy.evidence_rejections(conn, profile_id, action.evidence_event_ids)
        else:
            candidate = Candidate(action.text, action.date, action.evidence_event_ids, action.subject,
                                  (action.kc_id,) if action.kc_id else ())  # fmt: skip
            problems = policy.validate_candidate(candidate, conn=conn, profile_id=profile_id,
                                                 session_date=session_date, active_hashes=hashes,
                                                 student_texts=student_texts, settings=settings)  # fmt: skip
            if content_hash(action.text) in forgotten:
                problems.append(Rejection("forgotten", "the same text was forgotten while the job ran"))
        needs_new = kind in ("update", "drop") and (owned or not consolidating)
        if target is not None and needs_new and not set(action.evidence_event_ids) - set(target.source_event_ids):
            problems.append(Rejection("no_evidence", "no evidence the note does not already cite"))
        if not problems and target is not None and (kind == "contradiction" or owned):
            refused = review_room(target, action)  # a review item: one per note, a few per subject
            problems = [refused] if refused is not None else []
        if problems:
            staged.rejected.append(_one(problems))
            return
        if target is not None:
            staged.touched.add(target.note_id)
        if kind == "add":
            note_id = new_ulid()
            payload = written(note_id, action, action.evidence_event_ids, "active", None)
            staged.adds.append((len(staged.events), None, note_id, payload.get("subject"), len(action.text)))
            staged.events.append(event("note_written", payload, source))
            known[content_hash(action.text)] = note_id
        elif target is not None and (kind == "contradiction" or (kind == "update" and owned)):
            note_id = new_ulid()
            payload = written(note_id, action, action.evidence_event_ids, "pending_review", target)
            link = dispute(target.note_id, {"pending_note_id": note_id})
            staged.adds.append((len(staged.events), link, note_id, payload.get("subject"), len(action.text)))
            staged.events += [event("note_written", payload), link]
            known[content_hash(action.text)] = note_id
        elif target is not None and kind == "update":
            evidence = [*target.source_event_ids, *action.evidence_event_ids]
            staged.events.append(event("note_written", written(target.note_id, action, evidence, "active", target)))
            staged.applied.append(target.note_id)
            staged.updated.append(target.note_id)
            known.pop(content_hash(target.text), None)
            known[content_hash(action.text)] = target.note_id
        elif target is not None and kind == "drop" and owned:
            staged.drop_reviews.append(len(staged.events))
            staged.events.append(
                dispute(target.note_id, {"proposal": "drop", "evidence_event_ids": list(action.evidence_event_ids)})
            )
        elif target is not None and kind == "drop":
            staged.events.append(event("note_deleted", {"note_id": target.note_id, "actor_role": "system_expiry"}))
            staged.dropped.append(target.note_id)
            known.pop(content_hash(target.text), None)

    for action in consolidation or ():
        stage(action, consolidating=True)
    for action in actions:
        stage(action, consolidating=False)

    # Bounds before adds (MEM-12): what the store will hold once the drops land, then room for each addition. A
    # review item never makes room for itself, and a note under review is never expired (MEM-09).
    remaining = [n for n in notes.values() if n.note_id not in staged.dropped]
    plan = plan_bounds(remaining, [(subject, size) for _, _, _, subject, size in staged.adds], settings,
                       keep=staged.touched | reviewed,
                       reviews=[link is not None for _, link, *_ in staged.adds])  # fmt: skip
    refused = {index for (index, *_), fits in zip(staged.adds, plan.admit, strict=True) if not fits}
    links = {id(link) for (index, link, *_), fits in zip(staged.adds, plan.admit, strict=True) if link and not fits}
    for index, link, note_id, _, _ in staged.adds:
        if index in refused:
            continue
        (staged.pending if link is not None else staged.applied).append(note_id)
    expiries = [NewEvent("note_deleted", {"note_id": n, "actor_role": "system_expiry"}, source="engine",
                         session_id=sid, occurred_at=now_ms) for n in plan.expire]  # fmt: skip
    kept = [e for i, e in enumerate(staged.events) if i not in refused and id(e) not in links]
    batch = expiries + kept
    drop_events = [staged.events[i] for i in staged.drop_reviews]

    summary_text = _summary(summary, screen)
    gone = [*staged.dropped, *plan.expire]
    removed_texts = [notes[n].text for n in [*gone, *staged.updated] if n in notes]
    if not batch and summary_text is None:
        return Applied(blocked=staged.blocked, rejected=tuple(staged.rejected), over_bound=len(refused))

    def extra(c: sqlite3.Connection, stored: list[StoredEvent]) -> None:
        when = now_ms if now_ms is not None else (stored[0].recorded_at if stored else learner.log.clock.wall_ms())
        _erase_written(learner, c, gone, when)
        if staged.updated:  # the older wording of a rewritten note goes too (LRN-37); the new write stays
            _erase_written(learner, c, staged.updated, when, keep={s.event_id for s in stored})
            _replay_notes(learner)
        if summary_text is not None:
            c.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (summary_text, sid))
        _scrub_summaries(c, removed_texts)
        if also is not None:
            also(c)

    stored = learner.record_batch(batch, extra=extra, writer=NOTES_WRITER)
    if gone or staged.updated:
        compact_storage(conn)  # no copy of a removed text left in the file, the log or the index (LRN-37)
    by_event = {id(e): s.event_id for e, s in zip(batch, stored, strict=True)}
    drop_ids = [by_event[id(e)] for e in drop_events if id(e) in by_event]
    stored_summary = (
        summary_text is not None
        and conn.execute("SELECT 1 FROM sessions WHERE session_id = ? AND summary IS NOT NULL", (sid,)).fetchone()
        is not None
    )
    return Applied(
        applied=tuple(staged.applied),
        blocked=staged.blocked,
        rejected=tuple(staged.rejected),
        pending_review=(*staged.pending, *drop_ids),
        dropped=tuple(staged.dropped),
        expired=plan.expire,
        over_bound=len(refused),
        summary_stored=stored_summary,
    )


SUMMARY_MAX_CHARS = 400  # the Reflection contract's `summary_for_student`


def summary_text(text: str | None, capture: CaptureFilter) -> str | None:
    """The session summary as it would be stored, or None when it may not be (the engine then passes its code-built
    one instead)."""
    return _summary(text, capture)


def _summary(text: str | None, capture: CaptureFilter) -> str | None:
    """The session summary when it is safe to keep (MEM-22): no hidden characters, nothing secret-like or quoted,
    nothing the do-not-capture filter blocks. It speaks to the student, so the instruction-shape rule does not
    apply. A summary that fails is not stored; the engine keeps its code-built one."""
    if not text or not text.strip() or len(text) > SUMMARY_MAX_CHARS:
        return None
    if policy.hidden_characters(text) or policy.secret_like(text) or policy.quoted(text):
        return None
    if capture.check(text, instructions=False).blocked:
        return None
    return text.strip()


# --- review items (MEM-09) ----------------------------------------------------------------------------------------


def resolve_review(
    learner: Learner,
    pending_note_id: str,
    *,
    seen_pending_event_id: str,
    seen_target_event_id: str | None,
    accept: bool,
    actor: Literal["student"],
    now_ms: int | None = None,
) -> bool:
    """Accept or reject a review item, pinned to the versions shown (MEM-09): refused (False) when the item is gone,
    or when the pending note or the note it would replace has a newer event than the one seen.

    `pending_note_id` is the item's id (`ReviewItem.review_id`: the pending note's id, or a drop proposal's event
    id). Accepting a replacement makes the pending note active through a `correction` (`override`) and deletes the
    note it replaces; rejecting deletes the pending note. Accepting a drop deletes the note; rejecting it records
    `undispute`. Every deletion erases the note's text, and storage is compacted afterwards."""
    if actor not in ("student", "adult"):
        raise PermissionError("a review is answered by the student or the device adult")
    conn = learner.conn
    item = next((i for i in review_items(conn) if i.review_id == pending_note_id), None)
    if item is None or item.pending_event_id != seen_pending_event_id or item.target_event_id != seen_target_event_id:
        return False

    def event(type_: str, payload: dict[str, Any]) -> NewEvent:
        return NewEvent(type_, payload, source=actor, occurred_at=now_ms)

    def correction(target_id: str, action: str) -> NewEvent:
        return event("correction", {"target": "note", "target_id": target_id, "action": action, "actor_role": actor})

    def deletion(note_id: str) -> NewEvent:
        return event("note_deleted", {"note_id": note_id, "actor_role": actor})

    target = item.target.note_id if item.target is not None else None
    events: list[NewEvent]
    if item.kind == "replace" and accept:
        events = [correction(item.review_id, "override"), *([deletion(target)] if target else [])]
        gone = [target] if target else []
    elif item.kind == "replace":
        events, gone = [deletion(item.review_id)], [item.review_id]
    elif target is not None and accept:
        events, gone = [deletion(target)], [target]
    elif target is not None:
        events, gone = [correction(target, "undispute")], []
    else:
        return False

    texts = [n.text for n in (item.pending, item.target) if n is not None and n.note_id in gone]

    def extra(c: sqlite3.Connection, stored: list[StoredEvent]) -> None:
        _erase_written(learner, c, gone, now_ms if now_ms is not None else stored[0].recorded_at)
        _scrub_summaries(c, texts)

    learner.record_batch(events, extra=extra, writer=NOTES_WRITER)
    if gone:
        compact_storage(conn)  # the removed text leaves the file, the log and the index too (LRN-37)
    return True
