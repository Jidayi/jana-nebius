"""M43.f, the owner's request of 2026-10-17: talk naturally, point precisely, demonstrate the next step.

One mechanism serves a maths board and a labelled science diagram: the accepted turn's spoken form carries cue markers
that the engine resolves to ids on screen (VOC-10, VSL-45); the bridge sends them with the caption and word times
(VOC-51); evidence about a demonstration counts only once its words were heard (VOC-52); and a turn that waits ends
with one ask (PED-28). The engine runs for real with scripted model outputs; the maths problem, its checks and the
lines are invented for these tests, and the diagram is the physics pack's own refraction drawing.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.contracts import errors
from agent_core.engine import pointing
from agent_core.engine.assembly import assemble
from agent_core.engine.gates import ask_problem
from agent_core.engine.pointing import Shown, Targets, first_unheard, resolve, strip_markers
from agent_core.engine.state import BoardStep, Plan, PlanStep, Problem
from agent_core.engine.ui import open_board
from agent_core.engine.voice_bridge import VoiceBridge, VoiceProtocolError, aligned_words
from agent_core.engine.voice_turn import ProvisionalVoiceTurn
from engine_harness import close, make_engine, reply, tutor
from jana_tools import REPO_ROOT
from test_m31_voice_bridge import TURN, audio, created, event, ready

STEP_A = "stp_01JZ0000000000000000000001"
STEP_B = "stp_01JZ0000000000000000000002"
VISUAL = "vis_01JZ0000000000000000000003"
OTHER = "vis_01JZ0000000000000000000004"

# --- the maths slice: a two-step linear equation, the student on the step "take three from both sides" ------------

STATEMENT = "Solve 2x + 3 = 11."
WHY = "Why do we take away three?"
OPERATION = "2x + 3 - 3 = 11 - 3"


def _op(op: str, **fields: Any) -> dict[str, Any]:
    return {"op": op, "step": None, "latex": None, "reason": None, "owner": None, "status": None, "terms": [],
            "prompt": None, "check_id": None, **fields}  # fmt: skip


HIGHLIGHT = _op("highlight", step=1)
SHOW_OPERATION = _op("add_step", latex=OPERATION, reason="take 3 from both sides", owner="tutor", status="final",
                     check_id="chk_step2")  # fmt: skip
SHOW_RESULT = _op("add_step", latex="2x = 8", reason="11 - 3 is 8", owner="tutor", status="final",
                  check_id="chk_step2")  # fmt: skip
SHOW_UNCHECKED = _op("add_step", latex="2x = 9", reason="take 3 from both sides", owner="tutor", status="final")

# Rung 0, "why": focus the equation and explain the operation in words; no new line (the leak gate holds the step).
DEMO_SAY = "This line adds 3 to 2x, so we take 3 from both sides and they stay equal. What do you get on the right?"
DEMO_SPOKEN = ('This line <point at="1"/> adds three to two x, so we take three from both sides and they stay equal. '
               "What do you get on the right?")  # fmt: skip
# Rung 4, "show me": the verified transformation is written on in time with the words that cite it.
STEP_SAY = "We take 3 from both sides: 2x + 3 - 3 = 11 - 3. What does the right side come to?"
DEMO_SPOKEN_STEP = ('This line <point at="1"/> adds three to two x, so we take three from both sides. '
                    '<write at="2">Two x plus three minus three equals eleven minus three.</write> '
                    "What does the right side come to?")  # fmt: skip
SHOW_ME = "I'm stuck, show me"
STEP_SPOKEN = ('Here is the whole step on this line <point at="1"/>. <write at="2">Two x equals eight.</write> '
               "Can you find x now?")  # fmt: skip


def demo(board: list[dict[str, Any]], spoken: str | None, say: str = DEMO_SAY, **fields: Any) -> dict:
    return tutor(say, say_spoken=spoken, board=board, **fields)


DEMO = demo([HIGHLIGHT], DEMO_SPOKEN)
DEMO_STEP = demo([HIGHLIGHT, SHOW_OPERATION], DEMO_SPOKEN_STEP, say=STEP_SAY, hint_rung=4)
LEAK = demo([HIGHLIGHT, SHOW_OPERATION], DEMO_SPOKEN_STEP, say=STEP_SAY)
UNCHECKED = demo([HIGHLIGHT, SHOW_UNCHECKED], DEMO_SPOKEN_STEP, say=STEP_SAY, hint_rung=4)
FULL_STEP = demo([HIGHLIGHT, SHOW_RESULT], STEP_SPOKEN, say="Taking 3 from both sides gives 2x = 8. Can you find x?",
                 hint_rung=5)  # fmt: skip


def maths_state(state: Any, *, rung: int = 0) -> None:
    """The board shows the equation; the verified plan's second step (take three from both sides) is the current one."""
    state.subject = "mathematics"
    state.problem = Problem("prb_lin", STATEMENT, "prb_lin#statement")
    state.plan = Plan([PlanStep(1, "2x + 3 = 11", None, None, None), PlanStep(2, OPERATION, "8", None, "chk_step2"),
                       PlanStep(3, "x = 4", "4", None, "chk_step3")], "4", None, "chk_step3")  # fmt: skip
    state.check_values = {"chk_step2": [Fraction(8), Fraction(3), Fraction(11)], "chk_step3": [Fraction(4)]}
    open_board(state)  # the problem's own board, as the first board operation opened it (API-41)
    state.board.steps = [BoardStep(STEP_A, 0, "2x + 3 = 11", "the equation", "tutor", "final")]
    state.step, state.rung = 2, rung
    state.attempts, state.hint_step = {2: 1}, 2


