"""Numeric evaluation preserves exact input and rounds without guessing a closed form."""

import pytest
from tool_worker.functions.maths import math_evaluate
from tool_worker.registry import CallContext


@pytest.mark.parametrize(
    "expression,angle_unit,exact,rounded",
    [
        ("cos(1/7)", "radians", "cos(1/7)", "0.989813"),
        ("asin(0.3)", "degrees", "180*asin(3/10)/pi", "17.457603"),
        ("sqrt(2)+1/3", "radians", "1/3 + sqrt(2)", "1.747547"),
        ("1/10+2/10", "radians", "3/10", "0.300000"),
        ("6.9855", "radians", "13971/2000", "6.985500"),
    ],
)
def test_evaluation_keeps_exact_values_and_requested_rounding(expression, angle_unit, exact, rounded):
    context = CallContext("exact-evaluation", "test", {}, {}, lambda: False)
    value, extras = math_evaluate({"expression": expression, "angle_unit": angle_unit, "dp": 6}, context)
    assert value["status"] == "ok"
    assert value["exact"]["text"] == exact
    assert value["rounded"] == rounded
    assert extras["confidence"] == "proved"


def test_weight_at_a_rounding_boundary_uses_half_up():
    context = CallContext("exact-weight", "test", {}, {}, lambda: False)
    value, _ = math_evaluate({"expression": "95*8.9", "sf": 3}, context)
    assert value["exact"]["text"] == "1691/2"
    assert value["rounded"] == "846"
