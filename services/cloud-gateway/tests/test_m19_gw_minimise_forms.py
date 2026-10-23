"""The gateway's minimisation reads normalised text (MDL-25, PRV-25): a profile id hidden with zero-width or fullwidth
characters or written as an escape is refused, and a tool message's name is forwarded only when it is a tool
identifier. The ids and names are invented for the tests."""

from __future__ import annotations

import pytest
from cloud_gateway import minimise

PROFILE = "prf_01M4YKC4J7ZAA6XXC5QV6NCZ84"


@pytest.mark.parametrize("text", [
    PROFILE,
    PROFILE.replace("_", "​_"),
    "ｐrf_01M4YKC4J7ZAA6XXC5QV6NCZ84",
    "prf\\u005f01M4YKC4J7ZAA6XXC5QV6NCZ84",
    "PRF_01M4YKC4J7ZAA6XXC5QV6NCZ84",
])  # fmt: skip
def test_mdl25_gateway_refuses_hidden_profile_ids(text: str) -> None:
    body = {"messages": [{"role": "user", "content": f"my id is {text}"}]}
    assert minimise.refusal({}, body) == "the request carries a profile id"


def test_mdl25_gateway_forwards_only_tool_identifiers() -> None:
    body = {"messages": [{"role": "tool", "content": "x", "tool_call_id": "c1", "name": "Kwabena Darko"},
                         {"role": "tool", "content": "y", "tool_call_id": "c2", "name": "check_units"}]}  # fmt: skip
    forwarded = minimise.forwarded(body)["messages"]
    assert "name" not in forwarded[0] and forwarded[1]["name"] == "check_units"
