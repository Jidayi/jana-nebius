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
                        "text": "What value does the source give for Δx/Δt?",
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
            (422, "support_check"),
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

        cards = [{"front": claim("What value is given for v?"), "back": claim("v = 2.5 m/s.")}]
        for attempt, supported, wording in [
            (1, False, "The velocity is 2.5 m/s."),
            (2, True, "The source gives v = Δx/Δt = 2.5 m/s."),
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
        assert receipts == [(422, "support_check"), (200, "completed")]

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
