"""M42 service protocol and privacy boundaries; provider outputs are scripted, never a model-quality claim."""

import asyncio
import base64
import hashlib
import json

import pytest
from gateway_stubs import Device, Output, gateway_config, harness

JID = "stj_" + "0" * 26
SID = "src_" + "1" * 26
CID = "sck_" + "2" * 26
TEXT = "CANARY source: enzymes are biological catalysts."


@pytest.mark.parametrize("kind", ["summary", "quiz", "flashcards"])
def test_passage_references_preserve_decomposed_unicode_and_still_require_support(tmp_path, kind):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        text = "Δx/Δt = 2.5 m/s. 🧪 A cafe\u0301 label is not a measurement."
        body = {**payload(), "kind": kind}
        body["chunks"][0].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
        claim = {"text": "The source gives 2.5 m/s.", "citations": [{"passage_id": "p0"}]}
        draft = {"request_id": JID, "kind": kind, "claims": [claim]}
        if kind == "flashcards":
            body["count"] = 1
            draft["flashcards"] = [
                {
                    "front": {
                        "text": r"What value does the source give for \(\Delta x/\Delta t\)?",
                        "citations": [{"passage_id": "p0"}],
                    },
                    "back": claim,
                }
            ]
        if kind == "quiz":
            body["count"] = 1
            draft["quiz"] = {
                "items": [
                    {
                        "item_id": "q1",
                        "type": "choice",
                        "stem": claim,
                        "options": [{"option_id": "a", "text": "2.5 m/s"}, {"option_id": "b", "text": "5 m/s"}],
                    }
                ],
                "keys": [{"item_id": "q1", "answer": "a", "explanation": claim, "marking": "judged"}],
            }
        for attempt, supported in [(1, True), (2, False)]:
            h.stubs["gemini"].say(
                Output(text=json.dumps(draft)),
                Output(text=json.dumps({"supported": supported, "reason": "EPHEMERAL verifier reason"})),
            )
            response = await h.client.post(
                "/v1/study/process", json=body, headers={**device.headers(), "x-study-attempt": str(attempt)}
            )
            assert response.status_code == (200 if supported else 422), response.text
            assert b"EPHEMERAL verifier reason" not in response.content
            if supported:
                result = response.json()
                citation = result["claims"][0]["citations"][0]
                assert citation == {
                    "source_id": SID,
                    "revision": 1,
                    "chunk_id": CID,
                    "start": 0,
                    "end": len(text),
                    "quote": text,
                }
                assert "e\u0301" in citation["quote"] and "é" not in citation["quote"]
                if kind == "quiz":
                    assert result["quiz"]["keys"][0]["explanation"]["citations"] == [citation]
                if kind == "flashcards":
                    assert result["flashcards"][0]["front"]["citations"] == [citation]
                    assert result["flashcards"][0]["back"]["citations"] == [citation]
                sent = h.stubs["gemini"].seen[0].user_texts[0]
                assert "🧪" in sent and "e\u0301" in sent and "\\u0301" not in sent
                citation_schema = (
                    h.stubs["gemini"]
                    .seen[0]
                    .schema["properties"]["claims"]["items"]["properties"]["citations"]["items"]
                )
                assert citation_schema["properties"]["passage_id"]["enum"] == ["p0"]
                await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())
        store = h.client._transport.app.state.gateway.store
        assert store._db.execute("SELECT status,outcome FROM requests ORDER BY rowid").fetchall() == [
            (200, "completed"),
            (422, "support_rejected_other"),
        ]
        for file in tmp_path.rglob("*"):
            if file.is_file():
                assert b"EPHEMERAL verifier reason" not in file.read_bytes()

    asyncio.run(run())


@pytest.mark.parametrize(
    "reference",
    [
        {"passage_id": "p999"},
        {"passage_id": []},
        {"passage_id": "p0", "revision": 2},
        {"passage_id": "p0", "quote": "invented"},
    ],
)
def test_invented_or_mixed_passage_reference_is_withheld_before_support(tmp_path, reference):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {"request_id": JID, "kind": "summary", "claims": [{"text": "A claim", "citations": [reference]}]}
        h.stubs["gemini"].say(Output(text=json.dumps(draft)))
        response = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert response.status_code == 422
        assert len(h.stubs["gemini"].seen) == 1
        assert not h.client._transport.app.state.study.buffers
        assert h.client._transport.app.state.gateway.store._db.execute("SELECT outcome FROM requests").fetchone() == (
            "citation_reference",
        )

    asyncio.run(run())


def test_passage_partition_is_lossless_and_repeated_text_binds_to_selected_revision():
    from cloud_gateway.study import bind_passages, source_passages

    text = ("α 🧪 cafe\u0301 " * 100) + "x" * 1001
    chunk = payload()["chunks"][0]
    chunks = [{**chunk, "text": text}, {**chunk, "source_id": "src_" + "3" * 26, "revision": 2, "text": text}]
    passages = source_passages(chunks)
    for source in chunks:
        selected = [c for c in passages.values() if c["source_id"] == source["source_id"]]
        assert "".join(c["quote"] for c in selected) == text
        assert all(0 < len(c["quote"]) <= 500 and text[c["start"] : c["end"]] == c["quote"] for c in selected)
    key = next(k for k, c in passages.items() if c["revision"] == 2)
    draft = {"citations": [{"passage_id": key}]}
    bind_passages(draft, passages)
    assert draft["citations"] == [passages[key]]
    assert draft["citations"][0] is not passages[key]


