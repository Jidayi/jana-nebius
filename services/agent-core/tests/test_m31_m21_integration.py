"""The real M21 SQLite repository is the boundary between reviewed dictation and explicit Send."""

import asyncio

from agent_core.api.drafts import clean_document
from agent_core.contracts import errors
from agent_core.engine.events import new_id
from agent_core.store.checkpoints import CheckpointStore
from agent_core.store.sqlite import open_database
from test_m31_voice_activities import headers
from test_m32_adapter import setup_adapter


def test_confirmed_dictation_is_persisted_then_sent_by_capture_id(tmp_path):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn, _ = open_database(tmp_path / "captures.db", "learner")
        core.store = CheckpointStore(conn)
        core.persist(core.sessions[sid])
        try:
            created = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "answer"},
            )
            assert created.status_code == 200, created.text
            identity = created.json()["capture_id"]
            runtime.activities.transcript(runtime._active.bridge.binding, identity, "Could you explain this?")
            assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
            assert (await client.get(f"/v1/captures/{identity}", headers=headers())).status_code == 404
            request = {
                "client_message_id": new_id("cli"),
                "intent": "answer",
                "capture_id": identity,
                "content": [{"type": "text", "text": "UNTRUSTED replacement"}],
            }
            refused = await client.post(f"/v1/sessions/{sid}/turns", headers=headers(), json=request)
            assert refused.status_code == 404 and not core.sessions[sid].state["messages"]
            edited = "Could you explain that?"
            confirmed = await client.post(
                f"/v1/sessions/{sid}/voice/dictations/{identity}/confirm",
                headers=headers(),
                json={"type": "confirm_dictation", "text": edited},
            )
            assert confirmed.status_code == 200, confirmed.text
            assert not errors("input/captured-question", confirmed.json())
            assert conn.execute("SELECT session_id FROM captures").fetchone()[0] == sid[4:]
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
            stored = await client.get(f"/v1/captures/{identity}", headers=headers())
            assert stored.json() == confirmed.json()
            listed = await client.get(f"/v1/sessions/{sid}/captures", headers=headers())
            assert listed.json()["captures"] == [confirmed.json()]
            assert not core.sessions[sid].state["messages"] and not runtime.adapter.jobs
            engine = core._engine(core.sessions[sid])
            original = engine.student_turn
            sources = []

            async def observed(*args, **kwargs):
                sources.append(kwargs["source"])
                return await original(*args, **kwargs)

            engine.student_turn = observed
            sent = await client.post(f"/v1/sessions/{sid}/turns", headers=headers(), json=request)
            assert sent.status_code == 202, sent.text
            await core.sessions[sid].task
            assert sources == ["student_text"]
            student = next(m for m in core.sessions[sid].state["messages"] if m["role"] == "student")
            assert student["content"] == [{"type": "text", "text": edited}]
            # Voice transport shutdown discards volatile drafts, not confirmed M21 captures.
            await runtime.close()
            assert (await client.get(f"/v1/captures/{identity}", headers=headers())).json()["text"] == edited
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            await core.capture_desk.close()
            conn.close()

    asyncio.run(scenario())


def test_saved_dictation_highlight_keeps_only_the_fixed_safe_mark():
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "uncertain",
                        "marks": [
                            {"type": "dictationUncertain"},
                            {"type": "link", "attrs": {"href": "javascript:alert(1)"}},
                        ],
                    },
                ],
            }
        ],
    }
    text = clean_document(document)["content"][0]["content"][0]
    assert text == {"type": "text", "text": "uncertain", "marks": [{"type": "dictationUncertain"}]}