async def maths_engine(tmp_path: Path, replies: list[Any], *, rung: int = 0) -> tuple[Any, Any, Any]:
    live, provider = await make_engine(tmp_path, {"coach": replies}, worker=False)
    maths_state(live.state, rung=rung)

    def factory(state: Any) -> Any:
        return assemble({"local": provider}, live.deps.settings, state, REPO_ROOT / "content" / "agent",
                        REPO_ROOT / "skills", tmp_path / "spill", None)  # fmt: skip

    return live, factory, provider


def board_lines(state: Any) -> list[tuple[str, str, str | None]]:
    return [(s.latex, s.status, s.check_id) for s in state.board.steps]


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


# --- VSL-45: an ambiguous target is said in words, never guessed --------------------------------------------------

TARGETS = Targets(
    steps=((STEP_A, "tutor", "final"), (STEP_B, "tutor", "unchecked")),
    visuals=(
        Shown(VISUAL, ("incident_ray", "normal_entry", "refracted_ray")),
        Shown(OTHER, ("incident_ray", "mirror")),
    ),
)
# Each fixture names its place in words; its marker is unknown, off screen, unverified or not unique.
MISSES = (
    ('Look at the third line <point at="3"/> of the board.', "step_not_on_board"),
    ('Look at the line we removed <point at="stp_01JZ0000000000000000000009"/> before.', "step_not_on_board"),
    ('Look at the second line <point at="2"/> for a moment.', "step_unchecked"),
    ('Look at the incident ray <point at="incident_ray"/> in the drawing.', "part_ambiguous"),
    ('Look at the normal <point at="normal"/> where the ray enters.', "part_unknown"),
    ('Look at the old drawing <point at="vis_01JZ0000000000000000000009:mirror"/> again.', "visual_not_shown"),
    (f'Look at the mirror <point at="{VISUAL}:mirror"/> on the left.', "part_unknown"),
)


def vsl45_ambiguous_target_no_pointer() -> None:
    """No marker whose target is not exactly one element on screen draws anything; each miss has its reason code."""
    for text, reason in MISSES:
        spoken = resolve(text, TARGETS)
        assert spoken.cues == () and spoken.misses == (reason,), text
    # The same mechanism, given exactly one element, points at it: a board line by number or id, a part by its name
    # in the one visual that has it, or by the visual's id.
    hits = resolve('One <point at="1"/> two <point at="refracted_ray"/> three '
                   f'<point at="{OTHER}:mirror"/> four <point at="{STEP_A}"/>.', TARGETS)  # fmt: skip
    assert [c.target for c in hits.cues] == [STEP_A, f"{VISUAL}:refracted_ray", f"{OTHER}:mirror", STEP_A]
    assert hits.misses == ()


def vsl45_location_said_in_words() -> None:
    """Dropping a marker loses nothing the student needs: the words that name the place are spoken as written."""
    for text, _ in MISSES:
        spoken = resolve(text, TARGETS)
        assert spoken.text == strip_markers(text)
        assert re.search(r"\b(line|ray|normal|drawing|mirror)\b", spoken.text)


def test_vsl45_cue_offsets_index_the_spoken_text() -> None:
    """Each cue's offset is a character of the exact text sent to speech; a write cue spans the words that cite the
    new line, and only a line this turn added can be written on."""
    targets = Targets(steps=((STEP_A, "tutor", "final"), (STEP_B, "tutor", "final")), new_steps=frozenset({STEP_B}))
    spoken = resolve(DEMO_SPOKEN_STEP, targets)
    point, write = spoken.cues
    assert (point.target, point.action) == (STEP_A, "point")
    assert (write.target, write.action) == (STEP_B, "write")
    assert (
        spoken.text[write.char_offset : write.end_offset] == "Two x plus three minus three equals eleven minus three."
    )
    assert "<" not in spoken.text and spoken.text.endswith("What does the right side come to?")
    old = resolve('<write at="1">The first line.</write> Next?', targets)
    assert [(c.target, c.action) for c in old.cues] == [(STEP_A, "point")] and old.misses == ("write_not_new_line",)