@pytest.mark.parametrize(
    "safe,flags,accepted",
    [
        (True, [True, False], True),
        (True, [False, False], False),
        (False, [True, False], False),
        (True, [True], False),
        (True, [True, "yes"], False),
    ],
)
@pytest.mark.parametrize("answerable", [True, False])
@pytest.mark.parametrize("batch_supported", [True, False])
@pytest.mark.parametrize("kind", ["summary", "notes", "audio_overview"])
def test_prose_aids_keep_only_individually_supported_claims_and_require_safety(
    tmp_path, safe, flags, accepted, batch_supported, kind, answerable
):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": kind,
            "claims": [
                {"text": TEXT, "citations": [{"passage_id": "p0"}]},
                {"text": "Unsupported claim to withhold", "citations": [{"passage_id": "p0"}]},
            ],
        }
        verdict = {
            "reason": "Synthetic check",
            "safe": safe,
            "claim_support": flags,
            "supported": batch_supported,
            "answerable": answerable,
            "repairable": False,
        }
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text=json.dumps(verdict)))
        result = await h.client.post("/v1/study/process", json={**payload(), "kind": kind}, headers=device.headers())
        assert result.status_code == (200 if accepted and answerable else 422), result.text
        if accepted and answerable:
            assert [c["text"] for c in result.json()["claims"]] == [TEXT]
            assert result.json()["claims"][0]["citations"][0]["quote"] == TEXT
        else:
            assert "claims" not in result.json()
        assert len(h.stubs["gemini"].seen) == 2

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["flashcards", "quiz"])
@pytest.mark.parametrize("problem", [None, "unsafe", "all_unsupported", "missing_flags", "wrong_count", "non_boolean"])
def test_cards_and_quiz_keep_only_whole_verified_items_with_matching_keys(tmp_path, kind, problem):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)

        def fact(text):
            return {"text": text, "citations": [{"passage_id": "p0"}]}

        draft = {"request_id": JID, "kind": kind, "claims": [fact("Unsupported accompanying claim")]}
        verdict = {
            "reason": "Synthetic per-item check",
            "safe": problem != "unsafe",
            "supported": False,
            "answerable": True,
            "repairable": False,
            "claim_support": [False],
        }
        support_name = "card_support" if kind == "flashcards" else "question_support"
        verdict[support_name] = [True, False]
        if problem == "all_unsupported":
            verdict[support_name] = [False, False]
        elif problem == "missing_flags":
            verdict.pop(support_name)
        elif problem == "wrong_count":
            verdict[support_name] = [True]
        elif problem == "non_boolean":
            verdict[support_name] = [True, "false"]
        if kind == "flashcards":
            draft["flashcards"] = [
                {"front": fact("What are enzymes?"), "back": fact(TEXT)},
                {"front": fact("An unsupported question?"), "back": fact("Unsupported answer")},
            ]
        else:
            draft["quiz"] = {
                "items": [
                    {"item_id": "q1", "type": "true_false", "stem": fact(TEXT)},
                    {"item_id": "q2", "type": "true_false", "stem": fact("Unsupported question")},
                ],
                # Deliberately opposite order: keys must follow identities, never array position.
                "keys": [
                    {
                        "item_id": "q2",
                        "answer": "false",
                        "explanation": fact("Unsupported answer"),
                        "marking": "judged",
                    },
                    {"item_id": "q1", "answer": "true", "explanation": fact(TEXT), "marking": "judged"},
                ],
            }
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text=json.dumps(verdict)))
        response = await h.client.post(
            "/v1/study/process", json={**payload(), "kind": kind, "count": 2}, headers=device.headers()
        )
        assert response.status_code == (200 if problem is None else 422), response.text
        if problem is None:
            result = response.json()
            assert [c["text"] for c in result["claims"]] == [TEXT]
            if kind == "flashcards":
                assert len(result["flashcards"]) == 1 and result["flashcards"][0]["back"]["text"] == TEXT
            else:
                assert [q["item_id"] for q in result["quiz"]["items"]] == ["q1"]
                assert [(k["item_id"], k["answer"]) for k in result["quiz"]["keys"]] == [("q1", "true")]
        else:
            assert "claims" not in response.json()
        assert len(h.stubs["gemini"].seen) == 2

    asyncio.run(run())


def test_compact_support_preserves_all_evidence_and_exact_citation_bindings():
    from cloud_gateway.study import bind_passages, model_passages, source_passages, support_material

    chunks = payload()["chunks"]
    chunks[0]["text"] = ("A cafe\u0301 has two observations. The condition still applies. " * 35) + "LAST PAGE FACT"
    passages = source_passages(chunks)
    draft = {
        "claims": [
            {"text": "A condition applies.", "citations": [{"passage_id": "p0"}]},
            {"text": "Repeated citation.", "citations": [{"passage_id": "p0"}]},
        ]
    }
    bind_passages(draft, passages)
    original = json.dumps(draft)
    wire = support_material(chunks, draft, passages)
    assert "".join(p["quote"] for p in wire["sources"]) == chunks[0]["text"]
    assert all(p["locator"] == chunks[0]["locator"] for p in wire["sources"])
    assert wire["sources"] == model_passages(chunks, passages)
    assert wire["draft"]["claims"][0]["citations"] == [{"passage_id": "p0"}]
    assert json.dumps(draft) == original
    bind_passages(wire["draft"], passages)
    assert wire["draft"] == draft


def test_flashcards_withhold_unsupported_accompanying_claim_even_when_cards_are_grounded(tmp_path):
    """Replay the observed failure: cards quote v correctly, but a separate claim invents its meaning."""

    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        text = "The source gives v = Δx/Δt = 2.5 m/s. 🧪 A cafe\u0301 label is not a measurement."
        body = {**payload(), "kind": "flashcards", "count": 1}
        body["chunks"][0].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())

        def claim(text):
            return {"text": text, "citations": [{"passage_id": "p0"}]}

        cards = [{"front": claim("What value is given for v?"), "back": claim(r"\(v = 2.5\,\mathrm{m/s}\).")}]
        for attempt, supported, wording in [
            (1, False, "The velocity is 2.5 m/s."),
            (2, True, r"The source gives \(v = \Delta x/\Delta t = 2.5\,\mathrm{m/s}\)."),
        ]:
            draft = {"request_id": JID, "kind": "flashcards", "claims": [claim(wording)], "flashcards": cards}
            h.stubs["gemini"].say(
                Output(text=json.dumps(draft)),
                Output(text=json.dumps({"supported": supported, "answerable": True})),
            )
            result = await h.client.post(
                "/v1/study/process", json=body, headers={**device.headers(), "x-study-attempt": str(attempt)}
            )
            assert result.status_code == (200 if supported else 422)
            assert len(h.stubs["gemini"].seen) == attempt * 2  # Never retry or drop an unsupported claim silently.
            if supported:
                accepted = result.json()
                assert accepted["claims"][0]["text"] == wording
                assert accepted["flashcards"][0]["back"]["citations"][0]["quote"] == text
                await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())
            else:
                assert result.json()["error"]["code"] == "insufficient_evidence"
            assert not h.client._transport.app.state.study.buffers
        receipts = h.client._transport.app.state.gateway.store._db.execute(
            "SELECT status,outcome FROM requests ORDER BY rowid"
        ).fetchall()
        assert receipts == [(422, "support_rejected_other"), (200, "completed")]

    asyncio.run(run())


@pytest.mark.parametrize("revised_supported", [True, False])
def test_known_repairable_rejection_gets_one_reverified_draft_and_one_combined_charge(tmp_path, revised_supported):
    from cloud_gateway.providers.base import Usage
    from cloud_gateway.quotas import cost_usd

    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [{"text": "A claim", "citations": [{"passage_id": "p0"}]}],
        }
        feedback = "EPHEMERAL revision: use the source's cafe\u0301 notation without an invented definition."
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(text=json.dumps({"supported": False, "answerable": True, "repairable": True, "reason": feedback})),
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps(
                    {"supported": revised_supported, "answerable": True, "repairable": True, "reason": "Second verdict"}
                )
            ),
        )
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == (200 if revised_supported else 422)
        seen = h.stubs["gemini"].seen
        assert len(seen) == 4
        first, second = [json.loads(seen[i].user_texts[0]) for i in (0, 2)]
        assert second == {**first, "revision_feedback": feedback}
        assert "e\u0301" in seen[2].user_texts[0] and "\\u0301" not in seen[2].user_texts[0]
        store = h.client._transport.app.state.gateway.store
        actual = cost_usd(h.client._transport.app.state.gateway.config.prices["gemini-stub-flash"], Usage(160, 48, 32))
        assert store._db.execute("SELECT state,actual_usd,reserved_usd FROM study_receipts").fetchall() == [
            ("completed" if revised_supported else "failed", actual, 0.0)
        ]
        assert store._db.execute("SELECT tokens_in,tokens_out FROM requests").fetchall() == [(160, 48)]
        assert b"EPHEMERAL revision" not in result.content
        if revised_supported:
            assert result.json()["usage"]["input_tokens"] == 160
            again = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
            assert again.json() == result.json() and len(seen) == 4
            await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())
        assert not h.client._transport.app.state.study.buffers
        for file in tmp_path.rglob("*"):
            if file.is_file():
                assert b"EPHEMERAL revision" not in file.read_bytes()

    asyncio.run(run())


