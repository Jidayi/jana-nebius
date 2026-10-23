"""Every tool schema renders through a local model's chat template as llama-server's Jinja engine runs it.

Gemma 4's template upper-cases an array's `items.type` with `map('upper')` when it is a list of types, a filter form
llama.cpp's Jinja engine does not implement (HTTP 500 "filter-mapping not implemented"). Nine worker schemas spell
mixed arrays that way (`interval`, `givens`, `coefficients`, ...), so `LlamaServerProvider` sends every schema through
`grammar_friendly`, which turns a list of types into the equivalent `anyOf`. These tests hold that line."""

from __future__ import annotations

import asyncio
import os
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from agent_core.providers.base import Message, ToolSchema
from agent_core.providers.openai_compat import grammar_friendly
from agent_core.tools.spec import InitCtx
from agent_core.tools.specs import specs

KEY_FILE = Path("/private/tmp/jana-local-model/api-key")
LIVE_URL = os.environ.get("JANA_LIVE_LLAMA_URL", "http://127.0.0.1:18081")
LIVE_MODEL = os.environ.get("JANA_LIVE_LLAMA_MODEL", "gemma-4-12b")


def _key() -> str:
    if "JANA_LIVE_LLAMA_KEY" in os.environ:
        return os.environ["JANA_LIVE_LLAMA_KEY"]
    try:
        return KEY_FILE.read_text().strip()
    except OSError:
        return "none"


def _live_up() -> bool:
    headers = {"Authorization": f"Bearer {_key()}"}
    request = urllib.request.Request(f"{LIVE_URL}/v1/models", headers=headers)  # noqa: S310 (loopback only)
    try:
        with urllib.request.urlopen(request, timeout=2) as answer:  # noqa: S310 (loopback only)
            return LIVE_MODEL in answer.read().decode()
    except (OSError, ValueError):
        return False


def _type_lists(schema: Any, path: str = "") -> list[str]:
    if isinstance(schema, dict):
        found = [path or "/"] if isinstance(schema.get("type"), list) else []
        return found + [p for k, v in schema.items() for p in _type_lists(v, f"{path}/{k}")]
    if isinstance(schema, list):
        return [p for i, v in enumerate(schema) for p in _type_lists(v, f"{path}[{i}]")]
    return []


def _definitions() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for profile in ("full", "small"):
        for spec in specs():
            definition = spec.model_definition(InitCtx(profile=profile))
            out.append((f"{spec.name}:{profile}", definition))
    return out


def test_no_list_valued_type_reaches_a_local_model() -> None:
    """The wire form has no list-valued `type` anywhere, so no template meets `map('upper')` on one."""
    left = {name: paths for name, d in _definitions() if (paths := _type_lists(grammar_friendly(d["parameters"])))}
    assert left == {}


def test_the_mixed_arrays_keep_their_meaning_as_any_of() -> None:
    """The rewrite is the equivalent schema, not a loss: `["number", "string"]` becomes an `anyOf` of the two."""
    from jsonschema import Draft202012Validator

    schema = {"type": "array", "items": {"type": ["number", "string"]}, "minItems": 2}
    friendly = grammar_friendly(schema)
    assert friendly["items"] == {"anyOf": [{"type": "number"}, {"type": "string"}]}
    for value in ([1, "pi"], [2.5, 3], ["a", "b"]):
        Draft202012Validator(friendly).validate(value)
    assert not Draft202012Validator(friendly).is_valid([1, None])


@pytest.mark.skipif(not _live_up(), reason=f"needs {LIVE_MODEL} served at {LIVE_URL} (a live local model)")
@pytest.mark.parametrize("profile", ["full", "small"])
def test_every_tool_renders_through_the_live_local_template(profile: str) -> None:
    """Each tool alone, through the provider the engine uses: the server renders the chat template and answers."""
    from agent_core.providers.llama import LlamaServerProvider

    async def scenario() -> dict[str, str]:
        live = LlamaServerProvider(LIVE_URL, _key(), request_timeout_s=120)
        failed = {}
        try:
            for spec in specs():
                d = spec.model_definition(InitCtx(profile=profile))
                tool = ToolSchema(d["name"], d["description"], d["parameters"])
                try:
                    await live.complete(LIVE_MODEL, [Message("user", "Hello.")], [tool], max_tokens=1, effort="none")
                except Exception as error:  # collect every tool's failure, not the first
                    failed[spec.name] = repr(error)[:200]
        finally:
            await live.close()
        return failed

    assert asyncio.run(scenario()) == {}