# --- UXS-64: demonstrating the next step -------------------------------------------------------------------------


def uxs64_demo_uses_verified_values_only(tmp_path: Path) -> None:
    """A demonstration whose line carries an unchecked number is rejected before anything is spoken or shown; the
    regenerated one shows the checked transformation, and every number spoken or shown traces to its check."""

    async def scenario() -> None:
        live, factory, _ = await maths_engine(tmp_path, [UNCHECKED, DEMO_STEP], rung=3)
        provisional = ProvisionalVoiceTurn(live, factory, SHOW_ME)
        await provisional.evaluate()
        gates = {g["gate"]: g for g in provisional.traces[-1]["gates"]}
        assert gates["verified"]["fired"] and gates["verified"]["outcome"] == "passed_after_nudge"
        state = provisional.engine.state
        assert board_lines(state)[-1] == (OPERATION, "final", "chk_step2")
        assert "9" not in provisional.spoken_text and "nine" not in provisional.spoken_text
        assert "2x = 9" not in json.dumps(provisional.events.frames)
        spoken_numbers = {"three", "eleven", "two"}
        assert spoken_numbers >= set(re.findall(r"\b(two|three|eight|eleven|nine)\b", provisional.spoken_text))
        write = next(c for c in provisional.cues if c.action == "write")
        assert write.target == state.board.steps[-1].step_id and write.target in {s.step_id for s in state.board.steps}
        await provisional.discard()
        await close(live)

    run(scenario())


def uxs64_respects_hint_level(tmp_path: Path) -> None:
    """At rung 0 a demonstration that writes the step's working (`11 - 3` gives the value the student has not reached)
    is caught by the leak gate and regenerated: the tutor focuses the line and explains the operation in words, and no
    line is added. At rung 4 the transformation may be shown; at rung 5 (the full step, asked for) its result too, and
    never the later step."""

    async def scenario() -> None:
        live, factory, _ = await maths_engine(tmp_path / "low", [LEAK, DEMO])
        provisional = ProvisionalVoiceTurn(live, factory, WHY)
        await provisional.evaluate()
        leak = next(g for g in provisional.traces[-1]["gates"] if g["gate"] == "no_answer_leak")
        assert leak["fired"] and leak["outcome"] == "passed_after_nudge"
        assert [s.latex for s in provisional.engine.state.board.steps] == ["2x + 3 = 11"]
        assert "eleven minus three" not in provisional.spoken_text and "eight" not in provisional.spoken_text
        assert [c.target for c in provisional.cues] == [STEP_A]  # the focus on the equation itself
        await provisional.discard()
        await close(live)

        live, factory, _ = await maths_engine(tmp_path / "full", [FULL_STEP], rung=4)
        provisional = ProvisionalVoiceTurn(live, factory, SHOW_ME)
        await provisional.evaluate()
        assert board_lines(provisional.engine.state)[-1] == ("2x = 8", "final", "chk_step2")
        assert "Two x equals eight." in provisional.spoken_text and provisional.engine.state.rung == 5
        assert "x = 4" not in [s.latex for s in provisional.engine.state.board.steps]  # never the later step
        await provisional.discard()
        await close(live)

    run(scenario())


def uxs64_sound_off_and_screen_reader(tmp_path: Path) -> None:
    """With sound off (a typed turn) the same demonstration reaches the screen as text: the focused line, the new line
    with its reason and check, and the explanation, in order and in words. The spoken form is not needed for any of it
    (the screen reader announcements are covered by the board's own tests)."""

    async def scenario() -> None:
        live, _, _ = await maths_engine(tmp_path, [DEMO_STEP], rung=3)
        result = await live.student_turn(SHOW_ME)
        assert result.status == "complete"
        events = [f["event"] for f in live.events.frames]
        kinds = [e["type"] for e in events if e["type"] in ("text.delta", "board.highlight", "board.step")]
        assert kinds.index("text.delta") < kinds.index("board.highlight") < kinds.index("board.step")
        step = next(e for e in events if e["type"] == "board.step")
        assert (step["latex"], step["reason"], step["check_id"]) == (OPERATION, "take 3 from both sides", "chk_step2")
        highlight = next(e for e in events if e["type"] == "board.highlight")
        assert highlight["step_ids"] == [STEP_A]
        text = "".join(e["delta"] for e in events if e["type"] == "text.delta")
        assert text == STEP_SAY
        assert result.tutor_turn is not None and result.tutor_turn["say_spoken"] is None  # nothing needs sound
        await close(live)

    run(scenario())


