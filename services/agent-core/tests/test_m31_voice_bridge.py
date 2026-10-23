"""Synthetic Realtime recordings and binding isolation for the initial voice bridge slice."""

import base64
import copy

import pytest
from agent_core.contracts import errors
from agent_core.contracts.voice.engine_llm_adapter import Request
from agent_core.engine.voice_bindings import BindingRejected, VoiceBindings
from agent_core.engine.voice_bridge import MAX_PCM, VoiceBridge, VoiceProtocolError

TURN = "trn_01JZ0000000000000000000001"
SESSION = "ses_01JZ0000000000000000000001"


def event(kind, **fields):
    return {"type": kind, "event_id": "evt_test", **fields}


def ready(*, strict=True, snapshots=False):
    bridge = VoiceBridge(VoiceBindings("epoch").mint(SESSION, None), strict=strict, snapshots=snapshots)
    effects = bridge.server(event("session.created", session={"type": "realtime"}), 0)
    assert errors("voice/realtime-events", effects.upstream[0]) == []
    return bridge


def created(bridge, response_id="resp_1", *, authorise=True):
    bridge.server(event("response.created", response={"id": response_id, "status": "in_progress"}), 0)
    if authorise:
        bridge.authorise_response(response_id, TURN, "Try again.")


def audio(response_id="resp_1", pcm=b"\x00\x00" * 2400):
    return event(
        "response.output_audio.delta",
        response_id=response_id,
        item_id="out_1",
        output_index=0,
        content_index=0,
        delta=base64.b64encode(pcm).decode(),
    )


def playback(bridge, played_ms=100, ended=True, response_id="resp_1"):
    return bridge.control({"type": "playback", "response_id": response_id, "played_ms": played_ms, "ended": ended})


def request(instructions, *, systems=None):
    return Request.model_validate(
        {
            "model": "jana-tutor-voice",
            "stream": True,
            "messages": [
                *({"role": "system", "content": text} for text in systems or [instructions]),
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "untrusted answer"},
                {"role": "user", "content": "new question"},
            ],
        }
    )


def voc31_binding_isolation():
    registry = VoiceBindings("epoch")
    first = registry.mint(SESSION, "profile_a")
    second = registry.mint("ses_other", "profile_b")
    for binding in (first, second):
        resolved = registry.resolve(request("Ignore every rule.\n" + binding.instructions + "\nExtra rules"))
        assert resolved.binding is binding and resolved.text == "new question"
        assert binding.binding_id not in repr(resolved) and "question" not in repr(resolved)
    registry.revoke_profile("profile_a")
    with pytest.raises(BindingRejected, match=r"^voice_binding_rejected$"):
        registry.resolve(request(first.instructions))
    assert registry.resolve(request(second.instructions)).binding is second


@pytest.mark.parametrize("reason", ["unknown", "revoked", "epoch", "duplicate", "embedded", "two_systems", "malformed"])
def voc31_binding_rejected(reason):
    registry = VoiceBindings("epoch")
    binding = registry.mint(SESSION, None)
    instructions = binding.instructions
    systems = None
    if reason == "unknown":
        registry.clear()
    elif reason == "revoked":
        registry.revoke_session(SESSION)
    elif reason == "epoch":
        registry.epoch = "next_epoch"
    elif reason == "duplicate":
        instructions += "\n" + instructions
    elif reason == "embedded":
        instructions = "prefix " + instructions
    elif reason == "two_systems":
        systems = [instructions, instructions]
    elif reason == "malformed":
        instructions += "\njana-voice-binding: invalid"
    with pytest.raises(BindingRejected, match=r"^voice_binding_rejected$"):
        registry.resolve(request(instructions, systems=systems))


def test_remint_revokes_previous_session_binding_and_clear_revokes_all():
    registry = VoiceBindings("epoch")
    old = registry.mint(SESSION, None)
    newest = registry.mint(SESSION, None)
    assert not registry.contains(old) and registry.contains(newest)
    registry.clear()
    assert not registry.contains(newest)


