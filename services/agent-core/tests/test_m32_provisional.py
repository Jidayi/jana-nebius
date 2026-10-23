"""Real engine evaluation, isolated state and deferred effects for speculative voice."""

import asyncio
import copy
from dataclasses import replace
from fractions import Fraction

import pytest
from agent_core.contracts import errors
from agent_core.engine.assembly import assemble
from agent_core.engine.state import Plan, PlanStep, Problem, state_to_json
from agent_core.engine.voice_turn import ProvisionalVoiceTurn, VoiceTurnConflict
from engine_harness import make_engine, tutor
from jana_tools import REPO_ROOT

SAFE = "What quantity does the question ask you to find?"


async def prepared(tmp_path, replies=None):
    live, provider = await make_engine(tmp_path, {"coach": replies or [tutor(SAFE)]}, worker=False)
    live.state.problem = Problem("prb_test", "Find the height of a ball thrown at 14 m/s.", "prb_test#statement")
    live.state.plan = Plan([PlanStep(1, "h = 10", "10", "m", "chk_test")], "10", "m", "chk_test")
    live.state.check_values = {"chk_test": [Fraction(10)]}

    def factory(state):
        return assemble(
            {"local": provider},
            live.deps.settings,
            state,
            REPO_ROOT / "content" / "agent",
            REPO_ROOT / "skills",
            tmp_path / "spill",
            None,
        )

    return live, factory


def voc35_discard_no_side_effects(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path)
        before = state_to_json(live.state)
        frames, learning, saves, traces = [], [], [], []
        live.events.sink = frames.append
        live.learning = learning.extend
        live.on_memory_request = lambda *_: saves.append("memory")
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        await provisional.evaluate()
        assert provisional.spoken_text == SAFE
        assert provisional.events.frames and provisional.result.tutor_turn is not None
        ref = provisional.engine.deps.executor.spill.save(live.state.session_id, "speculative tool output")
        assert provisional.engine.deps.executor.spill.resolve(live.state.session_id, ref) == "speculative tool output"
        assert not (tmp_path / "spill").exists()
        assert state_to_json(live.state) == before and not frames and not learning and not saves and not traces
        await provisional.discard()
        assert not provisional.events.frames and state_to_json(live.state) == before and not live.persisted

    asyncio.run(scenario())


def voc34_release_on_first_audio(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path)
        frames = []
        live.events.sink = frames.append
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        await provisional.evaluate()
        expected = [e["event"] for e in provisional.events.frames if e["event"]["type"] != "turn.end"]
        assert not frames
        engine = provisional.release(live.events)
        assert [e["event"] for e in frames] == expected
        assert engine.state.transcript[-1]["content"] == SAFE
        assert not any(e["event"]["type"] == "turn.end" for e in frames)
        provisional.finish(played_ms=1000)
        assert frames[-1]["event"]["type"] == "turn.end"
        assert engine.state.transcript[-1]["heard_text"] == SAFE
        with pytest.raises(VoiceTurnConflict):
            provisional.release(live.events)

    asyncio.run(scenario())


def test_revision_conflict_rejects_stale_commit(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path)
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        await provisional.evaluate()
        live.state.mode = "revision"
        with pytest.raises(VoiceTurnConflict, match="voice_state_changed"):
            provisional.release(live.events)
        await provisional.discard()
        assert not live.events.frames and live.state.mode == "revision"

    asyncio.run(scenario())


def ped26_barge_in_accepted_ops_only(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path)
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        await provisional.evaluate()
        engine = provisional.release(live.events)
        state = copy.deepcopy(engine.state.board)
        provisional.finish(interrupted=True, played_ms=0)
        assert engine.state.board == state
        assert engine.state.transcript[-1]["heard_text"] == ""
        ends = [e["event"] for e in engine.events.frames if e["event"]["type"] == "turn.end"]
        assert len(ends) == 1 and ends[0]["status"] == "interrupted"
        assert engine.voice_interruption == ""

    asyncio.run(scenario())


def test_discard_cancels_inflight_model_call(tmp_path):
    async def scenario():
        live, factory = await prepared(tmp_path, [{"stall_s": 30, **tutor(SAFE)}])
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        evaluation = asyncio.create_task(provisional.evaluate())
        await asyncio.sleep(0.03)
        await provisional.discard()
        await asyncio.gather(evaluation, return_exceptions=True)
        assert provisional.task.done() and not live.events.frames and not live.state.transcript

    asyncio.run(scenario())


