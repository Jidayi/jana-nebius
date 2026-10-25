"""VER-32: a weak acid's pH from Ka through the real fn.call boundary: the square-root approximation only while under 5%
of the acid ionises, else the quadratic, and the working says which and why."""

from __future__ import annotations

from math import log10, sqrt
from typing import Any

import pytest
from test_ver38_biology import call

ACID = {"task": "ph", "acid": "CH3COOH", "acid_strength": "weak"}


def reply(**args: Any) -> dict[str, Any]:
    frame = call("chem_acid_base", {**ACID, **args})
    assert "result" in frame, frame
    result: dict[str, Any] = frame["result"]
    return result


def method(result: dict[str, Any]) -> str:
    return str(next(w["value"] for w in result["working"] if w["label"] == "method"))


def ver32_weak_acid_method() -> None:
    # Ka = 1.0e-3 at 0.10 mol/dm3: the approximation would put 10% of the acid in ions, so the quadratic is used.
    ten = reply(acid_concentration="0.10 M", ka=1.0e-3)
    quadratic = (-1.0e-3 + sqrt(1.0e-6 + 4 * 1.0e-3 * 0.10)) / 2
    assert float(ten["value"]["h"]["decimal"]) == pytest.approx(quadratic, rel=1e-6)
    assert method(ten) == "quadratic: the approximation would ionise 10.0% of the acid, not under 5%"
    assert ten["value"]["ph"]["rounded"] == f"{-log10(quadratic):.2f}"
    # Ka = 1.8e-5 at 0.10 mol/dm3: 1.3% ionised, so the square-root approximation is used.
    one = reply(acid_concentration="0.10 M", ka=1.8e-5)
    assert float(one["value"]["h"]["decimal"]) == pytest.approx(sqrt(1.8e-5 * 0.10), rel=1e-6)
    assert method(one) == "square-root approximation: 1.3% ionised, under 5%"
    # Without Ka a weak acid stays unknown, as before.
    assert call("chem_acid_base", {**ACID, "acid_concentration": "0.10 M"})["result"]["value"] == {
        "status": "unknown", "reason": "weak_acid_or_base"}  # fmt: skip