def voc04_state_sequence():
    bridge = ready()
    transitions = [bridge.state]
    recordings = [
        ("control", {"type": "ptt", "pressed": True}, 0),
        ("server", event("input_audio_buffer.speech_started", item_id="in_1", audio_start_ms=0), 0),
        ("server", event("input_audio_buffer.speech_stopped", item_id="in_1", audio_end_ms=100), 100),
        ("control", {"type": "ptt", "pressed": False}, 100),
    ]
    all_effects = []
    for direction, frame, now in recordings:
        all_effects.append(bridge.control(frame) if direction == "control" else bridge.server(frame, now))
    assert bridge.tick(699).events == []
    all_effects.append(bridge.tick(700))
    created(bridge)
    all_effects.append(bridge.server(audio(), 701))
    all_effects.append(playback(bridge, played_ms=50, ended=False))
    all_effects.append(bridge.server(event("response.done", response={"id": "resp_1", "status": "completed"}), 702))
    assert bridge.state == "speaking"
    all_effects.append(playback(bridge))
    transitions.extend(e["state"] for fx in all_effects for e in fx.events if e["type"] == "voice.state")
    assert transitions == ["idle", "listening", "thinking", "speaking", "idle"]
    assert [a["type"] for fx in all_effects for a in fx.actions] == ["release", "playback_started", "complete"]
    for fx in all_effects:
        for e in fx.events:
            assert errors("api/events#/$defs/ev_voice_state", e) == []


def voc04_stale_events_ignored():
    bridge = ready()
    created(bridge, "old")
    created(bridge, "new")
    before = bridge.state
    assert bridge.server(audio("old"), 0).ui == []
    assert playback(bridge, response_id="old").events == []
    assert bridge.server(event("response.created", response={"id": "old"}), 0).events == []
    assert bridge.state == before
    bridge.close()
    assert bridge.server(audio("new"), 0).ui == []
    assert bridge.control({"type": "ptt", "pressed": True}).events == []
    assert bridge.tick(5000).events == []


def test_session_binding_precedes_audio_and_pcm_is_bounded():
    bridge = VoiceBridge(VoiceBindings("e").mint(SESSION, None))
    bridge.control({"type": "ptt", "pressed": True})
    assert bridge.microphone(b"\x00\x00").upstream == []
    config = bridge.server(event("session.created", session={"type": "realtime"}), 0).upstream
    assert config[0]["session"]["instructions"] == bridge.binding.instructions
    assert bridge.microphone(b"\x00\x00").upstream[0]["type"] == "input_audio_buffer.append"
    for pcm in (b"", b"x", b"\x00" * (MAX_PCM + 2)):
        with pytest.raises(VoiceProtocolError, match="invalid_pcm_frame"):
            bridge.microphone(pcm)


def test_tutor_audio_requires_explicit_accepted_response():
    bridge = ready()
    created(bridge, authorise=False)
    with pytest.raises(VoiceProtocolError, match="response_not_authorised"):
        bridge.server(audio(), 0)
    assert bridge.close().actions[0]["type"] == "discard"


def test_release_once_and_flush_correlates_with_binary_tag():
    bridge = ready()
    created(bridge)
    first = bridge.server(audio(), 0)
    assert first.actions == [{"type": "release", "response_id": "resp_1", "turn_id": TURN}]
    assert len(first.ui[0]) == 4816
    second = bridge.server(audio(), 0)
    assert second.actions == [] and first.ui[0][:16] == second.ui[0][:16]
    playback(bridge, 50, False)
    stopped = bridge.control({"type": "stop"})
    assert stopped.ui == [{"type": "flush", "response_id": "resp_1"}]
    assert stopped.actions[0]["type"] == "cancel" and stopped.actions[0]["played_ms"] == 50
    assert bridge.server(audio(), 0).ui == []


def voc11_cancel_idle_noop():
    bridge = ready()
    result = bridge.control({"type": "stop"})
    assert result.upstream == result.actions == result.events == result.ui == []
    assert bridge.state == "idle"


def test_stop_pending_turn_cancels_without_response_id():
    bridge = ready()
    bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms=0), 0)
    bridge.server(event("input_audio_buffer.speech_stopped", item_id="in", audio_end_ms=1), 1)
    result = bridge.control({"type": "stop"})
    assert result.upstream == [{"type": "response.cancel"}]
    assert result.actions[0]["type"] == "discard"
    assert bridge.control({"type": "stop"}).upstream == []


def test_pending_stop_ignores_late_response_creation_until_new_speech():
    bridge = ready()
    bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms=0), 0)
    bridge.server(event("input_audio_buffer.speech_stopped", item_id="in", audio_end_ms=1), 1)
    bridge.control({"type": "stop"})
    created(bridge, "late", authorise=False)
    assert bridge.server(audio("late"), 2).ui == []
    with pytest.raises(VoiceProtocolError, match="response_not_current"):
        bridge.authorise_response("late", TURN, "Try again.")
    bridge.server(event("input_audio_buffer.speech_started", item_id="next", audio_start_ms=3), 3)
    created(bridge, "new")
    assert bridge.server(audio("new"), 4).actions[0]["type"] == "release"


