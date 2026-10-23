"""VOC-53, D130: the voice conversation lives in the open chats, Ask anything and a study set's Chat.

Each spoken question there is answered as its typed twin would be, under the same input guard; only the accepted
reply is spoken, and the answer reaches the UI as `voice.answer` once its audio starts (VOC-34)."""

import asyncio
from typing import Any

from agent_core.contracts import errors
from agent_core.engine.voice_place import OFFLINE, REST_ON_SCREEN, aid_spoken, parse_place, spoken_answer
from agent_core.engine.voice_bridge import VoiceProtocolError
from test_m31_voice_bridge import audio, event
from test_m32_adapter import body, contents, setup_adapter
from test_m32_provisional import SAFE

ADAPTER = {"authorization": "Bearer adapter-secret"}
SOURCE = "src_01JZ0000000000000000000001"


class FakeAskCloud:
    """Jana Online's Ask anything transport: one grounded reply from an allow-listed source."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def unavailable(self) -> str | None:
        return None

    async def ask(self, payload: dict[str, Any], _names: tuple[str, ...]) -> dict[str, Any]:
        self.asked.append(payload["question"])
        return {
            "sources": [{"ref": "w1", "url": "https://en.wikipedia.org/wiki/Photosynthesis", "title": "Photosynthesis",
                         "snippet": "Plants make sugar from light."}],  # fmt: skip
            "statements": [{"text": "Plants make their food from light, water and carbon dioxide.", "refs": ["w1"]}],
            "check_question": "What gas do plants take in?",
        }


class FakeDesk:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []

    def create_job(self, body: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(body)
        job = {"job_id": "stj_1", "state": "queued", "result_ids": [], "sources": body["sources"]}
        self.jobs["stj_1"] = job
        return dict(job)

    def job(self, jid: str) -> dict[str, Any]:
        return dict(self.jobs[jid])

    def aid(self, aid: str) -> dict[str, Any]:
        return {"aid_id": aid, "kind": "chat", "claims": [
            {"text": "Enzymes are biological catalysts.", "citations": [{"chunk_id": "c1"}]},
            {"text": "They speed up reactions without being used up.", "citations": [{"chunk_id": "c1"}]}]}  # fmt: skip

    def action(self, jid: str, _body: dict[str, Any]) -> dict[str, Any]:
        self.jobs[jid]["state"] = "cancelled"
        return self.jobs[jid]


class FakeStudy:
    """The study queue: grants checked, the chat job finished by the next poll."""

    def __init__(self) -> None:
        self.d = FakeDesk()
        self.grants: list[tuple[str, str, int | None]] = []

    def authorise(self, sid: str, grant: str = "", revision: int | None = None) -> dict[str, Any]:
        self.grants.append((sid, grant, revision))
        return {}

    def desk(self) -> FakeDesk:
        return self.d

    def poll(self) -> None:
        async def finish() -> None:
            await asyncio.sleep(0.05)
            self.d.jobs["stj_1"].update(state="completed", result_ids=["aid_01JZ0000000000000000000001"])

        asyncio.get_running_loop().create_task(finish())


def answers(core, sid):
    return [f["event"] for f in core._engine(core.sessions[sid]).events.frames if f["event"]["type"] == "voice.answer"]


async def heard(endpoint, socket, runtime, sid, core, response_id="resp_1"):
    """The reply's first audio plays, which releases the answer (VOC-34)."""
    before = len(answers(core, sid))
    await endpoint.incoming.put(audio(response_id))
    assert "bytes" in await socket.receive()
    async with asyncio.timeout(2):
        while len(answers(core, sid)) == before:
            await asyncio.sleep(0.01)
    return answers(core, sid)[-1]