# --- PED-28: one clear ask before waiting --------------------------------------------------------------------------


def ped28_one_ask_before_waiting(tmp_path: Path) -> None:
    """Every accepted turn that waits ends with exactly one question or instruction and nothing after it, typed and
    spoken alike; a turn that waits for nothing is not held to it."""
    cases = [
        ({"expects": "student_answer", "say": "Look at line 1. What is x?"}, None),
        ({"expects": "student_answer", "say": "Look at line 1. Now try it yourself."}, None),
        ({"expects": "student_answer", "say": "What is x? Then check it."}, "say: ask_not_last"),
        ({"expects": "student_choice", "say": "Which one? Or the other?"}, "say: two_asks"),
        ({"expects": "none", "say": "Well done? Yes. Well done."}, None),
        ({"expects": "student_answer", "say": "What is x?", "say_spoken": "What is x? Say it."}, None),
    ]
    for draft, fault in cases:
        assert ask_problem(draft) == fault, draft
    assert ask_problem({"expects": "student_answer", "say": "What is x?", "say_spoken": "What is x? Say it."},
                       spoken=True) == "say_spoken: ask_not_last"  # fmt: skip
    assert ask_problem({"expects": "student_answer", "say": "Why?", "say_spoken": 'Look <point at="1"/>. Why?'},
                       spoken=True) is None  # fmt: skip

    async def scenario() -> None:
        live, _, _ = await maths_engine(tmp_path, [DEMO])
        typed = await live.student_turn(WHY)
        assert typed.tutor_turn is not None and ask_problem(typed.tutor_turn) is None
        live2, factory2, _ = await maths_engine(tmp_path / "voice", [DEMO])
        provisional = ProvisionalVoiceTurn(live2, factory2, WHY)
        await provisional.evaluate()
        assert provisional.result is not None and provisional.result.tutor_turn is not None
        assert ask_problem(provisional.result.tutor_turn, spoken=True) is None
        assert provisional.spoken_text.endswith("?") and provisional.spoken_text.count("?") == 1
        await provisional.discard()
        await close(live)
        await close(live2)

    run(scenario())


def ped28_two_asks_regenerated(tmp_path: Path) -> None:
    """A Coach draft with two asks fails the gate and is regenerated; the accepted turn is the one with one ask."""
    two = demo([HIGHLIGHT], None, say="What do we do to both sides? And why does that keep it balanced?")

    async def scenario() -> None:
        live, _, provider = await maths_engine(tmp_path, [two, DEMO])
        result = await live.student_turn(WHY)
        coach = [r for r in provider.requests if r.get("_role") == "coach"]
        assert len(coach) == 2 and "exactly one short question" in coach[1]["messages"][-1]["content"]
        gate = next(g for g in result.trace["gates"] if g["gate"] == "one_ask")
        assert gate["fired"] and gate["outcome"] == "passed_after_nudge"
        assert result.tutor_turn is not None and result.tutor_turn["say"] == DEMO_SAY
        await close(live)

    run(scenario())


def test_ped28_exhausted_regenerations_keep_the_first_ask(tmp_path: Path) -> None:
    """Out of regenerations, the reply is cut after its first ask instead of being replaced (it still ends with one)."""
    twos = [demo([HIGHLIGHT], None, say=f"What do we do to both sides{mark}? And why{mark}?")
            for mark in ("", " here", " now", " first")]  # fmt: skip

    async def scenario() -> None:
        live, _, _ = await maths_engine(tmp_path, twos)
        result = await live.student_turn(WHY)
        said = result.tutor_turn["say"] if result.tutor_turn is not None else ""
        assert said.startswith("What do we do to both sides") and said.count("?") == 1 and said.endswith("?")
        gate = next(g for g in result.trace["gates"] if g["gate"] == "one_ask")
        assert gate["outcome"] == "exhausted_fallback"
        await close(live)

    run(scenario())


# --- VOC-51: cues fire on playback; the bridge sends them with word times ----------------------------------------


def transcript(delta: str, response_id: str = "resp_1") -> dict[str, Any]:
    return event("response.output_audio_transcript.delta", response_id=response_id, item_id="out_1", output_index=0,
                 content_index=0, delta=delta)  # fmt: skip


def caption_bridge(spoken: str, cues: tuple[pointing.Cue, ...]) -> VoiceBridge:
    bridge = ready()
    created(bridge, authorise=False)
    bridge.authorise_response("resp_1", TURN, spoken, cues)
    return bridge