def test_closed_input_cannot_restart_thinking_from_late_stopped_event():
    bridge = ready()
    bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms=0), 0)
    stopped = event("input_audio_buffer.speech_stopped", item_id="in", audio_end_ms=1)
    bridge.server(stopped, 1)
    bridge.control({"type": "stop"})
    bridge.server(stopped, 2)
    assert bridge.tick(700).events == []


def voc11_no_self_trigger():
    bridge = ready()
    bridge.control({"type": "mode", "mode": "hands_free"})
    created(bridge)
    bridge.server(audio(), 0)
    assert bridge.microphone(b"\x00\x00").upstream == []
    assert bridge.server(event("input_audio_buffer.speech_started", item_id="echo", audio_start_ms=0), 0).actions == []
    cfg = bridge.control({"type": "capture", "echo_cancellation": True, "headphones": False})
    assert cfg.upstream[0]["session"]["audio"]["input"]["turn_detection"]["interrupt_response"]
    assert bridge.microphone(b"\x00\x00").upstream
    assert bridge.server(event("input_audio_buffer.speech_started", item_id="student", audio_start_ms=0), 0).actions


def voc09_committed_vs_tentative():
    bridge = ready(snapshots=True)
    bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms=0), 0)
    prefix = "conversation.item.input_audio_transcription."
    result = bridge.server(event(prefix + "delta", item_id="in", delta="two "), 0)
    assert result.events[0]["committed_text"] == "two "
    result = bridge.server(
        event("speech_to_speech.input_audio_transcription.snapshot", item_id="in", transcript="two plus"), 0
    )
    assert result.events[0]["tentative_text"] == "plus"
    result = bridge.server(
        event(prefix + "completed", item_id="in", content_index=0, transcript="two plus two", usage={}), 0
    )
    assert result.events[0]["committed_text"] == "two plus two" and result.events[0]["tentative_text"] == ""
    assert result.events[0]["final"]
    assert errors("api/events#/$defs/ev_voice_caption", result.events[0]) == []
    assert bridge.server(event(prefix + "delta", item_id="in", delta="late"), 0).events == []


def test_tutor_captions_are_buffered_until_audio_and_match_accepted_text():
    bridge = ready()
    created(bridge)
    transcript = event(
        "response.output_audio_transcript.done",
        response_id="resp_1",
        item_id="out",
        output_index=0,
        content_index=0,
        transcript="Try again.",
    )
    assert bridge.server(transcript, 0).events == []
    fx = bridge.server(audio(), 0)
    assert fx.events[0]["committed_text"] == "Try again."
    assert errors("api/events#/$defs/ev_voice_caption", fx.events[0]) == []
    transcript["transcript"] = "Unchecked answer."
    with pytest.raises(VoiceProtocolError, match="spoken_transcript_mismatch"):
        bridge.server(transcript, 0)


def test_completed_without_audio_discards_and_drain_is_not_generation_done():
    bridge = ready()
    created(bridge)
    fx = bridge.server(event("response.done", response={"id": "resp_1", "status": "completed"}), 0)
    assert fx.actions[0]["type"] == "discard" and bridge.state == "idle"
    assert bridge.server(audio(), 0).ui == []


def voc25_wire_subset():
    bridge = ready()
    frames = []
    for control in [
        {"type": "capture", "echo_cancellation": False, "headphones": True},
        {"type": "think", "pressed": True},
        {"type": "think", "pressed": False},
    ]:
        frames.extend(bridge.control(control).upstream)
    bridge.control({"type": "ptt", "pressed": True})
    frames.extend(bridge.microphone(b"\x00\x00").upstream)
    created(bridge)
    fx = bridge.server(
        event(
            "response.function_call_arguments.done",
            response_id="resp_1",
            item_id="out",
            output_index=0,
            call_id="call1",
            name="do_not_execute",
            arguments="private",
        ),
        0,
    )
    frames.extend(fx.upstream)
    frames.extend(bridge.control({"type": "stop"}).upstream)
    # Dictation and its Stop key use the same five client events: nothing outside the subset (VOC-46).
    dictation = ready()
    frames.extend(dictation.start_dictation("cap_01JZ0000000000000000000001", 0).upstream)
    frames.extend(dictation.microphone(b"\x00\x00").upstream)
    frames.extend(dictation.control({"type": "stop"}).upstream)
    reading = ready()
    frames.extend(reading.queue_read_aloud("utt_01JZ0000000000000000000001", None, "Read this.").upstream)
    assert frames
    assert {frame["type"] for frame in frames} <= {
        "input_audio_buffer.append",
        "session.update",
        "conversation.item.create",
        "response.create",
        "response.cancel",
    }
    for frame in frames:
        assert errors("voice/realtime-events", frame) == [], frame