@pytest.mark.parametrize("answerable,repairable", [(False, True), (True, False), (True, "true")])
def test_missing_answer_or_non_repairable_refusal_never_generates_another_draft(tmp_path, answerable, repairable):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {**payload(), "kind": "chat", "prompt": "What is absent from this source?"}
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [{"text": "A claim", "citations": [{"passage_id": "p0"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps(
                    {"supported": False, "answerable": answerable, "repairable": repairable, "reason": "Do not revise"}
                )
            ),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == 422 and len(h.stubs["gemini"].seen) == 2
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


def test_unknown_provider_outcome_during_revision_stays_held_and_is_not_resent(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [{"text": "A claim", "citations": [{"passage_id": "p0"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps({"supported": False, "answerable": True, "repairable": True, "reason": "Fix wording"})
            ),
            Output(error=(503, {"error": {"status": "UNAVAILABLE", "message": "unknown usage"}})),
        )
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == 502 and len(h.stubs["gemini"].seen) == 3
        again = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert again.status_code == 409 and len(h.stubs["gemini"].seen) == 3
        state, actual, held = h.client._transport.app.state.gateway.store._db.execute(
            "SELECT state,actual_usd,reserved_usd FROM study_receipts"
        ).fetchone()
        assert state == "reserved" and actual == 0 and held > 0
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


@pytest.mark.parametrize("malformed", [False, True])
def test_revised_draft_must_repeat_json_and_citation_validation_before_verification(tmp_path, malformed):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [{"text": "A claim", "citations": [{"passage_id": "p0"}]}],
        }
        revised = json.dumps(draft).replace('"p0"', '"p999"') if not malformed else '{"claims":'
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps({"supported": False, "answerable": True, "repairable": True, "reason": "Fix wording"})
            ),
            Output(text=revised),
        )
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == 422 and len(h.stubs["gemini"].seen) == 3
        state, held = h.client._transport.app.state.gateway.store._db.execute(
            "SELECT state,reserved_usd FROM study_receipts"
        ).fetchone()
        assert state == "failed" and held == 0
        assert h.client._transport.app.state.gateway.store._db.execute("SELECT outcome FROM requests").fetchone() == (
            "draft_json" if malformed else "citation_reference",
        )
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["notes", "summary", "chat", "flashcards", "quiz", "audio_overview"])
def test_generation_citation_schema_restricts_every_reference_to_this_request(kind):
    from cloud_gateway.study import generation_schema, source_passages
    from jsonschema import Draft202012Validator

    chunks = [payload()["chunks"][0], {**payload()["chunks"][0], "revision": 2, "text": "Different revision."}]
    passages = source_passages(chunks)
    schema = generation_schema(kind, JID, passage_ids=list(passages))
    references = []

    def visit(value):
        if isinstance(value, dict):
            if "passage_id" in value.get("properties", {}):
                references.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    assert references
    for reference in references:
        validate = Draft202012Validator(reference)
        assert reference["properties"]["passage_id"]["enum"] == list(passages)
        assert all(validate.is_valid({"passage_id": passage}) for passage in passages)
        assert not validate.is_valid({"passage_id": "p999"})
        assert not validate.is_valid({"passage_id": "p0", "quote": "invented"})


def test_quiz_generation_schema_enforces_choice_and_non_choice_field_shapes():
    from cloud_gateway.study import generation_schema
    from jsonschema import Draft202012Validator

    schema = generation_schema("quiz", JID, 2, passage_ids=["p0"])["properties"]["quiz"]["properties"]["items"]["items"]
    validate = Draft202012Validator(schema)
    stem = {"text": "Question?", "citations": [{"passage_id": "p0"}]}
    choice = {
        "item_id": "q1",
        "type": "choice",
        "stem": stem,
        "options": [{"option_id": "a", "text": "One"}, {"option_id": "b", "text": "Two"}],
    }
    assert validate.is_valid(choice)
    assert not validate.is_valid({**choice, "unit_prompt": ""})
    assert not validate.is_valid({k: v for k, v in choice.items() if k != "options"})
    numeric = {"item_id": "q2", "type": "numeric", "stem": stem, "unit_prompt": "m/s"}
    assert validate.is_valid(numeric)
    assert not validate.is_valid({**numeric, "options": choice["options"]})


@pytest.mark.parametrize("actual_value,unconditional", [(False, True), (True, True), (True, False)])
def test_motion_chat_preserves_conditional_source_report_without_inventing_runner_direction(
    tmp_path, actual_value, unconditional
):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        text = (
            "A runner travels 10 metres in 2 seconds at constant speed. The source gives speed = "
            "distance/time = 10/2 = 5 metres per second. Constant speed in a straight line means zero acceleration."
        )
        prompt = (
            "What is this runner's actual acceleration?"
            if actual_value
            else "What speed and acceleration does the source state?"
        )
        body = {**payload(), "kind": "chat", "prompt": prompt}
        body["chunks"][0].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())

        def draft(acceleration):
            return {
                "request_id": JID,
                "kind": "chat",
                "claims": [
                    {
                        "text": "The source gives speed = 10/2 = 5 metres per second.",
                        "citations": [{"passage_id": "p0"}],
                    },
                    {"text": acceleration, "citations": [{"passage_id": "p0"}]},
                ],
            }

        # Exact unsupported acceleration claim captured in the live synthetic reproduction.
        wrong = (
            "The source states that there is zero acceleration, because constant speed in a straight line "
            "means zero acceleration."
        )
        conditional = "The source states that constant speed in a straight line means zero acceleration."
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft(wrong if unconditional else conditional))),
            Output(
                text=json.dumps(
                    {
                        "supported": not unconditional,
                        "answerable": not actual_value,
                        "repairable": not actual_value,
                        "reason": "Retain the straight-line condition; the runner's direction is not established.",
                    }
                )
            ),
        )
        if not actual_value:
            h.stubs["gemini"].say(
                Output(text=json.dumps(draft(conditional))),
                Output(text=json.dumps({"supported": True, "answerable": True, "repairable": False})),
            )
        response = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert response.status_code == (422 if actual_value else 200)
        assert len(h.stubs["gemini"].seen) == (2 if actual_value else 4)
        if not actual_value:
            assert response.json()["claims"][1]["text"] == conditional
        for sent in h.stubs["gemini"].seen[::2]:
            assert sent.schema["properties"]["claims"]["items"]["properties"]["citations"]["items"]["properties"][
                "passage_id"
            ]["enum"] == ["p0"]

    asyncio.run(run())


