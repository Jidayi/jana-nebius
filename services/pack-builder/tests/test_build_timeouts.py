"""Offline exact verification has a bounded budget and never treats a timeout as proof."""

from dataclasses import replace

import pytest
from agent_core.config import Settings
from pack_builder import verify


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("60/360*2*pi*9", "9.42"),
        ("80/tan(51)", "64.8"),
        ("40*tan(51)+1.7", "51.1"),
        ("30/tan(51)", "24.3"),
        ("sin(55)/sin(33)", "1.50"),
        ("1/sin(39)", "1.59"),
    ],
)
def test_build_verifies_original_curriculum_values_with_bounded_symbolic_work(expression, expected):
    result = verify.run_check(
        "chk_build_release_regression",
        {"tool": "math_evaluate", "args": {"expression": expression, "angle_unit": "degrees", "sf": 3}},
    )
    assert result.value["status"] == "ok"
    assert result.value["rounded"] == expected
    assert Settings().ver_symbolic_slice_ms == 800


def test_build_still_returns_unknown_when_every_bounded_attempt_times_out(monkeypatch):
    contexts = []

    def unknown(args, context):
        contexts.append(context)
        return {"status": "unknown", "reason": "timeout"}, {}

    monkeypatch.setitem(
        verify.FUNCTIONS, "math_evaluate", replace(verify.FUNCTIONS["math_evaluate"], implementation=unknown)
    )
    result = verify.run_check("chk_build_unknown", {"tool": "math_evaluate", "args": {"expression": "1+1"}})
    assert result.value == {"status": "unknown", "reason": "timeout"}
    assert len(contexts) == Settings().build_check_timeout_attempts
    assert all(c.setting("symbolic_slice_ms", 0) == Settings().build_check_symbolic_slice_ms for c in contexts)
    assert 100 <= Settings().build_check_symbolic_slice_ms <= 5000