@pytest.mark.parametrize("discarded", [False, True])
def test_voice_trace_has_only_available_phase_timings_and_no_transcript(tmp_path, discarded):
    async def scenario():
        live, factory = await prepared(tmp_path)
        records = []
        live.deps = replace(live.deps, trace_sink=records.append)
        provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
        provisional.talk_mode = "hands_free"
        await provisional.evaluate()
        assert not records
        if discarded:
            await provisional.discard()
        else:
            provisional.release(live.events)
            provisional.finish(played_ms=200)
        assert len(records) == 1
        record = records[0]
        assert errors("trace/turn-trace", record) == []
        assert record["turn_source"] == "voice"
        voice = record["voice"]
        assert voice["speculative_discard"] == discarded and voice["talk_mode"] == "hands_free"
        assert voice["latency"]["adapter_first_sentence_ms"] >= 0
        assert ("release_ms" in voice["latency"]) != discarded
        assert "e2e_s" not in voice["latency"] and "playback_start_ms" not in voice["latency"]
        assert SAFE not in str(record) and "Could you explain that?" not in str(record)

    asyncio.run(scenario())


DISTRESS = "I want to hurt myself, I can't do this anymore"


@pytest.mark.parametrize("stage", ["evaluated", "in_flight"])
def test_discarded_distress_turn_keeps_safety_flag_and_calm_screen(tmp_path, stage):
    """VOC-20, PRV-14, VOC-35: a discard drops speculative effects, never the safety record or the calm screen."""

    async def scenario():
        live, factory = await prepared(tmp_path)
        frames, learning = [], []
        live.events.sink = frames.append
        live.learning = learning.extend
        provisional = ProvisionalVoiceTurn(live, factory, DISTRESS)
        if stage == "evaluated":
            await provisional.evaluate()
            assert provisional.distress
        else:
            evaluation = asyncio.create_task(provisional.evaluate())
            for _ in range(200):
                await asyncio.sleep(0.005)
                if provisional.learning:
                    break
        await provisional.discard()
        if stage == "in_flight":
            await asyncio.gather(evaluation, return_exceptions=True)
        flagged = [event for event in learning if event.type == "safety_flagged"]
        assert [event.payload["category"] for event in flagged] == ["distress"]
        notices = [f["event"] for f in frames if f["event"]["type"] == "notice"]
        assert [notice["code"] for notice in notices] == ["calm_screen"]
        assert not [f for f in frames if f["event"]["type"] in ("turn.start", "turn.end", "part.start")]
        assert provisional.distress
        await provisional.discard()  # idempotent: never records the flag twice
        assert len([event for event in learning if event.type == "safety_flagged"]) == 1

    asyncio.run(scenario())


def test_salvage_is_synchronous_for_profile_close(tmp_path):
    """Profile close reconciles while the learner database is still open: no await between flag and write."""

    async def scenario():
        live, factory = await prepared(tmp_path)
        learning = []
        live.learning = learning.extend
        provisional = ProvisionalVoiceTurn(live, factory, DISTRESS)
        await provisional.evaluate()
        assert provisional.salvage_safety() is True
        assert [event.type for event in learning] == ["safety_flagged"]
        await provisional.discard()
        assert [event.type for event in learning] == ["safety_flagged"]

    asyncio.run(scenario())


@pytest.mark.parametrize("release", [False, True])
def test_distress_notice_and_safety_flag_survive_unheard_voice_exactly_once(tmp_path, release):
    async def scenario():
        live, factory = await prepared(tmp_path)
        learning = []
        live.learning = learning.extend
        before = state_to_json(live.state)
        turn = ProvisionalVoiceTurn(live, factory, "I want to hurt myself")
        await turn.evaluate()
        # Delivered ahead of release, once: a second call (and the later release or discard) adds nothing.
        assert turn.salvage_safety() and turn.safety_preserved and turn.distress
        assert not turn.salvage_safety()
        assert state_to_json(live.state) == before
        if release:
            turn.release(live.events)
            turn.finish(interrupted=True)
        else:
            await turn.discard()
        notices = [f["event"] for f in live.events.frames if f["event"].get("code") == "calm_screen"]
        flags = [e for e in learning if e.type == "safety_flagged"]
        assert len(notices) == len(flags) == 1
        assert flags[0].payload["category"] == "distress"
        assert "I want to hurt myself" not in str(flags[0].payload)
        if not release:
            assert not any(f["event"]["type"] in ("text.delta", "board.step") for f in live.events.frames)

    asyncio.run(scenario())