def voc53_ask_place_routes(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        try:
            # A question in an installed subject spoken in Ask anything: a full tutor turn, every gate (D130, A).
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER, json=body(instructions))
            assert contents(reply) == SAFE and runtime.adapter.jobs and not runtime.adapter.chats
            answer = await heard(endpoint, socket, runtime, sid, core)
            assert answer["route"] == "tutor" and answer["place"] == "ask" and answer["text"] == SAFE
            assert answer["reply"] is None and errors("api/events#/$defs/ev_voice_answer", answer) == []
            assert core.sessions[sid].engine_state.transcript[-1]["content"] == SAFE
            await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
            await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            async with asyncio.timeout(2):
                while runtime.adapter.jobs:
                    await asyncio.sleep(0.01)
            # Any other question: Ask anything's grounded answer, spoken in short, shown in full.
            runtime.adapter.route = lambda _text: "ask"
            core.ask_cloud = cloud = FakeAskCloud()
            transcript = len(core.sessions[sid].engine_state.transcript)
            await endpoint.incoming.put(event("response.created", response={"id": "resp_2"}))
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER,
                                      json=body(instructions, "How do plants make food?"))  # fmt: skip
            spoken = contents(reply)
            assert cloud.asked == ["How do plants make food?"]
            assert spoken.startswith("Plants make their food from light") and "What gas do plants take in?" in spoken
            assert not runtime.adapter.jobs and runtime.adapter.chats
            answer = await heard(endpoint, socket, runtime, sid, core, "resp_2")
            assert answer["route"] == "ask" and answer["reply"]["state"] == "answered" and answer["text"] == spoken
            assert errors("api/events#/$defs/ev_voice_answer", answer) == []
            assert len(core.sessions[sid].engine_state.transcript) == transcript  # no tutor turn was made
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_voc53_ask_offline_speaks_the_stu20_line(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        runtime.adapter.route = lambda _text: "ask"
        try:
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER,
                                      json=body(instructions, "Who wrote Things Fall Apart?"))  # fmt: skip
            assert contents(reply) == OFFLINE  # no online plan: nothing is answered, the offline line is spoken
            answer = await heard(endpoint, socket, runtime, sid, core)
            assert answer["reply"]["state"] == "unavailable" and answer["reply"]["reason"] == "needs_online_plan"
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def voc53_study_place_chat(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, place=None)
        core.settings = core.settings.model_copy(update={"study_workspace_enabled": True})
        core.study = study = FakeStudy()
        try:
            await socket.send({"type": "place", "place": "study", "source_id": SOURCE, "revision": 2, "open": "grant"})
            async with asyncio.timeout(2):
                while runtime._active.place is None:
                    await asyncio.sleep(0)
            await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER,
                                      json=body(instructions, "What do enzymes do?"))  # fmt: skip
            spoken = contents(reply)
            assert spoken == "Enzymes are biological catalysts. They speed up reactions without being used up."
            assert study.grants == [(SOURCE, "grant", 2)]
            assert study.d.requests == [{"kind": "chat", "execution": "local", "prompt": "What do enzymes do?",
                                         "sources": [{"source_id": SOURCE, "revision": 2}]}]  # fmt: skip
            answer = await heard(endpoint, socket, runtime, sid, core)
            assert answer["place"] == "study" and answer["aid_id"] == "aid_01JZ0000000000000000000001"
            assert answer["route"] == "study" and answer["reply"] is None
            assert errors("api/events#/$defs/ev_voice_answer", answer) == []
            assert not core.sessions[sid].engine_state.transcript  # the tutor session is untouched
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def voc53_no_place_no_conversation(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, place=None)
        try:
            bridge = runtime._active.bridge
            assert runtime._active.place is None and not bridge.tutoring
            await socket.send({"type": "mode", "mode": "hands_free"})
            await socket.incoming.put({"type": "websocket.receive", "bytes": bytes(4800)})
            await asyncio.sleep(0.05)
            assert not any(e.get("type") == "input_audio_buffer.append" for e in list(endpoint.sent._queue))
            # A late sidecar request with this binding is not a turn (D130: no conversation on the tutor screen).
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER, json=body(instructions))
            assert contents(reply) == "" and not runtime.adapter.jobs and not runtime.adapter.chats
            assert not core.sessions[sid].engine_state.transcript
            # Naming the open chat offers the conversation; leaving it withdraws it again.
            await socket.send({"type": "place", "place": "ask"})
            async with asyncio.timeout(2):
                while not bridge.tutoring:
                    await asyncio.sleep(0)
            await socket.send({"type": "place", "place": None})
            async with asyncio.timeout(2):
                while bridge.tutoring:
                    await asyncio.sleep(0)
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def voc53_spoken_question_guarded(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        runtime.adapter.route = lambda _text: "ask"
        core.ask_cloud = cloud = FakeAskCloud()
        try:
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER,
                                      json=body(instructions, "How do I make a bomb at home?"))  # fmt: skip
            spoken = contents(reply)
            templates = core._engine(core.sessions[sid]).deps.templates
            assert spoken == templates.spoken("tpl.dangerous_request") and cloud.asked == []  # no model was asked
            answer = await heard(endpoint, socket, runtime, sid, core)
            assert answer["reply"] == {"route": "ask", "state": "failed", "reason": "safety_template", "answer": None}
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_voc53_distress_spoken_in_ask_shows_the_calm_screen_and_rests_voice(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        runtime.adapter.route = lambda _text: "ask"
        core.ask_cloud = cloud = FakeAskCloud()
        try:
            reply = await client.post("/v1/voice/llm/chat/completions", headers=ADAPTER,
                                      json=body(instructions, "I want to kill myself"))  # fmt: skip
            assert contents(reply) and cloud.asked == []
            frames = [f["event"] for f in core._engine(core.sessions[sid]).events.frames]
            assert any(e["type"] == "notice" and e.get("code") == "calm_screen" for e in frames)
            assert sid in runtime.calm_sessions and runtime._active.bridge.calm
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_voc53_places_and_spoken_forms():
    assert parse_place({"type": "place", "place": None}) is None
    assert parse_place({"type": "place", "place": "ask"}).kind == "ask"
    study = parse_place({"type": "place", "place": "study", "source_id": SOURCE, "revision": 1, "open": ""})
    assert (study.kind, study.source_id, study.revision) == ("study", SOURCE, 1)
    for bad in ({"type": "place", "place": "tutor"}, {"type": "place", "place": "study", "source_id": "x",
                                                         "revision": 1, "open": ""}):  # fmt: skip
        try:
            parse_place(bad)
        except VoiceProtocolError:
            continue
        raise AssertionError(bad)
    long = " ".join(["Plants grow towards the light."] * 30)
    spoken = spoken_answer([long])
    assert spoken.endswith(REST_ON_SCREEN) and len(spoken.split()) <= 80 + len(REST_ON_SCREEN.split())
    assert "$" not in spoken_answer([r"The area is $\pi r^2$."])
    assert aid_spoken({"claims": []}).startswith("Sorry")
