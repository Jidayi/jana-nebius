"""MEM-26, PRD-19, EVL-22: numerical learning evidence, never memory content."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from agent_core.config import Settings

EVENTS = frozenset({"attempt", "verdict", "hint", "mastery_check", "session_ended", "diagnostic_item"})
NUMBERS = frozenset(
    {
        "active_ms",
        "duration_ms",
        "attempts",
        "hint_rung",
        "score",
        "max_score",
        "correct",
        "passed",
        "bottom_out",
        "newly_mastered",
        "time_ms",
        "rung",
        "marks_awarded",
        "marks_available",
        "closes_opportunity",
    }
)


def statistic(participants: int, total: float, settings: Settings | None = None) -> dict[str, Any]:
    suppressed = participants < (settings or Settings()).research_min_participants
    return {
        "sample_size": participants,
        "value": None if suppressed else total / participants,
        "suppressed": suppressed,
        "review_required": suppressed,
    }


def project(raw: dict[str, Any]) -> dict[str, Any]:
    events = []
    for event in raw.get("events", []):
        if event.get("type") not in EVENTS:
            continue
        try:
            day = date.fromisoformat(str(event["occurred_at"])[:10]).isoformat()
        except (KeyError, ValueError):
            continue
        payload = event.get("payload", {})
        entry = {
            key: value
            for key, value in payload.items()
            if key in NUMBERS and type(value) in (int, float, bool) and math.isfinite(value)
        }
        for key, allowed in {
            "item_result": {"pass", "fail"},
            "check_state": {"in_progress", "passed", "failed"},
            "outcome": {"correct", "incorrect", "partial", "unverifiable"},
            "mode": {
                "guided",
                "solution",
                "check_working",
                "learn",
                "practice",
                "mock",
                "revision",
                "diagnostic",
                "mastery_check",
                "review",
            },
        }.items():
            if payload.get(key) in allowed:
                entry[key] = payload[key]
        kc = payload.get("kc_id")
        if isinstance(kc, str) and re.fullmatch(r"kc\.(mth|phy|chm|bio|acc)\.(o|a)\.[a-z0-9_]+\.[a-z0-9_]+", kc):
            entry["kc_id"] = kc
        events.append({"type": event["type"], "day": day, **entry})
    mastery = []
    for row in raw.get("kc_mastery", []):
        # KC identifiers stay out of this analysis projection; it cannot join to the device's learner record.
        kept = {
            key: value
            for key, value in row.items()
            if key in {"p_mastery", "attempt_count", "confirmed"}
            and type(value) in (int, float, bool)
            and math.isfinite(value)
        }
        if kept:
            mastery.append(kept)
    return {"events": events, "kc_mastery": mastery}