@pytest.mark.parametrize("supported,answerable", [(True, False), (False, True), (False, False)])
def test_chat_requires_answerable_even_when_an_unrelated_fact_is_supported(tmp_path, supported, answerable):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {**payload(), "kind": "chat", "prompt": "What is the author's year of birth?"}
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [
                {
                    "text": "Enzymes are catalysts.",
                    "citations": [
                        {"source_id": SID, "revision": 1, "chunk_id": CID, "start": 0, "end": len(TEXT), "quote": TEXT}
                    ],
                }
            ],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)), Output(text=json.dumps({"supported": supported, "answerable": answerable}))
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == 422 and result.json()["error"]["code"] == "insufficient_evidence"
        assert "author's year of birth" in json.dumps(h.stubs["gemini"].seen[1].user_texts)
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


@pytest.mark.parametrize("valid_second_draft", [True, False])
def test_math_format_gets_one_bounded_retry_before_independent_support(tmp_path, valid_second_draft):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = payload()
        body["chunks"][0].update(text="x_i=2", sha256=hashlib.sha256(b"x_i=2").hexdigest())

        def draft(text):
            return {
                "request_id": JID,
                "kind": "summary",
                "claims": [{"text": text, "citations": [{"passage_id": "p0"}]}],
            }

        h.stubs["gemini"].say(
            Output(text=json.dumps(draft("x_i=2"))),
            Output(text=json.dumps(draft(r"\(x_i=2\)" if valid_second_draft else "x_i=2"))),
            *([Output(text='{"supported":true}')] if valid_second_draft else []),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (200 if valid_second_draft else 422), result.text
        assert len(h.stubs["gemini"].seen) == (3 if valid_second_draft else 2)
        if valid_second_draft:
            assert result.json()["claims"][0]["text"] == r"\(x_i=2\)"
            assert result.json()["claims"][0]["citations"][0]["quote"] == "x_i=2"
        store = h.client._transport.app.state.gateway.store
        assert store._db.execute("select count(*) from requests").fetchone()[0] == 1
        assert store._db.execute("select reserved_usd from study_receipts").fetchone()[0] == 0

    asyncio.run(run())


@pytest.mark.parametrize("second_valid,supported", [(True, True), (True, False), (False, False)])
def test_malformed_nebius_display_parts_get_one_fresh_verified_retry(tmp_path, second_valid, supported):
    async def run():
        h = harness(gateway_config(tmp_path, slots={"primary": "nebius", "fallback": "openai_compat"}))
        device = Device()
        await device.login(h.client)

        def draft(valid):
            claim = {
                "text": [{"kind": "prose", "value": "Enzymes are biological catalysts." if valid else ""}],
                "citations": [{"passage_id": "p0"}],
            }
            return {"request_id": JID, "kind": "summary", "claims": [claim]}

        h.stubs["nebius"].say(
            Output(text=json.dumps(draft(False))),
            Output(text=json.dumps(draft(second_valid))),
            *(
                [
                    Output(
                        text=json.dumps(
                            {
                                "supported": supported,
                                "safe": True,
                                "answerable": True,
                                "repairable": False,
                                "reason": "Checked",
                                "claim_support": [supported],
                            }
                        )
                    )
                ]
                if second_valid
                else []
            ),
        )
        response = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert response.status_code == (200 if supported else 422), response.text
        calls = h.stubs["nebius"].seen
        assert len(calls) == (3 if second_valid else 2)
        assert json.loads(calls[0].user_texts[0])["passages"] == json.loads(calls[1].user_texts[0])["passages"]
        assert "nonempty string" in calls[1].system
        if supported:
            assert response.json()["claims"][0]["text"] == "Enzymes are biological catalysts."
            assert response.json()["claims"][0]["citations"][0]["quote"] == TEXT
        if second_valid:
            assert (
                json.loads(calls[2].user_texts[0])["draft"]["claims"][0]["text"] == "Enzymes are biological catalysts."
            )
        store = h.client._transport.app.state.gateway.store
        assert store._db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert store._db.execute("SELECT reserved_usd FROM study_receipts").fetchone()[0] == 0

    asyncio.run(run())


@pytest.mark.parametrize("second_valid", [True, False])
def test_malformed_nebius_verdict_never_publishes_before_a_fresh_verified_draft(tmp_path, second_valid):
    async def run():
        h = harness(gateway_config(tmp_path, slots={"primary": "nebius", "fallback": "openai_compat"}))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [
                {
                    "text": [{"kind": "prose", "value": "Enzymes are biological catalysts."}],
                    "citations": [{"passage_id": "p0"}],
                }
            ],
        }
        verdict = {
            "supported": True,
            "safe": True,
            "answerable": True,
            "repairable": False,
            "reason": "Checked",
            "claim_support": [True],
        }
        malformed = {**verdict, "claim_support": "true"}
        h.stubs["nebius"].say(
            Output(text=json.dumps(draft)),
            Output(text=json.dumps(malformed)),
            Output(text=json.dumps(draft)),
            Output(text=json.dumps(verdict if second_valid else malformed)),
        )
        response = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert response.status_code == (200 if second_valid else 422), response.text
        calls = h.stubs["nebius"].seen
        assert len(calls) == 4
        assert "verification response was malformed" in calls[2].system
        assert json.loads(calls[0].user_texts[0])["passages"] == json.loads(calls[2].user_texts[0])["passages"]
        store = h.client._transport.app.state.gateway.store
        assert store._db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert store._db.execute("SELECT reserved_usd FROM study_receipts").fetchone()[0] == 0

    asyncio.run(run())


@pytest.mark.parametrize("supported", [True, False])
def test_retained_formatted_points_still_require_independent_source_verification(tmp_path, supported):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [
                {"text": "x_i=2", "citations": [{"passage_id": "p0"}]},
                {"text": TEXT, "citations": [{"passage_id": "p0"}]},
            ],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(text=json.dumps(draft)),
            Output(text=json.dumps({"supported": supported})),
        )
        response = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert response.status_code == (200 if supported else 422), response.text
        assert len(h.stubs["gemini"].seen) == 3
        verification = json.loads(h.stubs["gemini"].seen[2].user_texts[0])
        assert [c["text"] for c in verification["draft"]["claims"]] == [TEXT]
        if supported:
            assert [c["text"] for c in response.json()["claims"]] == [TEXT]

    asyncio.run(run())


