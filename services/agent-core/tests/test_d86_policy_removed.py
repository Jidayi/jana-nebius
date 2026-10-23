"""D86, D87: there is no answer-policy setting. The configuration has no such key, the session state no such field,
and a checkpoint an earlier build wrote with one still restores."""

from __future__ import annotations

import dataclasses

from agent_core.config import Settings
from agent_core.engine.state import SessionState, state_from_json, state_to_json


def test_no_policy_in_settings_or_state() -> None:
    assert "solution_policy" not in Settings.model_fields
    assert "solution_policy" not in {f.name for f in dataclasses.fields(SessionState)}


def test_older_checkpoint_with_a_policy_restores() -> None:
    state = SessionState("ses_01JZ00000000000000000000D8", subject="mathematics", mode="guided")
    older = {**state_to_json(state), "solution_policy": "never", "a_field_from_a_later_build": 1}
    restored = state_from_json(older)
    assert restored.mode == "guided" and restored.subject == "mathematics"
    assert state_to_json(restored) == state_to_json(state)
