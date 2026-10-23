"""Unit display through the shipped engine with synthetic model replies and the real local tool worker."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agent_core.engine.unit_format import decimal_unit_comma, format_turn_units, format_unit_spacing
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor


@pytest.mark.parametrize("kind", ["plain", "tex", "comma_retry"])
def loc10_unit_format(tmp_path: Path, kind: str) -> None:
    async def scenario() -> None:
        good = "The starting speed is 14m/s. Which equation could you use?"
        tex = r"The given acceleration is \(9.8\mathrm{m/s^2}\). Which quantity is unknown?"
        comma = r"The starting speed is \(14,0\,\mathrm{m/s}\). Which equation could you use?"
        coach = [tutor(comma), tutor(good)] if kind == "comma_retry" else [tutor(tex if kind == "tex" else good)]
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach})
        try:
            result = await engine.start_problem(STATEMENT)
            assert result.tutor_turn is not None, result.degraded_reason
            say = result.tutor_turn["say"]
            assert say == format_unit_spacing(say, "physics")
            assert not decimal_unit_comma(say)
            expected = r"9.8\,\mathrm{m/s^2}" if kind == "tex" else "14 m/s"
            assert expected in say
            assert "14,0" not in json.dumps(engine.state.transcript)
            if kind == "comma_retry":
                assert any(g["gate"] == "verified" and g["fired"] for g in result.trace["gates"])
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_unit_spacing_preserves_numerals_algebra_metadata_and_chemical_symbols() -> None:
    assert format_unit_spacing(r"\(1000V+3V\)", "physics") == r"\(1000V+3V\)"
    assert format_unit_spacing(r"{}^{14}_{7}\text{N}", "physics", latex=True) == r"{}^{14}_{7}\text{N}"
    chemical = r"2\text{K}+2\text{H}_2\text{O}"
    assert format_unit_spacing(chemical, "chemistry", latex=True) == chemical
    assert format_unit_spacing("1.50kg", "physics") == "1.50 kg"
    draft = {"say": "1.50kg", "id": "node_1.50kg", "value": "1.50", "unit": "kg"}
    assert format_turn_units(draft, "physics") == {**draft, "say": "1.50 kg"}
    assert draft["say"] == "1.50kg"
    for text in ["9,8 kg", r"9{,}8\,\mathrm{kg}", "9,8e-2 kg"]:
        assert decimal_unit_comma(text)
    assert not decimal_unit_comma("1,234 kg")
