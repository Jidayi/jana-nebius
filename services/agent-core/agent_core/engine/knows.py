"""The "What your tutor knows" page's reads and corrections (LRN-36, MEM-09, MEM-14, LRN-37, UXS-28, PRV-10; G90).

`KnowsDesk` serves one profile's learner database: the view in its wire shape (`KnowsView` of the G90 contract
additions: codes, bands and labels, never a probability) and the four corrections, each written as events through the
memory layer's writer. The API checks the open profile's token and adds its id and sharing flags (D87).

A review answer is pinned to the versions the page showed (MEM-09): when the item still exists but its pending note
or the note it would replace has moved on, nothing is written and the caller gets the item as it is now, to show
again. Every deletion here erases the note's text and compacts storage afterwards (LRN-37), outside any transaction.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from agent_core.config import Settings
from agent_core.engine.memory_session import MemorySource
from agent_core.learner.projections import PREFERENCE_VALUES, local_date
from agent_core.memory.capture import default_filter
from agent_core.memory.policy import render_check
from agent_core.memory.queries import NoteRecord, ReviewItem, review_items
from agent_core.memory.view import about, knows_view
from agent_core.memory.write import compact_storage, correct_misconception, correct_preference, forget, resolve_review

Owner = Literal["student"]
NOTE_PREFIX, REVIEW_PREFIX = "mem_", "rvw_"
_ULID_CHARS = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
BOOLEAN_PREFERENCES = frozenset(k for k, vs in PREFERENCE_VALUES.items() if all(isinstance(v, bool) for v in vs))


def bare(wire_id: str, prefix: str) -> str | None:
    """The stored id behind a wire id of this prefix, or None when it is not one (a foreign or malformed id)."""
    if not wire_id.startswith(prefix):
        return None
    inner = wire_id[len(prefix) :]
    return inner if len(inner) == 26 and set(inner) <= _ULID_CHARS else None


@dataclass(frozen=True)
class ReviewChanged:
    """A refused review answer: the item has moved on since it was shown; `current` is it as it is now (wire)."""

    current: dict[str, Any]


# Fixed table names only. Every DAT-05 projection is listed, including rows whose detailed fields stay numeric.
RECORD_CATEGORIES = {
    "kc_mastery": "mastery",
    "review_cards": "reviews",
    "learner_misconceptions": "mistakes",
    "attempts": "practice",
    "engagement_daily": "learning_days",
    "engagement_state": "activity",
    "subject_ability": "subject_progress",
    "preferences": "preferences",
    "notes": "notes",
    "study_plans": "plans",
}
PLAN_REASONS = {"revisit_moved_on", "prerequisite", "weak_high_value", "mock", "mock_follow_up"}


@dataclass
class KnowsDesk:
    source: MemorySource
    settings: Settings

    @property
    def _capture(self) -> Any:
        return self.source.capture or default_filter(self.settings)

    # --- the view -------------------------------------------------------------------------------------------------

    def _note(self, note: NoteRecord, flagged: bool | None = None) -> dict[str, Any]:
        if flagged is None:
            flagged = bool(render_check(note.text, self.settings, self._capture))
        source = {"student_request": "student", "corrected": "corrected"}.get(note.origin, "reflector")
        return {"note_id": NOTE_PREFIX + note.note_id, "text": note.text, "status": note.status, "source": source,
                "flagged": flagged, "subject": note.subject, "created_ts": note.created_at,
                "updated_ts": note.updated_at or note.created_at}  # fmt: skip

    def _review(self, item: ReviewItem) -> dict[str, Any]:
        return {"review_id": REVIEW_PREFIX + item.review_id, "kind": item.kind,
                "pending": self._note(item.pending) if item.pending is not None else None,
                "target": self._note(item.target) if item.target is not None else None,
                "pending_version": item.pending_event_id, "target_version": item.target_event_id}  # fmt: skip

    def view(self) -> dict[str, Any]:
        """Everything the page shows except who views it and what is shared (the API's), in the wire shape."""
        conn = self.source.conn
        seen = knows_view(conn, self.source.content, self.settings, capture=self._capture)
        profile = about(conn)
        records = []
        for table, kind in RECORD_CATEGORIES.items():
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - fixed table names
            if count:
                records.append({"kind": kind, "count": count})
        today = local_date(self.source.learner.projector.ctx.params.local_day(int(time.time() * 1000)))
        plan = conn.execute(
            "SELECT p.items,p.status FROM study_plans p JOIN events e ON e.type='plan_generated'"
            " AND json_extract(e.payload,'$.plan_id')=p.plan_id WHERE p.day=? AND p.status!='changed'"
            " ORDER BY e.hlc DESC,e.device_id DESC,e.origin_seq DESC LIMIT 1",
            (today,),
        ).fetchone()
        reason = None
        if plan is not None and plan[1] in ("proposed", "started"):
            for block in json.loads(plan[0]).get("blocks", []):
                if block.get("kind") in ("main", "mock"):
                    code = "mock" if block["kind"] == "mock" else block.get("reason_code")
                    reason = code if code in PLAN_REASONS else None
                    break
        return {
            "records": records,
            "plan_reason": reason,
            "about": None if profile is None or profile.level not in ("O", "A") else
            {"level": profile.level, "subjects": list(profile.subjects), "exam_date": profile.exam_date},
            "kcs": [{"kc_id": b.kc.kc_id, "statement": b.kc.statement, "state": b.kc.state, "band": b.band}
                    for b in seen.bands],
            "misconceptions": [{"misconception_id": m.misconception_id, "name": m.name, "status": m.status}
                               for m in seen.misconceptions],
            "preferences": [{"key": p.key, "value": p.value == "true" if p.key in BOOLEAN_PREFERENCES else p.value,
                             "source": p.origin} for p in seen.preferences if p.key in PREFERENCE_VALUES],
            "notes": [self._note(n.note, n.flagged) for n in seen.notes],
            "reviews": [self._review(r) for r in seen.reviews],
            "memory_saving": seen.memory_saving,
        }  # fmt: skip

    # --- corrections ------------------------------------------------------------------------------------------------

    def resolve(
        self, review_id: str, *, accept: bool, pending_version: str, target_version: str | None, actor: Owner
    ) -> list[str] | ReviewChanged | None:
        """Answer one review item for the versions shown. Returns the ids of the notes it deleted, `ReviewChanged`
        when the item moved on (nothing written), or None when there is no such item."""
        inner = bare(review_id, REVIEW_PREFIX)
        item = next((i for i in review_items(self.source.conn) if i.review_id == inner), None)
        if item is None:
            return None
        if (item.pending_event_id, item.target_event_id) != (pending_version, target_version):
            return ReviewChanged(self._review(item))
        target = item.target.note_id if item.target is not None else None
        if item.kind == "replace" and not accept:
            gone = [item.review_id]  # the pending note goes
        else:
            gone = [target] if accept and target else []  # the note it replaces, or the one a drop removes
        done = resolve_review(self.source.learner, item.review_id, seen_pending_event_id=pending_version,
                              seen_target_event_id=target_version, accept=accept, actor=actor)  # fmt: skip
        return gone if done else None

    def dispute_note(self, note_id: str, actor: Owner) -> str | None:
        """The note's "This isn't right": the dispute and the deletion in one batch, then compaction. Returns
        the deleted note's id, or None when there is no such active note."""
        inner = bare(note_id, NOTE_PREFIX)
        if inner is None or forget(self.source.learner, inner, actor, disputed=True) is None:
            return None
        compact_storage(self.source.conn)
        return inner

    def correct_misconception(self, misconception_id: str, action: Literal["dispute", "undispute"],
                              actor: Owner) -> bool:  # fmt: skip
        return correct_misconception(self.source.learner, misconception_id, action, actor)

    def correct_preference(self, key: str, value: Any, actor: Owner) -> bool:
        return correct_preference(self.source.learner, key, value, actor)