def test_teaching_chat_is_one_ordered_lesson_with_original_evidence(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {**payload(), "kind": "chat", "prompt": "Teach me from the beginning of notes.pdf."}
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [{"text": "Enzymes are biological catalysts.", "citations": [{"passage_id": "p0"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(text=json.dumps({"supported": True, "answerable": True})),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == 200, result.text
        system = h.stubs["gemini"].seen[0].system
        assert "one coherent response" in system and "earliest substantive learning concept" in system
        assert "example already present" in system and "Do not restart" in system
        assert len(h.stubs["gemini"].seen) == 2  # final answer still has independent support verification
        citation = result.json()["claims"][0]["citations"][0]
        assert citation["chunk_id"] == CID and citation["quote"] == TEXT

    asyncio.run(run())


@pytest.mark.parametrize("supported", [True, False])
def test_lesson_followup_context_reaches_both_models_without_becoming_evidence(tmp_path, supported):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        previous = "1. Enzymes are biological catalysts."
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "Can you explain that step again, a different way?",
            "previous_response": previous,
        }
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [{"text": "Enzymes are catalysts.", "citations": [{"passage_id": "p0"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps(
                    {
                        "supported": supported,
                        "answerable": True,
                        "repairable": False,
                    }
                )
            ),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (200 if supported else 422), result.text
        calls = h.stubs["gemini"].seen
        assert previous in json.dumps(calls[0].user_texts)
        assert previous in json.dumps(calls[1].user_texts)
        assert "not factual evidence" in calls[0].system
        if supported:
            assert result.json()["claims"][0]["citations"][0]["quote"] == TEXT

    asyncio.run(run())


def payload():
    chunk = {
        "chunk_id": CID,
        "source_id": SID,
        "revision": 1,
        "ordinal": 0,
        "locator": {"kind": "text", "paragraph": 1},
        "text": TEXT,
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    return {"request_id": JID, "kind": "summary", "chunks": [chunk], "output_locale": "en"}


def test_processing_support_once_cleanup_and_no_body_storage(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [
                {
                    "text": TEXT,
                    "citations": [
                        {"source_id": SID, "revision": 1, "chunk_id": CID, "start": 0, "end": len(TEXT), "quote": TEXT}
                    ],
                }
            ],
        }
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text='{"supported":true}'))
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == 200, result.text
        assert {k: v for k, v in result.json().items() if k != "usage"} == draft
        again = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert again.status_code == 200 and again.json() == result.json()
        assert len(h.stubs["gemini"].seen) == 2
        changed = await h.client.post(
            "/v1/study/process", json={**payload(), "output_locale": "fr"}, headers=device.headers()
        )
        assert changed.status_code == 409
        cleanup = await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())
        assert cleanup.status_code == 204
        refused = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert refused.status_code == 410
        for file in tmp_path.rglob("*"):
            if file.is_file():
                assert b"CANARY" not in file.read_bytes()

    asyncio.run(run())


def test_ephemeral_upload_auth_hash_replay_memory_and_expiry(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        one, two = Device(), Device()
        await one.login(h.client)
        await two.login(h.client)
        data = b"CANARY selected original file"
        create = {
            "request_id": JID,
            "kind": "document",
            "mime_type": "text/plain",
            "byte_length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        response = await h.client.post("/v1/study/uploads", json=create, headers=one.headers())
        assert response.status_code == 200, response.text
        upload = response.json()["upload_id"]
        store = h.client._transport.app.state.gateway.store
        reservation = store._db.execute("SELECT state,reserved_usd FROM study_receipts").fetchone()
        assert reservation[0] == "reserved" and reservation[1] > 0
        part = {"offset": 0, "sha256": hashlib.sha256(data).hexdigest(), "data_base64": base64.b64encode(data).decode()}
        path = f"/v1/study/uploads/{upload}/chunks/0"
        assert (await h.client.put(path, json=part, headers=two.headers())).status_code == 404
        assert (await h.client.put(path, json=part, headers=one.headers())).json()["complete"]
        assert (await h.client.put(path, json=part, headers=one.headers())).json()["received_bytes"] == len(data)
        h.clock.now += 901
        await one.login(h.client)
        assert (await h.client.put(path, json=part, headers=one.headers())).status_code == 404
        assert store._db.execute("SELECT state,reserved_usd,actual_usd FROM study_receipts").fetchone() == (
            "failed",
            0,
            0,
        )
        for file in tmp_path.rglob("*"):
            if file.is_file():
                assert b"CANARY" not in file.read_bytes()

    asyncio.run(run())


def test_actual_cloud_sandbox_extraction_paging_and_deletion(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        data = b"Enzymes are biological catalysts.\n" * 1000
        body = {
            "request_id": JID,
            "kind": "document",
            "mime_type": "text/plain",
            "byte_length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        grant = await h.client.post("/v1/study/uploads", json=body, headers=device.headers())
        assert grant.status_code == 200
        uid = grant.json()["upload_id"]
        part = {"offset": 0, "sha256": body["sha256"], "data_base64": base64.b64encode(data).decode()}
        assert (
            await h.client.put(f"/v1/study/uploads/{uid}/chunks/0", json=part, headers=device.headers())
        ).status_code == 200
        extracted = await h.client.post(
            "/v1/study/extract",
            json={"request_id": JID, "upload_id": uid, "source_id": SID, "revision": 1, "locale": "en"},
            headers=device.headers(),
        )
        assert extracted.status_code == 200, extracted.text
        assert "".join(c["text"] for c in extracted.json()["chunks"]) == data.decode().strip()
        assert all(c["source_id"] == SID for c in extracted.json()["chunks"])
        replay = await h.client.post(
            "/v1/study/extract",
            json={"request_id": JID, "upload_id": uid, "source_id": SID, "revision": 1, "locale": "en"},
            headers=device.headers(),
        )
        assert replay.json() == extracted.json()  # raw bytes were destroyed; replay uses the frozen result.
        changed = await h.client.post(
            "/v1/study/extract",
            json={"request_id": JID, "upload_id": uid, "source_id": SID, "revision": 2, "locale": "en"},
            headers=device.headers(),
        )
        assert changed.status_code == 409
        store = h.client._transport.app.state.gateway.store
        receipt = store._db.execute("SELECT state,reserved_usd,actual_usd FROM study_receipts").fetchone()
        assert receipt[0] == "completed" and receipt[1] == 0
        pages = (
            len(data.decode().strip()) + h.config.study_extract_chars_per_page - 1
        ) // h.config.study_extract_chars_per_page
        assert receipt[2] == pages * h.config.study_extract_page_usd
        assert store._db.execute("SELECT count(*) FROM requests WHERE model='study-extraction'").fetchone()[0] == 1
        assert (await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())).status_code == 204
        assert (await h.client.get(f"/v1/study/extractions/{JID}/chunks", headers=device.headers())).status_code == 404

    asyncio.run(run())


def test_draft_unicode_offsets_bind_only_to_exact_unique_quote_and_settle_once(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        text = "😀 DNA stores information."
        body = payload()
        body["chunks"][0].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
        citation = {"source_id": SID, "revision": 1, "chunk_id": CID, "start": 0, "end": 2, "quote": "DNA"}
        draft = {
            "request_id": JID,
            "kind": "summary",
            "claims": [{"text": "DNA stores information.", "citations": [citation]}],
        }
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text='{"supported":true}'))
        reply = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert reply.status_code == 200, reply.text
        assert reply.json()["claims"][0]["citations"][0] == {**citation, "start": 2, "end": 5}
        store = h.client._transport.app.state.gateway.store
        assert store._db.execute("SELECT count(*) FROM requests WHERE feature='study_materials'").fetchone()[0] == 1
        assert (await h.client.post("/v1/study/process", json=body, headers=device.headers())).status_code == 200
        assert store._db.execute("SELECT count(*) FROM requests WHERE feature='study_materials'").fetchone()[0] == 1
        await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())
        # An explicit higher attempt is a new send; the erased attempt itself cannot replay.
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text='{"supported":true}'))
        assert (
            await h.client.post("/v1/study/process", json=body, headers={**device.headers(), "x-study-attempt": "2"})
        ).status_code == 200
        second = {**body, "request_id": "stj_" + "3" * 26}
        second["chunks"] = [{**body["chunks"][0], "text": "DNA DNA", "sha256": hashlib.sha256(b"DNA DNA").hexdigest()}]
        ambiguous = {**draft, "request_id": second["request_id"]}
        h.stubs["gemini"].say(Output(text=json.dumps(ambiguous)))
        assert (await h.client.post("/v1/study/process", json=second, headers=device.headers())).status_code == 422
        assert len(h.stubs["gemini"].seen) == 5  # no support/model retry for an ambiguous quote.

    asyncio.run(run())


def test_unknown_provider_usage_retains_reservation_and_prevents_automatic_resend(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(error=(503, {"error": {"message": "synthetic unavailable"}})))
        assert (await h.client.post("/v1/study/process", json=payload(), headers=device.headers())).status_code == 502
        assert (await h.client.post("/v1/study/process", json=payload(), headers=device.headers())).status_code == 409
        store = h.client._transport.app.state.gateway.store
        row = store._db.execute("SELECT state,reserved_usd,actual_usd FROM study_receipts").fetchone()
        assert row[0] == "reserved" and row[1] > 0 and row[2] == 0
        assert len(h.stubs["gemini"].seen) == 1
        h.clock.now += 31 * 86400
        h.client._transport.app.state.study.sweep()
        assert store._db.execute("SELECT state FROM study_receipts").fetchone()[0] == "reserved"

    asyncio.run(run())


@pytest.mark.parametrize("truncated_call", [1, 2])
def test_token_limit_completion_is_withheld_even_when_json_is_parseable(tmp_path, monkeypatch, truncated_call):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        gateway = h.client._transport.app.state.gateway
        adapter = gateway.providers.resolve(gateway.config.study_model)[1]
        complete = adapter.complete
        calls = 0

        async def limited(*args, **kwargs):
            nonlocal calls
            reply = await complete(*args, **kwargs)
            calls += 1
            if calls == truncated_call or (truncated_call == 1 and calls == 2):
                reply.body["choices"][0]["finish_reason"] = "length"
            return reply

        monkeypatch.setattr(adapter, "complete", limited)
        draft = {"request_id": JID, "kind": "summary", "claims": [{"text": TEXT, "citations": [{"passage_id": "p0"}]}]}
        h.stubs["gemini"].say(Output(text=json.dumps(draft)), Output(text='{"supported":true}'))
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == 503 and result.json()["error"]["code"] == "model_unavailable"
        assert calls == 2
        assert not h.client._transport.app.state.study.buffers
        row = gateway.store._db.execute("SELECT state,reserved_usd,actual_usd FROM study_receipts").fetchone()
        assert row[0] == "failed" and row[1] == 0 and row[2] > 0

    asyncio.run(run())


def test_truncated_model_json_is_withheld_and_known_usage_settled(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text='{"claims": ['))
        result = await h.client.post("/v1/study/process", json=payload(), headers=device.headers())
        assert result.status_code == 422 and result.json()["error"]["code"] == "insufficient_evidence"
        row = h.client._transport.app.state.gateway.store._db.execute(
            "SELECT state,reserved_usd,actual_usd FROM study_receipts"
        ).fetchone()
        assert row[0] == "failed" and row[1] == 0 and row[2] > 0
        assert not h.client._transport.app.state.study.buffers
        assert len(h.stubs["gemini"].seen) == 1

    asyncio.run(run())


@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.parametrize("kind", ["summary", "quiz"])
def test_observed_output_limit_retries_one_fresh_draft_and_still_requires_support(
    tmp_path, monkeypatch, supported, kind
):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        gateway = h.client._transport.app.state.gateway
        adapter = gateway.providers.resolve(gateway.config.study_model)[1]
        complete = adapter.complete
        calls = 0

        async def limited(*args, **kwargs):
            nonlocal calls
            reply = await complete(*args, **kwargs)
            calls += 1
            if calls == 1:
                reply.body["choices"][0]["finish_reason"] = "length"
            return reply

        monkeypatch.setattr(adapter, "complete", limited)
        claim = {"text": TEXT, "citations": [{"passage_id": "p0"}]}
        body = {**payload(), "kind": kind}
        draft = {"request_id": JID, "kind": kind, "claims": [claim]}
        if kind == "quiz":
            body.update(count=10, settings={"question_types": ["choice", "fill_blank", "true_false"]})
            draft["quiz"] = {
                "items": [
                    {
                        "item_id": "q1",
                        "type": "choice",
                        "stem": claim,
                        "options": [{"option_id": "a", "text": "Given"}, {"option_id": "b", "text": "Absent"}],
                    }
                ],
                "keys": [{"item_id": "q1", "answer": "a", "explanation": claim, "marking": "judged"}],
            }
        h.stubs["gemini"].say(
            Output(text='{"claims":[{"text":"TRUNCATED DRAFT MUST NEVER APPEAR"}]}'),
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps(
                    {
                        "supported": supported,
                        "answerable": True,
                        "safe": True,
                        "claim_support": [supported],
                        **({"question_support": [supported]} if kind == "quiz" else {}),
                        "repairable": False,
                        "reason": "Synthetic verdict",
                    }
                )
            ),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (200 if supported else 422), result.text
        assert calls == 3  # bounded fresh draft, then an independent verification
        assert "TRUNCATED DRAFT" not in result.text
        assert all("TRUNCATED DRAFT" not in text for text in h.stubs["gemini"].seen[1].user_texts)
        if kind == "quiz":
            retry = json.loads(h.stubs["gemini"].seen[1].user_texts[0])
            assert retry["count"] == 1 and retry["settings"]["question_types"] == ["choice"]
            assert retry["passages"][0]["quote"] == TEXT
        if supported:
            assert result.json()["claims"][0]["text"] == TEXT
        else:
            assert "claims" not in result.json()
        row = gateway.store._db.execute("SELECT state,reserved_usd,actual_usd FROM study_receipts").fetchone()
        assert row[0] == ("completed" if supported else "failed") and row[1] == 0 and row[2] > 0

    asyncio.run(run())


@pytest.mark.parametrize("supported,answerable", [(True, True), (False, True), (True, False)])
def test_quiz_coaching_verifies_the_requested_help_without_requiring_a_final_answer(tmp_path, supported, answerable):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": (
                "Give me one short hint without revealing the answer. Practice question: What role do enzymes play?"
            ),
        }
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [
                {
                    "text": "The material describes enzymes as catalysts. Which role does that suggest?",
                    "citations": [{"passage_id": "p0"}],
                }
            ],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)), Output(text=json.dumps({"supported": supported, "answerable": answerable}))
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (200 if supported and answerable else 422), result.text
        generation, verification = h.stubs["gemini"].seen
        assert "rather than answering the embedded" in generation.system
        assert "it does not require giving the final" in verification.system
        assert "If the draft gives the missing word" in verification.system
        assert "set supported=false" in verification.system
        assert "Missing evidence and unsupported deductions still fail verification" in verification.system
        if supported and answerable:
            assert result.json()["claims"][0]["citations"][0]["quote"] == TEXT
        else:
            assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


