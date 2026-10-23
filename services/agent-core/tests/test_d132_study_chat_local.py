"""The study Chat on a local model (STU-20, D132): a reply that adds study aids the request did not ask for is trimmed
and checked again, and citation offsets come from the exact quote, so a correct cited answer is not lost."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import validator
from agent_core.engine.events import new_id
from agent_core.engine.reflection import ReflectorModel, _only_requested
from agent_core.engine.study import located

TEXT = "Enzymes are biological catalysts. They speed up chemical reactions without being used up."
QUOTE = "Enzymes are biological catalysts."


def chunk() -> dict[str, Any]:
    return {"chunk_id": new_id("sck"), "source_id": new_id("src"), "revision": 1, "text": TEXT}


def cited(c: dict[str, Any], start: int, end: int, quote: str = QUOTE) -> dict[str, Any]:
    return {"text": quote, "citations": [{"source_id": c["source_id"], "revision": 1, "chunk_id": c["chunk_id"],
                                          "start": start, "end": end, "quote": quote}]}  # fmt: skip


def test_offsets_come_from_the_exact_quote() -> None:
    c = chunk()
    output = {"claims": [cited(c, 0, 20)], "quiz": {"keys": [{"explanation": cited(c, 5, 9)}]}}
    located(output, [c])
    for citation in (output["claims"][0]["citations"][0], output["quiz"]["keys"][0]["explanation"]["citations"][0]):
        assert TEXT[citation["start"] : citation["end"]] == QUOTE
    missing = cited(c, 0, 5, quote="Not in the material at all.")
    located(missing, [c])
    assert missing["citations"][0]["start"] == 0 and missing["citations"][0]["end"] == 5  # left for the check to refuse


def test_a_chat_answer_never_carries_other_study_aids() -> None:
    draft = {"request_id": "x", "kind": "chat", "claims": [], "flashcards": [1], "quiz": {}, "chapters": [2]}
    assert _only_requested(draft, "chat") == {"request_id": "x", "kind": "chat", "claims": []}
    assert set(_only_requested({**draft, "kind": "quiz"}, "quiz")) == {"request_id", "kind", "claims", "quiz"}


def test_an_answer_with_an_unasked_quiz_is_trimmed_and_accepted() -> None:
    c, job = chunk(), new_id("stj")
    reply = {"request_id": job, "kind": "chat", "claims": [cited(c, 0, len(QUOTE))],
             "quiz": {"items": [], "keys": []}}  # fmt: skip

    class Router:
        async def complete(self, *_: Any, **__: Any) -> Any:
            calls = [{"provider_kind": "local"}]
            return SimpleNamespace(schema_valid=False, structured=None, turn=SimpleNamespace(text=json.dumps(reply)),
                                   record=SimpleNamespace(model_calls=lambda: calls))  # fmt: skip

    model = ReflectorModel(router=Router(), assets=None, settings=Settings(), schemas={}, known_tools=frozenset())  # type: ignore[arg-type]
    model.messages = lambda *_a, **_k: []  # type: ignore[method-assign]
    output, local = asyncio.run(model.study_generate(job, {"kind": "chat", "prompt": "What are enzymes?"}, [c]))
    assert local and "quiz" not in output and output["claims"][0]["text"] == QUOTE
    assert not list(validator("study/workspace#/$defs/ProcessingResponse").iter_errors(output))
