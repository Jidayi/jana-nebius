"""VSL-03, VSL-31, VSL-35: the renderer fixtures are what the engine resolves today. Each fixture is a resolved spec
made by running the validator with the verification tools, so a resolver or tool change that alters what is drawn
shows up here until the fixtures are rewritten (`python -m jana_tools visual-fixtures --write`)."""

from __future__ import annotations

from jana_tools.visual_fixtures import stale


def test_visual_fixtures_fresh() -> None:
    assert stale() == []
