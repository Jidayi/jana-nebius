"""Heard text follows the sidecar's output transcript aligned with the audio played (VOC-36)."""

import asyncio
import json

from agent_core.engine.voice_turn import ProvisionalVoiceTurn
from test_m31_voice_bridge import TURN, audio, created, event, ready
from test_m32_provisional import SAFE, prepared

SPOKEN = "One two. Three four."


def transcript(delta, response_id="resp_1"):
    return event("response.output_audio_transcript.delta", response_id=response_id, item_id="out_1",
                 output_index=0, content_index=0, delta=delta)  # fmt: skip


def test_barge_in_reports_the_transcript_prefix_whose_audio_fully_played():
    bridge = ready()
    created(bridge, authorise=False)
    bridge.authorise_response("resp_1", TURN, SPOKEN)
    bridge.server(transcript("One two."), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 2400), 0)  # 100 ms
    bridge.server(transcript(" Three four."), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 2400), 0)
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 150, "ended": False})
    effects = bridge.control({"type": "stop"})
    cancel = next(action for action in effects.actions if action["type"] == "cancel")
    assert cancel["heard_chars"] == len("One two.")


def test_without_transcript_deltas_the_estimate_is_used():
    bridge = ready()
    created(bridge)
    bridge.server(audio(), 0)
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 50, "ended": False})
    cancel = next(a for a in bridge.control({"type": "stop"}).actions if a["type"] == "cancel")
    assert cancel["heard_chars"] is None


def test_filler_audio_never_releases_and_is_not_counted_as_heard_turn_audio():
    """VOC-12: a stop during the filler discards the unaccepted turn; once released, played time excludes it."""
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    created(bridge, authorise=False)
    bridge.authorise_filler(TURN, "Let me work that out.")
    effects = bridge.server(audio(), 0)  # 100 ms of filler
    assert effects.ui and not effects.actions
    stop = bridge.control({"type": "stop"})
    assert [a["type"] for a in stop.actions] == ["discard"]

    bridge = ready()
    assert bridge.begin_provisional(TURN)
    created(bridge, authorise=False)
    bridge.authorise_filler(TURN, "Let me work that out.")
    bridge.server(audio(), 0)
    bridge.authorise_turn(TURN, "Try again.")
    assert [a["type"] for a in bridge.server(audio(), 0).actions] == ["release"]
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 150, "ended": False})
    cancel = next(a for a in bridge.control({"type": "stop"}).actions if a["type"] == "cancel")
    assert cancel["played_ms"] == 50 and cancel["total_ms"] == 100


def test_filler_streamed_before_the_response_exists_survives_an_early_acceptance():
    """VOC-12: the filler and the accepted text can both be authorised before the endpoint names its response; the
    adapter has already streamed the filler ahead of the text, so its transcript must not read as a mismatch."""
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    bridge.authorise_filler(TURN, "Let me work that out.")
    bridge.authorise_turn(TURN, SPOKEN)
    created(bridge, authorise=False)
    bridge.server(transcript("Let me work that out."), 0)
    bridge.server(transcript(" One two."), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 2400), 0)
    bridge.server(transcript(" Three four."), 0)
    done = event("response.output_audio_transcript.done", response_id="resp_1", item_id="out_1", output_index=0,
                 content_index=0, transcript="Let me work that out. " + SPOKEN)  # fmt: skip
    bridge.server(done, 0)
    assert bridge._response is not None and bridge._response.caption == SPOKEN and bridge._response.caption_final


def test_turn_latency_metadata_is_parsed_as_timings_only():
    from agent_core.engine.voice_bridge import turn_latency

    metadata = {"speech_to_speech.turn_latency": json.dumps(
        {"e2e_s": 1.5, "stt_s": 0.25, "llm_s": -1, "tts_ttfa_s": "nan", "smart_status": "complete",
         "transcript": "private words"})}  # fmt: skip
    assert turn_latency(metadata) == {"e2e_s": 1.5, "stt_s": 0.25, "smart_status": "complete"}
    assert turn_latency({"speech_to_speech.turn_latency.hold_s": "0.4"}) == {"hold_s": 0.4}
    assert turn_latency({"speech_to_speech.turn_latency": "not json"}) == {} and turn_latency(None) == {}


def test_voc22_voice_trace_records_upstream_latency_and_playback_start(tmp_path):
    from agent_core.contracts import errors
    from test_m32_adapter import body, contents, setup_adapter

    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        try:
            response = await client.post("/v1/voice/llm/chat/completions",
                                         headers={"authorization": "Bearer adapter-secret"},
                                         json=body(instructions))  # fmt: skip
            assert contents(response) == SAFE
            await endpoint.incoming.put(audio())
            assert "bytes" in await socket.receive()
            metadata = {"speech_to_speech.turn_latency": json.dumps({"e2e_s": 1.5, "stt_s": 0.25})}
            await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed",
                                                                         "metadata": metadata}))  # fmt: skip
            await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            async with asyncio.timeout(3):
                while runtime.adapter.jobs:
                    await asyncio.sleep(0.01)
            records = [r for r in core._engine(core.sessions[sid]).traces if r.get("turn_source") == "voice"]
            latency = records[-1]["voice"]["latency"]
            assert latency["e2e_s"] == 1.5 and latency["stt_s"] == 0.25
            assert {"adapter_first_sentence_ms", "release_ms", "playback_start_ms"} <= set(latency)
            assert errors("trace/turn-trace", records[-1]) == []
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_heard_text_from_the_transcript_never_counts_a_half_played_word(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path)
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        await provisional.evaluate()
        engine = provisional.release(live.events)
        cut = SAFE.index("does") + 2  # the transcript reached the middle of "does"
        provisional.finish(interrupted=True, played_ms=900, heard_chars=cut)
        assert engine.state.transcript[-1]["heard_text"] == SAFE[: SAFE.index(" does")]
        assert engine.voice_interruption == SAFE[: SAFE.index(" does")]

    asyncio.run(scenario())