def test_voc10_caption_carries_resolved_cues_and_word_times() -> None:
    """The tutor caption carries the turn's cues once their words are in it, and word times anchored where each spoken
    unit arrived in the audio stream; every caption validates against the events contract in force."""
    targets = Targets(steps=((STEP_A, "tutor", "final"), (STEP_B, "tutor", "final")), new_steps=frozenset({STEP_B}))
    spoken = resolve(DEMO_SPOKEN_STEP, targets)
    first, second, third = re.findall(r"[^.?!]+[.?!]", spoken.text)
    bridge = caption_bridge(spoken.text, spoken.cues)
    events = bridge.server(transcript(first), 0).events
    events += bridge.server(audio(pcm=b"\x00\x00" * 48_000), 0).events  # 2 s
    events += bridge.server(transcript(second), 0).events
    events += bridge.server(audio(pcm=b"\x00\x00" * 72_000), 0).events  # 3 s
    events += bridge.server(transcript(third), 0).events
    captions = [e for e in events if e["type"] == "voice.caption"]
    for caption in captions:
        assert errors("api/events#/$defs/ev_voice_caption", caption) == []
    last = captions[-1]
    assert [c["target"] for c in last["cues"]] == [STEP_A, STEP_B]
    words = last["words"]
    assert len(words) == len(spoken.text.split())
    assert words[0]["start_ms"] == 0
    second_start = len(first.split())
    assert words[second_start]["start_ms"] == 2000  # the second unit starts where its audio did
    assert all(a["start_ms"] <= b["start_ms"] for a, b in itertools.pairwise(words))
    early = captions[0]  # only the first unit's words: the write cue's words are not there yet
    assert [c["target"] for c in early["cues"]] == [STEP_A]


def test_voc10_cues_name_ids_only() -> None:
    """A cue that is not an id on screen, or that does not index the spoken text, is a defect and is never sent."""
    bridge = ready()
    created(bridge, authorise=False)
    for bad in (pointing.Cue(0, "the second line"), pointing.Cue(99, STEP_A), pointing.Cue(3, STEP_A, "write", 1)):
        with pytest.raises(VoiceProtocolError):
            bridge.authorise_response("resp_1", TURN, "Look here.", (bad,))


def test_voc51_write_cues_wait_for_the_events_contract() -> None:
    """HAND-WRITTEN BINDING check: under the pinned events contract (no cue `action`) a write cue travels as a point;
    when the contract carries write cues (API 1.9) it travels as a write with its end offset."""
    cue = pointing.Cue(5, STEP_B, "write", 20)
    assert cue.event(actions=False) == {"char_offset": 5, "target": STEP_B}
    assert cue.event(actions=True) == {"char_offset": 5, "target": STEP_B, "action": "write", "end_offset": 20}
    pointing.cue_actions_supported.cache_clear()
    supported = pointing.cue_actions_supported()
    from agent_core.contracts import document

    cue_props = document("api/events")["$defs"]["ev_voice_caption"]["properties"]["cues"]["items"]["properties"]
    assert supported == ("action" in cue_props)


def voc51_estimated_timing_labelled(tmp_path: Path) -> None:
    """With only the caption synchroniser's estimate available (the sidecar sends no word alignment), the turn's trace
    records its cue timing as estimated; a turn without cues records nothing about cue timing."""

    async def scenario() -> None:
        live, factory, _ = await maths_engine(tmp_path, [DEMO, tutor("What is x?")])
        provisional = ProvisionalVoiceTurn(live, factory, WHY)
        await provisional.evaluate()
        engine = provisional.release(live.events)
        provisional.finish(interrupted=False, played_ms=9000)
        record = engine.traces[-1]
        names = [g["gate"] for g in record["gates"]]
        assert "cue_timing_estimated" in names and errors("trace/turn-trace", record) == []
        plain = ProvisionalVoiceTurn(engine, factory, "and next?")
        await plain.evaluate()
        assert plain.cues == ()
        engine2 = plain.release(engine.events)
        plain.finish(interrupted=False, played_ms=1000)
        assert "cue_timing_estimated" not in [g["gate"] for g in engine2.traces[-1]["gates"]]
        await close(live)

    run(scenario())


# --- VOC-52: the heard extent, resuming, and learner state ---------------------------------------------------------


def voc52_heard_extent_from_playback() -> None:
    """The heard extent follows the audio the student's device reports as played, never the audio sent or received:
    six seconds arrive, one and a half play, and the extent ends at the first unit."""
    spoken = "We take three from both sides. That gives the line below. What does the right side come to?"
    first, second, third = re.findall(r"[^.?!]+[.?!]", spoken)
    bridge = caption_bridge(spoken, ())
    bridge.server(transcript(first), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 48_000), 0)  # 2 s received
    bridge.server(transcript(second), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 48_000), 0)  # 4 s received
    bridge.server(transcript(third), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 48_000), 0)  # 6 s received, all of it before the student speaks
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 2100, "ended": False})
    cancel = next(a for a in bridge.control({"type": "stop"}).actions if a["type"] == "cancel")
    assert cancel["played_ms"] == 2100 and cancel["total_ms"] == 6000
    assert spoken[: cancel["heard_chars"]] == first
    # Playback reports never move backwards or past what was received.
    bridge = caption_bridge(spoken, ())
    bridge.server(audio(pcm=b"\x00\x00" * 24_000), 0)
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 600, "ended": False})
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 300, "ended": False})
    bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 5000, "ended": False})
    assert bridge._response is not None and bridge._response.played_ms == 600