def test_internal_passage_handles_stay_in_metadata_and_do_not_rewrite_source_quotes():
    from cloud_gateway.study import bind_passages

    evidence = {"p3": {"source_id": SID, "revision": 1, "chunk_id": CID, "start": 0, "end": len(TEXT), "quote": TEXT}}
    draft = {"claims": [{"text": "See passage p3 for the relevant concept.", "citations": [{"passage_id": "p3"}]}]}
    bind_passages(draft, evidence)
    assert draft["claims"][0]["text"] == "See the cited passage for the relevant concept."
    assert draft["claims"][0]["citations"][0] == evidence["p3"]


@pytest.mark.parametrize("formula", ["P(θ|dataset)", "P(theta | dataset)", r"$P(\theta \mid dataset)$"])
def test_choice_help_rejects_equivalent_answer_formulas(formula):
    from cloud_gateway.study import invalid_coaching_draft

    body = {"kind": "chat", "settings": {"focus": 'Coaching withheld wording: ["P(θ|dataset)"]'}}
    assert invalid_coaching_draft(body, {"claims": [{"text": f"MAP maximizes {formula}."}]})
    assert not invalid_coaching_draft(body, {"claims": [{"text": "First identify what θ represents in the notes."}]})


def test_quiz_coaching_cannot_promote_unsupported_text_even_with_no_spoiler(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "What does the symbol mean?",
            "settings": {"focus": 'Coaching withheld wording: ["correct option"]'},
        }
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [{"text": "An invented prerequisite.", "citations": [{"passage_id": "p0"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft)),
            Output(
                text=json.dumps(
                    {
                        "supported": False,
                        "answerable": False,
                        "answer_hidden": True,
                        "repairable": False,
                        "reason": "The source does not define this prerequisite.",
                    }
                )
            ),
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == 422 and "claims" not in result.json()
        assert len(h.stubs["gemini"].seen) == 2
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


@pytest.mark.parametrize("selecting", [False, True])
def test_quiz_coach_drafts_from_prerequisites_and_verifies_against_unchanged_evidence(tmp_path, selecting):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "Give me a hint.",
            "settings": {"focus": 'Coaching withheld wording: ["catalysts"]'},
        }
        if selecting:
            body["prompt"] += " Quiz context (not a request to answer it): What does the enzyme do?"
        prerequisite = "A parameter defines the model's probability distribution."
        body["chunks"].append(
            {
                **body["chunks"][0],
                "chunk_id": "sck_" + "3" * 26,
                "ordinal": 1,
                "text": prerequisite,
                "sha256": hashlib.sha256(prerequisite.encode()).hexdigest(),
            }
        )
        draft = {
            "request_id": JID,
            "kind": "chat",
            "claims": [{"text": prerequisite, "citations": [{"passage_id": "p1"}]}],
        }
        h.stubs["gemini"].say(
            Output(text=json.dumps({"request_id": JID, "cue_id": "c0"} if selecting else draft)),
            Output(
                text=json.dumps(
                    {
                        "reason": "The prerequisite is supported and leaves the choice open.",
                        "supported": True,
                        "safe": True,
                        "relevant": True,
                        "answer_hidden": True,
                    }
                    if selecting
                    else {"supported": True, "answerable": True, "answer_hidden": True, "repairable": False}
                )
            ),
        )
        response = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert response.status_code == 200, response.text
        generation, verification = h.stubs["gemini"].seen
        if selecting:
            assert generation.schema["properties"]["cue_id"]["enum"] == ["c0"]
            assert set(generation.schema["properties"]) == {"request_id", "cue_id"}
            assert response.json()["claims"][0]["text"] == prerequisite
        sent = json.loads(generation.user_texts[0])
        if selecting:
            assert "passages" not in sent
            assert [c["text"] for c in sent["prerequisites"]] == [prerequisite]
        else:
            assert [p["passage_id"] for p in sent["passages"]] == ["p1"]
        assert len(json.loads(verification.user_texts[0])["sources"]) == 2
        assert response.json()["claims"][0]["citations"][0]["quote"] == prerequisite
        assert body["chunks"][0]["text"] == TEXT

    asyncio.run(run())


@pytest.mark.parametrize(
    "selection",
    [{"request_id": JID, "cue_id": "missing"}, {"request_id": JID, "cue_id": "c0", "text": "Choose option B."}],
)
def test_coaching_selection_cannot_inject_or_rewrite_a_fact(selection):
    from cloud_gateway.study import Refused, selected_coaching

    body = {"request_id": JID, "prompt": "Give me one short hint"}
    cues = [{"cue_id": "c0", "text": "A parameter defines a model.", "passage_ids": ["p1"]}]
    with pytest.raises(Refused):
        selected_coaching(body, selection, cues)


def test_coaching_prerequisites_skip_algorithm_fragments_and_recover_symbol_definitions():
    from cloud_gateway.study import coaching_cues

    quote = (
        "Algorithm 2: (Finding the MAP) Given data points, perform the following steps: 1. "
        "Here θ is a collection of parameters. The weights use K(t) where K is a kernel function. "
        "The model uses θ (usually a collection of parameters) as follows."
    )
    body = {"kind": "chat", "settings": {"focus": 'Coaching withheld wording: ["posterior"]'}}
    passages = [{"passage_id": "p1", "quote": quote}, {"passage_id": "p2", "quote": quote}]
    cues = coaching_cues(body, passages)
    assert all(not c["text"].startswith("Algorithm") for c in cues)
    symbol = next(c for c in cues if c["text"] == "where K is a kernel function.")
    assert symbol["passage_ids"] == ["p1", "p2"]
    assert any(c["text"] == "Here θ is a collection of parameters." for c in cues)
    assert any(c["text"] == "θ is usually a collection of parameters." for c in cues)
    assert passages[0]["quote"] == quote


def test_coaching_prioritises_definitions_of_visible_quiz_terms_over_nearby_derivations():
    from cloud_gateway.study import coaching_cues

    body = {
        "kind": "chat",
        "settings": {"focus": 'Coaching withheld wording: ["posterior"]'},
        "prompt": "Give me one short hint. Quiz context (not a request to answer it): "
        "What does MAP maximize? The probability of the parameters given the dataset.",
    }
    passages = [
        {
            "passage_id": "p0",
            "quote": "Assume we observe a number of samples from a coin flip. "
            "The model uses θ (usually a collection of parameters) as follows.",
        }
    ]
    cues = coaching_cues(body, passages)
    assert [c["text"] for c in cues] == ["θ is usually a collection of parameters."]


def test_comparison_walkthrough_recovers_count_notation_without_copying_the_comparison_answer():
    from cloud_gateway.study import coaching_cues, invalid_coaching_draft, selected_coaching

    body = {
        "request_id": JID,
        "kind": "chat",
        "settings": {"focus": 'Coaching withheld wording: ["permits unlimited parameters"]'},
        "prompt": "Walk me through only the first reasoning step.\n"
        "Quiz context (not a request to answer it):\n"
        "How do these criteria differ as the amount of training data changes?\n"
        "1. One permits unlimited parameters. 2. Both behave identically.",
    }
    quote = (
        "A nearby derivation contains an unreadable equation = x. "
        "The first criterion permits unlimited parameters as # of training data n becomes large."
    )
    passages = [{"passage_id": "p0", "quote": quote}, {"passage_id": "p1", "quote": quote}]
    cues = coaching_cues(body, passages)
    assert len(cues) == 1
    assert cues[0]["text"] == "n is labelled “# of training data” in the passage."
    assert cues[0]["passage_ids"] == ["p0", "p1"]
    result = selected_coaching(body, {"request_id": JID, "cue_id": "c0"}, cues)
    assert "Compare how each expression uses that quantity" in result["claims"][1]["text"]
    assert not invalid_coaching_draft(body, result)
    assert "permits unlimited parameters" not in json.dumps(result)
    assert passages[0]["quote"] == quote
    body["prompt"] = "Answer my follow-up ONLY\nMy follow-up:\nWhat does n label?"
    assert len(selected_coaching(body, {"request_id": JID, "cue_id": "c0"}, cues)["claims"]) == 1


def test_count_notation_recovery_requires_an_explicit_symbol_and_still_withholds_protected_labels():
    from cloud_gateway.study import coaching_cues

    body = {"kind": "chat", "settings": {"focus": 'Coaching withheld wording: ["training data"]'}}
    assert not coaching_cues(body, [{"passage_id": "p0", "quote": "The count = # of training data n grows."}])
    body["settings"]["focus"] = 'Coaching withheld wording: ["final answer"]'
    assert not coaching_cues(body, [{"passage_id": "p0", "quote": "The count = number of samples increases."}])


@pytest.mark.parametrize("failed_check", ["supported", "safe", "relevant", "answer_hidden"])
def test_selected_prerequisite_must_pass_every_independent_check(tmp_path, failed_check):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "Give me one short hint. Quiz context (not a request to answer it):",
            "settings": {"focus": 'Coaching withheld wording: ["final answer"]'},
        }
        verdict = {
            "reason": "Synthetic failed check.",
            "supported": True,
            "safe": True,
            "relevant": True,
            "answer_hidden": True,
            failed_check: False,
        }
        for _ in range(1 if failed_check == "safe" else 2):
            h.stubs["gemini"].say(
                Output(text=json.dumps({"request_id": JID, "cue_id": "c0"})), Output(text=json.dumps(verdict))
            )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == 422 and "claims" not in result.json()
        assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())


