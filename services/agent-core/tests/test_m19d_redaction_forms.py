"""M19.d security fixes: the egress redaction check reads normalised text, so hidden, fullwidth or lookalike characters
and other spellings of a name, contact detail or digital address cannot carry it out (MDL-25, PRV-25). The names,
numbers and addresses are invented for the tests."""

from __future__ import annotations

import pytest
from agent_core.net.redaction import Redactor

PROFILE = "prf_01M4YKC4J7ZAA6XXC5QV6NCZ84"
TERMS = ["Ama Owusu", PROFILE]


def _kinds(text: str) -> set[str]:
    return {f.kind for f in Redactor(TERMS).findings({"messages": [{"role": "user", "content": text}]})}


@pytest.mark.parametrize("text", [
    "A​ma Owusu", "Аma Owusu", "AMA  OWUSU", "ama_owusu", "Ama-Owusu", "Ａｍａ Owusu",
    "prf_01m4ykc4j7zaa6xxc5qv6ncz84", "Ｐrf_01M4YKC4J7ZAA6XXC5QV6NCZ84", "prf​_01M4YKC4J7ZAA6XXC5QV6NCZ84",
])  # fmt: skip
def test_mdl25_redaction_blocks_hidden_spellings(text: str) -> None:
    """The profile's name or id spelled with zero-width, lookalike, fullwidth or joining characters still blocks."""
    assert "term" in _kinds(text) or "profile_id" in _kinds(text)


@pytest.mark.parametrize(("text", "kind"), [
    ("My name is Kwabena Darko", "name"),
    ("MY NAME IS KWABENA DARKO", "name"),
    ("my name is kwabena", "name"),
    ("my name is Ɔbɛng Asante", "name"),
    ("write to kd.sample＠example.org", "email"),
    ("write to kd.sample​@example.org", "email"),
    ("call (024) 555-0199", "phone"),
    ("call 024 555 0199", "phone"),
    ("call ０２４５５５０１９９", "phone"),
    ("call +233 24 555 0199", "phone"),
    ("my address is GA-183-8164", "digital_address"),
    ("digital address AK 039 5121", "digital_address"),
])  # fmt: skip
def test_mdl25_redaction_blocks_contact_forms(text: str, kind: str) -> None:
    """Self-introductions in any case or script, fullwidth or hidden `@`, bracketed and grouped national numbers and
    GhanaPostGPS digital addresses are found (PRV-25)."""
    assert kind in _kinds(text)


@pytest.mark.parametrize("text", [
    "A car travels 120 km in 2 hours. What is its average speed?",
    "Solve 3x + 5 = 20 for x, then find 2x - 1.",
    "Between 1990 and 2024 the population grew by 35%.",
    "The ratio is 0.25 and the mass is 4.5 kg.",
])  # fmt: skip
def test_mdl25_redaction_passes_ordinary_questions(text: str) -> None:
    """Ordinary maths and science questions are not mistaken for personal data."""
    assert _kinds(text) == set()
