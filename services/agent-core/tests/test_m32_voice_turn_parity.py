"""A spoken turn runs the typed turn's whole path, post-turn steps included (VOC-32, MEM-06)."""

import asyncio

import pytest
from test_m31_voice_bridge import audio, event
from test_m32_adapter import body, contents, setup_adapter
from test_m32_provisional import SAFE

QUESTION = "Could you explain that?"


class Reflector:
    def __init__(self):
        self.calls = []

    def pause(self):
        self.calls.append("pause")
        return False

    def activity(self):
        self.calls.append("activity")

    def trigger(self, point, *args, **kwargs):
        self.calls.append(point)
        return True


class Records:
    """Records only what the post-turn path asks for; the voice adapter also reports its turns and delivery."""

    def __init__(self):
        self.calls, self.voice_turns = [], set()

    def touch(self, meta, now, *, solved=False):
        self.calls.append("touch")

    def solved(self, session_id):
        self.calls.append("solved")

    def voice_delivery(self, *args):
        self.calls.append("delivery")

    def learning(self, events):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def board(state):
    """The board as the student sees it: ids are minted per session."""
    steps = [(s.index, s.latex, s.reason, s.owner, s.status, s.check_id) for s in state.board.steps]
    return steps, state.board.knowns, state.board.unknowns


def gates(core, sid):
    engine = core._engine(core.sessions[sid])
    return [(g["gate"], g["outcome"]) for record in engine.traces for g in record["gates"]
            if not g["gate"].startswith(("voice_", "verbaliser_"))]  # fmt: skip


async def typed(tmp_path):
    core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path)
    core.reflector, core.records, core.records_profile = Reflector(), Records(), None
    try:
        core.start_turn(sid, {"client_message_id": "cli_01JZ0000000000000000000009", "intent": "answer",
                              "content": [{"type": "text", "text": QUESTION}]})  # fmt: skip
        await asyncio.wait_for(core.sessions[sid].task, 10)
        return core, sid
    finally:
        await socket.close()
        await runtime.close()
        await client.aclose()


async def spoken(tmp_path, *, solve=False):
    core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
    core.reflector, core.records, core.records_profile = Reflector(), Records(), None
    try:
        response = await client.post("/v1/voice/llm/chat/completions",
                                     headers={"authorization": "Bearer adapter-secret"},
                                     json=body(instructions, QUESTION))  # fmt: skip
        assert contents(response) == SAFE
        job = next(iter(runtime.adapter.jobs.values()))
        if solve:
            job.turn.engine.state.solved = True  # a turn that solves the problem ends it (MEM-06)
        await endpoint.incoming.put(audio())
        assert "bytes" in await socket.receive()
        await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
        await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
        async with asyncio.timeout(3):
            while runtime.adapter.jobs:
                await asyncio.sleep(0.01)
        return core, sid
    finally:
        await socket.close()
        await runtime.close()
        await client.aclose()


def voc32_voice_equals_typed(tmp_path):
    async def scenario():
        typed_core, typed_sid = await typed(tmp_path / "typed")
        voice_core, voice_sid = await spoken(tmp_path / "voice")
        typed_state = typed_core.sessions[typed_sid].engine_state
        voice_state = voice_core.sessions[voice_sid].engine_state
        assert board(voice_state) == board(typed_state)
        assert gates(voice_core, voice_sid) == gates(typed_core, typed_sid)
        assert [r["content"] for r in voice_state.transcript] == [r["content"] for r in typed_state.transcript]
        for core, sid in ((typed_core, typed_sid), (voice_core, voice_sid)):
            frames = core._engine(core.sessions[sid]).events.frames
            titles = [f["event"]["title"] for f in frames if f["event"]["type"] == "session.updated"]
            assert titles == [QUESTION]
            assert "touch" in core.records.calls
            assert core.reflector.calls[0] == "pause" and core.reflector.calls[-1] == "activity"

    asyncio.run(scenario())