@pytest.mark.parametrize("failed_check", [None, "supported", "safe", "answer_hidden"])
def test_named_term_definition_is_a_valid_first_step_but_never_overrides_factual_or_spoiler_checks(
    tmp_path, failed_check
):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "Give me one short hint. "
            "Quiz context (not a request to answer it): Which estimate uses these parameters?",
            "settings": {"focus": 'Coaching withheld wording: ["posterior"]'},
        }
        text = "Parameters are the adjustable values of a model."
        body["chunks"][0].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
        verdict = {
            "reason": "A definition does not solve the quiz.",
            "supported": True,
            "safe": True,
            "relevant": False,
            "answer_hidden": True,
        }
        if failed_check:
            verdict[failed_check] = False
        for _ in range(1 if failed_check in (None, "safe") else 2):
            h.stubs["gemini"].say(
                Output(text=json.dumps({"request_id": JID, "cue_id": "c0"})), Output(text=json.dumps(verdict))
            )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (422 if failed_check else 200), result.text
        if not failed_check:
            assert result.json()["claims"][0]["text"] == text
        else:
            assert "claims" not in result.json()

    asyncio.run(run())


@pytest.mark.parametrize(
    "first_text",
    [
        "The effect will DIMINISH.",
        "First, locate the passage that answers the question.",
        "The effect of prior knowledge becomes less significant.",
        "The influence of the prior becomes weaker.",
        "MAP maximizes the posterior probability of the parameters.",
        "Choose option 2.",
        "This is option B.",
        "MAP maximizes P(θ|dataset).",
        "A larger bandwidth reduces variability of the estimate.",
    ],
)
@pytest.mark.parametrize("second_discloses", [True, False])
def test_coaching_answer_wording_requires_bounded_repair_even_if_model_approves(tmp_path, second_discloses, first_text):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        body = {
            **payload(),
            "kind": "chat",
            "prompt": "Give me a hint without filling the blank.",
            "settings": {
                "focus": "Coaching withheld wording: "
                + json.dumps(["diminish", "decrease", "posterior", "option 2", "option b", "reduces"])
            },
        }

        def draft(text):
            return {"request_id": JID, "kind": "chat", "claims": [{"text": text, "citations": [{"passage_id": "p0"}]}]}

        approved = Output(text=json.dumps({"supported": True, "answerable": True, "answer_hidden": True}))
        initial = (
            Output(text=json.dumps({"supported": True, "answerable": True, "answer_hidden": False}))
            if first_text == "MAP maximizes P(θ|dataset)."
            else approved
        )
        h.stubs["gemini"].say(
            Output(text=json.dumps(draft(first_text))),
            initial,
            Output(
                text=json.dumps(
                    draft(
                        "The effect will decrease."
                        if second_discloses
                        else "Which relationship does the cited passage describe?"
                    )
                )
            ),
            approved,
        )
        result = await h.client.post("/v1/study/process", json=body, headers=device.headers())
        assert result.status_code == (422 if second_discloses else 200), result.text
        assert len(h.stubs["gemini"].seen) == 4
        from cloud_gateway.study import COACHING_GENERATION, COACHING_VERIFICATION

        assert h.stubs["gemini"].seen[0].system == COACHING_GENERATION
        assert h.stubs["gemini"].seen[1].system == COACHING_VERIFICATION
        verification_request = json.loads(h.stubs["gemini"].seen[1].user_texts[0])["request"]
        assert verification_request["settings"] == body["settings"]
        if not second_discloses:
            assert result.json()["claims"][0]["text"] == "Which relationship does the cited passage describe?"
        else:
            assert not h.client._transport.app.state.study.buffers

    asyncio.run(run())