def test_runtime_tolerates_unknown_fields_but_debug_is_strict():
    frame = event("response.created", response={"id": "r", "future": "ignored"}, future="ignored")
    tolerant = ready(strict=False)
    assert tolerant.server(frame, 0).diagnostics == ["unknown_field"]
    assert tolerant.server(frame, 0).diagnostics == []
    with pytest.raises(VoiceProtocolError, match="invalid_realtime_frame"):
        ready().server(frame, 0)
    bridge = ready()
    unknown = {"type": "endpoint-secret-new-event", "secret": "not logged"}
    assert bridge.server(unknown, 0).diagnostics == ["unknown_event"]
    assert bridge.server(copy.deepcopy(unknown), 0).diagnostics == []


def voc06_hold_to_think():
    bridge = ready()
    bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms=0), 0)
    bridge.server(event("input_audio_buffer.speech_stopped", item_id="in", audio_end_ms=1), 1)
    fx = bridge.control({"type": "think", "pressed": True})
    configured = next(frame for frame in fx.upstream if frame["type"] == "session.update")
    assert configured["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 10000
    assert bridge.tick(5000).events == []
    bridge.control({"type": "think", "pressed": False})
    assert bridge.tick(5001).events[0]["state"] == "thinking"


def test_runtime_does_not_coerce_invalid_known_fields():
    bridge = ready(strict=False)
    with pytest.raises(VoiceProtocolError, match="invalid_realtime_frame"):
        bridge.server(event("input_audio_buffer.speech_started", item_id="in", audio_start_ms="0"), 0)


@pytest.mark.parametrize(
    "control",
    [
        {"type": "ptt", "pressed": 1},
        {"type": "mode", "mode": "other"},
        {"type": "playback", "played_ms": -1},
        {"type": "speak", "utterance_id": "x"},
    ],
)
def test_invalid_controls_are_reason_only(control):
    with pytest.raises(VoiceProtocolError, match=r"^(unsupported_control|invalid_playback)$"):
        ready().control(control)


def voc06_push_to_talk_release():
    bridge = ready()
    bridge.control({"type": "ptt", "pressed": True})
    effects = bridge.control({"type": "ptt", "pressed": False})
    assert len(effects.upstream) == 4
    assert all(frame["type"] == "input_audio_buffer.append" for frame in effects.upstream)
    assert all(base64.b64decode(frame["audio"]) == bytes(MAX_PCM) for frame in effects.upstream)
    assert not bridge.control({"type": "ptt", "pressed": False}).upstream


def _silence(effects):
    """The trailing silence a key-up sends, in ms, and the silence_duration_ms last configured (if any)."""
    appended = [f for f in effects.upstream if f["type"] == "input_audio_buffer.append"]
    return sum(len(base64.b64decode(f["audio"])) for f in appended) * 1000 // 48_000


def _configured(effects):
    updates = [f for f in effects.upstream if f["type"] == "session.update"]
    return updates[-1]["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] if updates else None


def test_voc05_push_to_talk_release_outlasts_the_thinking_extension():
    """After a turn that awaits worked input the VAD waits the thinking extension; key-up ends capture, so its
    trailing silence must outlast that pause or the utterance never ends and is never transcribed."""
    bridge = ready()
    assert _configured(bridge.await_work(True)) == 1200
    bridge.control({"type": "ptt", "pressed": True})
    assert _silence(bridge.control({"type": "ptt", "pressed": False})) > 1200
    bridge.control({"type": "think", "pressed": True})
    bridge.control({"type": "ptt", "pressed": True})
    assert _silence(bridge.control({"type": "ptt", "pressed": False})) == 400  # the held think key keeps waiting


@pytest.mark.parametrize("mode", ["push_to_talk", "hands_free"])
def test_bridge_forwards_audio_and_transcripts_on_every_turn(mode):
    """Speech reaches the endpoint and its transcript reaches the student on the first turn and on the turn after an
    answer that awaits worked input (the 2026-10-22 regression: the second push-to-talk utterance was never heard)."""
    bridge = ready()
    bridge.control({"type": "mode", "mode": mode})
    prefix = "conversation.item.input_audio_transcription."
    pcm = b"\x01\x00" * 2400
    now = 0
    for turn, words in enumerate(["what is kinetic energy", "half m v squared"]):
        item = f"in_{turn}"
        if mode == "push_to_talk":
            bridge.control({"type": "ptt", "pressed": True})
        forwarded = bridge.microphone(pcm).upstream
        assert [f["type"] for f in forwarded] == ["input_audio_buffer.append"]
        assert base64.b64decode(forwarded[0]["audio"]) == pcm
        bridge.server(event("input_audio_buffer.speech_started", item_id=item, audio_start_ms=now), now)
        if mode == "push_to_talk":
            assert _silence(bridge.control({"type": "ptt", "pressed": False})) > (1200 if turn else 160)
        now += 100
        bridge.server(event("input_audio_buffer.speech_stopped", item_id=item, audio_end_ms=now), now)
        bridge.server(event(prefix + "delta", item_id=item, delta=words.split()[0] + " "), now)
        done = bridge.server(event(prefix + "completed", item_id=item, content_index=0, transcript=words, usage={}),
                             now)  # fmt: skip
        caption = next(e for e in done.events if e["type"] == "voice.caption")
        assert caption["speaker"] == "student" and caption["final"] and caption["committed_text"] == words
        now += 700
        bridge.tick(now)
        response = f"resp_{turn}"
        created(bridge, response, authorise=False)
        bridge.authorise_response(response, TURN, "Try again.")
        bridge.server(audio(response), now)
        bridge.server(event("response.done", response={"id": response, "status": "completed"}), now)
        playback(bridge, response_id=response)
        bridge.await_work(True)  # the tutor's answer asks the student for worked input
        now += 2000
        bridge.tick(now)


def test_push_to_talk_interrupts_playback_even_without_echo_cancellation():
    bridge = ready()
    created(bridge)
    bridge.server(audio(), 0)
    assert not bridge.echo_safe
    effects = bridge.control({"type": "ptt", "pressed": True})
    assert effects.actions[0]["type"] == "cancel" and effects.actions[0]["ended_by"] == "barge_in"
    assert effects.ui == [{"type": "flush", "response_id": "resp_1"}]
    assert bridge.microphone(bytes(960)).upstream


def test_hold_to_think_discards_a_speculative_response_before_audio():
    bridge = ready()
    created(bridge)
    effects = bridge.control({"type": "think", "pressed": True})
    assert effects.actions[0]["type"] == "discard"
    assert effects.upstream[0]["type"] == "response.cancel"
    assert effects.upstream[1]["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 10000


def test_authorization_can_wait_for_upstream_response_created():
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    bridge.authorise_turn(TURN, "Try again.")
    created(bridge, authorise=False)
    assert bridge.server(audio(), 0).actions[0]["type"] == "release"


def test_response_created_can_race_with_the_accepted_candidate():
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    created(bridge, authorise=False)
    bridge.authorise_turn(TURN, "Try again.")
    assert bridge.server(audio(), 0).actions[0]["type"] == "release"


def test_stop_revokes_pending_authorization_and_old_callbacks_cannot_rebind():
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    bridge.authorise_turn(TURN, "Try again.")
    assert bridge.control({"type": "stop"}).actions[0]["type"] == "discard"
    created(bridge, authorise=False)
    assert not bridge.server(audio(), 0).ui
    assert not bridge.begin_provisional(TURN)
    bridge.control({"type": "ptt", "pressed": True})
    fresh = TURN[:-1] + "2"
    assert bridge.begin_provisional(fresh)
    with pytest.raises(VoiceProtocolError, match="voice_turn_not_current"):
        bridge.authorise_turn(TURN, "Try again.")
    bridge.authorise_turn(fresh, "Try again.")
    created(bridge, response_id="resp_2", authorise=False)
    assert not bridge.server(audio(), 0).ui
    assert bridge.server(audio(response_id="resp_2"), 0).actions[0]["turn_id"] == fresh


def test_hold_revokes_pending_authorization_before_a_response_id_exists():
    bridge = ready()
    assert bridge.begin_provisional(TURN)
    bridge.authorise_turn(TURN, "Try again.")
    assert bridge.control({"type": "think", "pressed": True}).actions[0]["type"] == "discard"
    with pytest.raises(VoiceProtocolError, match="voice_turn_not_current"):
        bridge.authorise_turn(TURN, "Try again.")