def voc52_resume_from_unheard(tmp_path: Path) -> None:
    """After an interruption mid-explanation the next turn's context names the first unit the student did not hear,
    so the tutor continues there instead of repeating what was heard."""

    async def scenario() -> None:
        live, factory, provider = await maths_engine(tmp_path, [DEMO_STEP, tutor("What does the right side come to?")],
                                                     rung=3)  # fmt: skip
        provisional = ProvisionalVoiceTurn(live, factory, SHOW_ME)
        await provisional.evaluate()
        engine = provisional.release(live.events)
        heard_to = provisional.spoken_text.index("Two x plus")  # the first unit played, then the student spoke
        provisional.finish(interrupted=True, played_ms=4000, heard_chars=heard_to)
        unheard = first_unheard(provisional.spoken_text, provisional.spoken_text[:heard_to])
        assert unheard == "Two x plus three minus three equals eleven minus three."
        assert engine.voice_unheard == unheard
        await engine.student_turn("sorry, carry on please")
        # The tutor-context carries the one-shot resume note; the restored rung reaches the Coach too, as the
        # session reminder that follows it (the demonstration was not heard, so rung 4 never counted).
        sent = [str(m["content"]) for m in provider.requests[-1]["messages"]]
        context = next(c for c in sent if "Not heard yet" in c or "The student interrupted after" in c)
        assert "Not heard yet, continue from: 'Two x plus three minus three equals eleven minus three.'" in context
        assert "The student interrupted after: 'This line adds three to two x" in context
        assert "hint rung: 3" in context and any("The hint rung is now 3." in c for c in sent)
        assert "Not heard yet" not in json.dumps(provider.requests[:-1])
        await close(live)

    run(scenario())