@pytest.mark.parametrize("solve", [False, True])
def test_spoken_turn_that_solves_the_problem_ends_it_like_a_typed_turn(tmp_path, solve):
    async def scenario():
        core, _ = await spoken(tmp_path, solve=solve)
        assert ("solved" in core.records.calls) is solve
        assert ("problem_end" in core.reflector.calls) is solve

    asyncio.run(scenario())


def test_voc12_one_honest_filler_plays_before_acceptance_and_never_releases_the_turn(tmp_path):
    import json

    from agent_core.api.voice_adapter import FILLERS
    from agent_core.contracts.voice.engine_llm_adapter import Request as AdapterRequest
    from engine_harness import tutor

    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(
            tmp_path, replies=[{"stall_s": 0.6, **tutor(SAFE)}]
        )
        core.settings = core.settings.model_copy(update={"voice_filler_after_ms": 50})
        runtime.adapter.keep_alive_s = 0.02
        stream = runtime.adapter.stream(AdapterRequest.model_validate(body(instructions, QUESTION)))
        try:
            lines = [await anext(stream)]
            while ": keep-alive" in lines[-1]:
                lines.append(await anext(stream))
            first = json.loads(lines[-1][6:])
            assert first["choices"][0]["delta"]["content"].strip() == FILLERS[0]
            job = next(iter(runtime.adapter.jobs.values()))
            await endpoint.incoming.put(audio())  # the filler's audio plays...
            assert "bytes" in await socket.receive()
            assert not job.turn.released and not core.sessions[sid].engine_state.transcript  # ...but releases nothing
            rest = [line async for line in stream]
            spoken = "".join(json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                             for line in rest if line.startswith("data: {"))  # fmt: skip
            assert spoken == SAFE and sum(FILLERS[0] in line for line in [*lines, *rest]) == 1
            await endpoint.incoming.put(audio())  # first audio of the accepted turn releases it (VOC-34)
            assert "bytes" in await socket.receive()
            async with asyncio.timeout(2):
                while not job.turn.released:
                    await asyncio.sleep(0.01)
            assert core.sessions[sid].engine_state.transcript[-1]["content"] == SAFE
        finally:
            await stream.aclose()
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def silences(endpoint):
    found = []
    while not endpoint.sent.empty():
        frame = endpoint.sent.get_nowait()
        if frame["type"] == "session.update":
            found.append(frame["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"])
    return found


def test_voc05_thinking_extension_while_the_tutor_awaits_worked_input(tmp_path):
    """After a turn that expects the student's answer the bridge sends the thinking extension; the next turn's start
    restores the normal silence. Both values are the named configuration keys."""
    from agent_core.config import Settings

    settings = Settings()

    async def scenario():
        _, _, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        try:
            response = await client.post("/v1/voice/llm/chat/completions",
                                         headers={"authorization": "Bearer adapter-secret"},
                                         json=body(instructions, QUESTION))  # fmt: skip
            assert contents(response) == SAFE
            silences(endpoint)
            await endpoint.incoming.put(audio())
            assert "bytes" in await socket.receive()
            await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
            await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            seen = []
            async with asyncio.timeout(3):
                while settings.voice_thinking_extension_ms not in seen:
                    seen += silences(endpoint)
                    await asyncio.sleep(0.01)
            assert runtime._active.bridge.awaiting_work
            await endpoint.incoming.put(event("response.created", response={"id": "resp_2"}))
            response = await client.post("/v1/voice/llm/chat/completions",
                                         headers={"authorization": "Bearer adapter-secret"},
                                         json=body(instructions, "So the answer is ten?"))  # fmt: skip
            seen = []
            async with asyncio.timeout(3):
                while settings.voice_silence_ms not in seen:
                    seen += silences(endpoint)
                    await asyncio.sleep(0.01)
            assert not runtime._active.bridge.awaiting_work
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())
