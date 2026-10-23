"""M32 named tests closed without a device (G117): the learner model stays consistent with what the student heard or
saw after a barge-in (VOC-36), and the spoken-form overlay (PRM-26). Replies are scripted; lines are synthetic."""

import asyncio
from pathlib import Path
from typing import Any

from agent_core.engine.voice_turn import ProvisionalVoiceTurn
from engine_harness import tutor
from test_m31_voice_closures import RUNG_FOUR, RUNG_FOUR_BOARD
from test_m32_provisional import prepared

HINT = "Think about which equation links the speed you know to the height you want."
STUCK = "I'm stuck"


def _stuck_on_step(live: Any, rung: int) -> None:
    """One attempt on the current step and the given rung: the student's "I'm stuck" asks for the next rung."""
    state = live.state
    state.attempts, state.hint_step, state.rung = {state.step: 1}, state.step, rung


def voc36_learner_model_consistent(tmp_path: Path) -> None:
    """No learning event refers to tutor output the student neither heard nor saw. A hint discarded before any audio
    (a speculative turn, a barge-in inside the reopen window) leaves no hint event and no rung change. A hint released
    at first audio and interrupted at once was shown in full at release (its text and its board step), so its events
    stand, each tied to a turn whose output reached the student's screen."""

    async def scenario() -> None:
        # 1. Discarded before first audio: nothing heard, nothing shown, nothing learned.
        live, factory = await prepared(tmp_path / "discarded", [tutor(HINT, hint_rung=2)])
        _stuck_on_step(live, 1)
        learned: list[Any] = []
        frames: list[dict[str, Any]] = []
        live.learning, live.events.sink = learned.extend, frames.append
        provisional = ProvisionalVoiceTurn(live, factory, STUCK)
        await provisional.evaluate()
        assert any(e.type == "hint" for batch in provisional.learning for e in batch), "the fork decided a hint"
        await provisional.discard()
        assert learned == [] and frames == [] and live.state.rung == 1

        # 2. Released at first audio, interrupted with nothing played: heard nothing, saw the whole accepted turn.
        for rung, reply in ((1, tutor(HINT, hint_rung=2)), (3, tutor(RUNG_FOUR, hint_rung=4, board=RUNG_FOUR_BOARD))):
            live, factory = await prepared(tmp_path / f"released{rung}", [reply])
            _stuck_on_step(live, rung)
            learned, frames = [], []
            live.learning, live.events.sink = learned.extend, frames.append
            provisional = ProvisionalVoiceTurn(live, factory, STUCK)
            await provisional.evaluate()
            engine = provisional.release(live.events)
            provisional.finish(interrupted=True, played_ms=0)
            assert engine.state.transcript[-1]["heard_text"] == "" and engine.state.rung == rung + 1
            hints = [e for e in learned if e.type == "hint"]
            assert [e.payload["rung"] for e in hints] == [rung + 1]
            for item in learned:
                shown = [f["event"] for f in frames if f.get("turn_id") == item.turn_id]
                text = "".join(e.get("delta", "") for e in shown if e["type"] == "text.delta")
                assert text, f"{item.type} refers to a turn whose text never reached the screen"
                if item.type == "hint" and item.payload["rung"] >= 4:
                    steps = [e for e in shown if e["type"] == "board.step" and e.get("owner") == "tutor"]
                    assert steps, "a rung 4-5 hint counts only with its step on the board"

    asyncio.run(scenario())


# --- PRM-26: the spoken-form overlay -----------------------------------------------------------------------------

# A scripted voice set: what the Coach writes in `say` (LaTeX, markdown, plain) and its `say_spoken`, if any.
VOICE_SET = (
    (r"**Good.** What does $v^2 = u^2 + 2as$ give for $s$?", None),
    (r"Write $\frac{1}{2}mv^2$ for the kinetic energy. Which quantity is missing?", None),
    ("What quantity does the question ask you to find?", "What does the question ask you to find?"),
    (r"Use `h` for the height: what is $h$ at the top?", r"Use h for the height. What is $h$ at the top?"),
    ("Which equation links the speed and the height?", "*Which* equation links the speed and the height?"),
)
OVERLAY = "Voice turn: also write `say_spoken`"  # the spoken-form block's opening (content/agent/guidance)


def prm26_spoken_form_overlay(tmp_path: Path) -> None:
    """With the overlay active (a voice turn), the Coach's prompt carries the spoken-form block with its configured
    caps and every accepted turn of the scripted voice set has a non-null `say_spoken` free of LaTeX and markdown.
    With it inactive (the same replies as typed turns), the block is absent (reported as dropped) and `say_spoken` is
    null even where the Coach wrote one. `say` is unchanged either way."""
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from engine_harness import make_engine
    from jana_tools import REPO_ROOT
    from test_m32_provisional import SAFE
    from test_m32_voice_named import FORBIDDEN

    settings = Settings()
    caps = f"at most {settings.spoken_max_sentences} sentences and {settings.spoken_max_chars} characters"

    async def one(index: int, voice: bool, say: str, spoken: str | None) -> tuple[dict[str, Any], str]:
        reply = tutor(say, say_spoken=spoken, numbers_from=[])
        live, provider = await make_engine(tmp_path / f"{'voice' if voice else 'typed'}{index}",
                                           {"coach": [reply, tutor(SAFE)]}, worker=False)  # fmt: skip
        from agent_core.engine.state import Plan, PlanStep, Problem

        live.state.problem = Problem("prb_test", "Find the height of a ball thrown at 14 m/s.", "prb_test#statement")
        live.state.plan = Plan([PlanStep(1, "h = 10", "10", "m", "chk_test")], "10", "m", "chk_test")

        def factory(state: Any) -> Any:
            return assemble({"local": provider}, live.deps.settings, state, REPO_ROOT / "content" / "agent",
                            REPO_ROOT / "skills", tmp_path / "spill", None)  # fmt: skip

        if voice:
            provisional = ProvisionalVoiceTurn(live, factory, "Could you explain that?")
            await provisional.evaluate()
            turn = provisional.result.tutor_turn
            await provisional.discard()
        else:
            turn = (await factory(live.state).student_turn("Could you explain that?")).tutor_turn
        coach = next(r for r in provider.requests if r["_role"] == "coach")
        system = "\n".join(str(m["content"]) for m in coach["messages"] if m["role"] == "system")
        assert turn is not None
        return turn, system

    async def scenario() -> None:
        for index, (say, spoken) in enumerate(VOICE_SET):
            turn, system = await one(index, True, say, spoken)
            assert OVERLAY in system and caps in system.lower() and "{{" not in system
            assert turn["say_spoken"] and not FORBIDDEN.search(turn["say_spoken"]), turn["say_spoken"]
            assert turn["say"] != turn["say_spoken"] or not FORBIDDEN.search(turn["say"])
            typed, system = await one(index, False, say, spoken)
            assert OVERLAY not in system
            assert typed["say_spoken"] is None and typed["say"] == turn["say"]

    asyncio.run(scenario())