def voc52_unheard_no_learner_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A full-step demonstration written on with its words (rung 5) counts only once its words were heard: interrupted
    before them, no hint or bottom-out is recorded and the rung goes back; heard through, both are recorded. The
    student's own evidence is never held. (Write cues reach the client from API 1.9; the rule is exercised as it will
    run after that re-pin.)"""
    monkeypatch.setattr(pointing, "cue_actions_supported", lambda: True)

    async def once(where: Path, heard: str) -> tuple[list[Any], Any, ProvisionalVoiceTurn]:
        live, factory, _ = await maths_engine(where, [FULL_STEP], rung=4)
        learned: list[Any] = []
        live.learning = learned.extend
        provisional = ProvisionalVoiceTurn(live, factory, SHOW_ME)
        await provisional.evaluate()
        assert provisional.demonstrates()
        engine = provisional.release(live.events)
        assert [e for e in learned if e.type == "hint"] == []  # held until the demonstration's words are heard
        text = provisional.spoken_text
        cut = {"before": text.index("Two x equals"), "after": text.index("Can you")}[heard]
        provisional.finish(interrupted=True, played_ms=3000, heard_chars=cut)
        await close(live)
        return learned, engine, provisional

    learned, engine, provisional = run(once(tmp_path / "before", "before"))
    assert [e.type for e in learned if e.type in ("hint", "integrity_signal")] == []
    assert engine.state.rung == 4 and provisional.counted is False
    updates = [f["event"] for f in engine.events.frames if f["event"]["type"] == "session.updated"]
    assert updates and updates[-1]["hint_rung"] == 4
    assert "unheard_evidence_dropped" in [g["gate"] for g in engine.traces[-1]["gates"]]

    learned, engine, provisional = run(once(tmp_path / "after", "after"))
    assert [e.payload["rung"] for e in learned if e.type == "hint"] == [5]
    assert any(e.type == "integrity_signal" and e.payload["kind"] == "bottom_out" for e in learned)
    assert engine.state.rung == 5 and provisional.counted is True


# --- VOC-32: spoken and typed questions give the same teaching outcome ---------------------------------------------


def outcome(engine: Any, learned: list[Any]) -> dict[str, Any]:
    state = engine.state
    gates = [(g["gate"], g["outcome"]) for record in engine.traces for g in record["gates"]
             if not g["gate"].startswith(("voice_", "verbaliser_", "cue_", "pointer_"))]  # fmt: skip
    return {
        "board": board_lines(state),
        "highlight": [e["event"]["step_ids"] for e in engine.events.frames if e["event"]["type"] == "board.highlight"],
        "checks": sorted(state.check_values),
        "rung": state.rung,
        "gates": gates,
        # The same events, compared as a set: on the voice path tutor-output evidence is written once its words are
        # heard (VOC-52), so it lands after the evidence written on release; the order of writing is not an outcome.
        "learning": sorted(
            (
                e.type,
                json.dumps({k: v for k, v in e.payload.items() if k not in ("turn_id", "session_id")}, sort_keys=True),
            )
            for e in learned
        ),
        "say": [r["content"] for r in state.transcript if r.get("role") == "assistant"],
    }


def voc32_spoken_typed_same_teaching_outcome(tmp_path: Path) -> None:
    """The same question spoken and typed gives the same accepted board operations, checks, demonstration, hint rung
    and learning events; only the spoken form differs (it exists only in voice)."""

    async def scenario() -> None:
        for text, rung, reply_ in ((WHY, 0, DEMO), (SHOW_ME, 4, FULL_STEP)):
            typed_live, _, _ = await maths_engine(tmp_path / f"typed{rung}", [reply_], rung=rung)
            typed_learned: list[Any] = []
            typed_live.learning = typed_learned.extend
            await typed_live.student_turn(text)
            voice_live, factory, _ = await maths_engine(tmp_path / f"voice{rung}", [reply_], rung=rung)
            voice_learned: list[Any] = []
            voice_live.learning = voice_learned.extend
            provisional = ProvisionalVoiceTurn(voice_live, factory, text)
            await provisional.evaluate()
            engine = provisional.release(voice_live.events)
            provisional.finish(interrupted=False, played_ms=9000)
            typed_outcome, voice_outcome = outcome(typed_live, typed_learned), outcome(engine, voice_learned)
            # Step ids are minted per session; everything else matches.
            for side in (typed_outcome, voice_outcome):
                side["highlight"] = [len(ids) for ids in side["highlight"]]
            assert voice_outcome == typed_outcome
            assert provisional.spoken_text and provisional.cues
            # Heard through: nothing held back is left uncounted (with write cues the hold was active, VOC-52).
            assert provisional.held == [] and provisional.counted in (None, True)
            await close(typed_live)
            await close(voice_live)

    run(scenario())


# --- the same mechanism on a labelled science diagram ---------------------------------------------------------------

PHYSICS = "A ray of light enters a glass block at an angle. Explain what happens to the ray."
REFRACTION = "dgm.phy.refraction_glass_block.v1"


def _refraction_entry() -> dict[str, Any]:
    from agent_core.store.svg import normalise

    pack = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
    entry = yaml.safe_load((pack / "diagrams" / f"{REFRACTION}.yaml").read_text())
    return {**entry, "svg": normalise((pack / entry["svg_path"]).read_text())}


SHOW = tutor("Here is the ray going into the block. Which line is the normal?",
             visual=[{"spec_version": 1, "type": "library_diagram", "ref": REFRACTION, "params": {},
                      "steps": [{"highlight": ["incident_ray"]}]}])  # fmt: skip
POINT = tutor(
    "Inside the glass the ray bends towards the normal, so the angle of refraction is smaller. Which angle is smaller?",
    say_spoken='Here is the normal <point at="normal_entry"/> where the ray goes in. Inside the glass the ray '
    '<point at="refracted_ray"/> bends towards it, so this angle <point at="angle_r"/> is smaller. '
    "Which angle is smaller?",
)


def test_uxs64_diagram_demo_points_at_the_parts_on_screen(tmp_path: Path) -> None:
    """The maths mechanism, unchanged, on the physics pack's refraction drawing: a spoken "why" points at the normal,
    the refracted ray and the angle of refraction by the part ids of the visual on screen."""
    diagnosis = {"in_scope": True, "subject": "physics", "topic_ref": None, "kc_refs": [], "question_kind": "diagram",
                 "knowns": [], "unknowns": [], "clarifying_question": None, "misconception_ref": None, "evidence": [],
                 "inference": "", "prerequisite_gap_refs": [], "confidence": "medium"}  # fmt: skip
    from engine_harness import checker_steps, solver_steps

    script = {"diagnoser": [reply(json.dumps(diagnosis))], "solver": solver_steps(), "checker": checker_steps(),
              "coach": [tutor("What happens to light at the edge of the block?"), SHOW, POINT]}  # fmt: skip

    async def scenario() -> None:
        live, provider = await make_engine(tmp_path, script)
        live.deps.stage = "S2"
        sources = {"diagrams": {REFRACTION: _refraction_entry()}, "presets": {}, "conventions": {}, "pack_values": {}}
        live.deps.visual_sources = lambda code: sources
        await live.start_problem(PHYSICS)
        await live.student_turn("Can you show me the ray in the block?")
        shown = live.state.shown_visuals
        assert len(shown) == 1 and {"normal_entry", "refracted_ray", "angle_r"} <= set(shown[0]["parts"])

        def factory(state: Any) -> Any:
            engine = assemble({"local": provider}, live.deps.settings, state, REPO_ROOT / "content" / "agent",
                              REPO_ROOT / "skills", tmp_path / "spill", live.deps.executor.supervisor)  # fmt: skip
            engine.deps.stage, engine.deps.visual_sources = "S2", live.deps.visual_sources
            return engine

        provisional = ProvisionalVoiceTurn(live, factory, "Why does the ray bend towards the normal?")
        await provisional.evaluate()
        visual = shown[0]["visual_id"]
        assert [c.target for c in provisional.cues] == [f"{visual}:normal_entry", f"{visual}:refracted_ray",
                                                        f"{visual}:angle_r"]  # fmt: skip
        assert provisional.cue_misses == () and "<" not in provisional.spoken_text
        for cue in provisional.cues:
            assert cue.char_offset < len(provisional.spoken_text)
        await provisional.discard()
        await close(live)

    run(scenario())


def test_vsl45_a_new_problem_clears_the_visuals_on_screen() -> None:
    """A new problem's cues can never point at the last problem's drawing (VSL-45)."""
    settings = Settings()
    assert settings.pointer_visuals_kept >= 1
    spoken = resolve('The ray <point at="refracted_ray"/> bends.', Targets(visuals=()))
    assert spoken.cues == () and spoken.misses == ("part_unknown",)


def test_voc51_word_times_never_run_ahead_of_received_audio() -> None:
    """Word times inside a unit are syllable estimates within the unit's own audio, so a cue's time never falls after
    audio that has not arrived; a unit still arriving runs at the synchroniser's rate."""
    bridge = caption_bridge("One two three. Four five six.", ())
    bridge.server(transcript("One two three."), 0)
    bridge.server(audio(pcm=b"\x00\x00" * 24_000), 0)  # 1 s
    bridge.server(transcript(" Four five six."), 0)
    assert bridge._response is not None
    words = aligned_words(bridge._response)
    assert [w["start_ms"] for w in words[:3]] == [0, 500, 750]  # by syllables: one (2), two (1), three (1)
    assert words[3]["start_ms"] == 1000
    # A slow voice: the last unit's audio already received is longer than the estimate, so its words spread over it
    # (measured: Qwen3-TTS "Ryan" speaks units about a second longer than the synchroniser's rate).
    bridge.server(audio(pcm=b"\x00\x00" * 96_000), 0)  # 4 s for "Four five six."
    words = aligned_words(bridge._response)
    assert words[4]["start_ms"] > 1000 + round(1 * 1000 / 3.83) and words[5]["start_ms"] >= 1000 + 2000


def test_voc14_a_voice_failure_with_cues_keeps_the_typed_fallback(tmp_path: Path) -> None:
    """VOC-14: when the voice endpoint fails before a pointed turn is heard, the same question completes as a typed turn
    (its text, its highlight on the board) and no cue of the lost response ever reaches the screen."""
    from test_m32_adapter import body, setup_adapter

    pointed = tutor("Look at the first line. What does it give?", board=[HIGHLIGHT],
                    say_spoken='Look at this line <point at="1"/>. What does it give?')  # fmt: skip

    async def scenario() -> None:
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(
            tmp_path, replies=[pointed, pointed]
        )
        try:
            state = core.sessions[sid].engine_state
            open_board(state)
            state.board.steps = [BoardStep(STEP_A, 0, "h = 10", "the height", "tutor", "final")]
            response = await client.post("/v1/voice/llm/chat/completions",
                                         headers={"authorization": "Bearer adapter-secret"},
                                         json=body(instructions))  # fmt: skip
            assert response.status_code == 200
            job = next(iter(runtime.adapter.jobs.values()))
            assert [c.target for c in job.turn.cues] == [STEP_A]
            await endpoint.incoming.put(RuntimeError("transport_lost"))
            async with asyncio.timeout(5):
                entry = core.sessions[sid]
                while entry.task is None or not entry.task.done():
                    await asyncio.sleep(0.01)
            events = [f["event"] for f in core._engine(entry).events.frames]
            ends = [e for e in events if e["type"] == "turn.end"]
            assert len(ends) == 1 and ends[0]["status"] == "complete"
            assert [e["step_ids"] for e in events if e["type"] == "board.highlight"] == [[STEP_A]]
            assert not [e for e in events if e["type"] == "voice.caption" and e.get("cues")]
            assert entry.engine_state.transcript[-1]["content"] == "Look at the first line. What does it give?"
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    run(scenario())
