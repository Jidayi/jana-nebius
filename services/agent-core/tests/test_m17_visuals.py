"""M17 in the engine: step operations resolved by the tools (VSL-10), one corrected attempt at a visual (VSL-17), and
the per-kind rules the vetted renderers are held to (VSL-12, VSL-14, VSL-19, VSL-29)."""

import asyncio
import json
from fractions import Fraction
from pathlib import Path

import pytest
import yaml
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, feedback, kind_param_errors, validate
from agent_core.contracts import errors as contract_errors
from agent_core.store.svg import normalise
from engine_harness import STATEMENT, checker_steps, close, make_engine, reply, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.visual_fixtures import _call

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"


def run(coro):
    return LOOP.run_until_complete(coro)


INCLINE = {
    "spec_version": 1,
    "type": "free_body",
    "params": {
        "object": "block",
        "surface": {"incline_deg": 30, "kind": "incline"},
        "forces": [{"id": "W", "name": "weight", "magnitude": "49 N", "direction_deg": 270}],
    },
    "numbers_from": ["kn_fw"],
    "steps": [{"highlight": ["W"]}, {"add": [{"element": "components_of", "of": "W"}]}],
}


def vsl10_add_components():
    ctx = VisualContext("physics", "O", "S2", knowns={"kn_fw": Fraction(49)})
    calls = []
    call = _call("vsl10")

    def counted(tool, args):
        calls.append((tool, args))
        return call(tool, args)

    resolved, _ = validate(INCLINE, ctx, Resolver(resolver(counted)))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    ids = [p["id"] for p in resolved["parts"]]
    assert "W.parallel" in ids and "W.perpendicular" in ids
    # The magnitudes come from the resolution's tool calls (W sin 30 along the slope, W cos 30 across it), each traced.
    labels = resolved["computed"]["labels"]
    assert labels["W.parallel"] == "24.5 N" and labels["W.perpendicular"] == "42.4 N"
    assert [tool for tool, _ in calls] == ["math_evaluate", "math_evaluate"]
    assert all(c in resolved["numbers_from"] for c in resolved["computed"]["check_ids"])
    assert len(resolved["computed"]["check_ids"]) == 2
    # The derived parts appear only from the step that adds them (cumulative steps, read by the renderer).
    assert resolved["steps"][1]["add"] == [{"element": "components_of", "of": "W"}]


def test_add_must_be_a_kind_element():
    bad = {**INCLINE, "steps": [{"add": [{"element": "tangent_at", "of": "W"}]}]}
    with pytest.raises(VisualError) as raised:
        validate(bad, VisualContext("physics", "O", "S2", knowns={"kn_fw": Fraction(49)}))
    assert raised.value.code == "visual_param_invalid" and "components_of" in raised.value.hint


def _refraction_entry() -> dict:
    pack = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
    entry = yaml.safe_load((pack / "diagrams" / "dgm.phy.refraction_glass_block.v1.yaml").read_text())
    return {**entry, "svg": normalise((pack / entry["svg_path"]).read_text())}


def _library(ref: str, highlight: str) -> dict:
    return {
        "spec_version": 1,
        "type": "library_diagram",
        "ref": ref,
        "params": {},
        "steps": [{"highlight": [highlight]}],
    }


def vsl17_single_retry(tmp_path: Path):
    ref = "dgm.phy.refraction_glass_block.v1"
    wrong, right = _library(ref, "prism"), _library(ref, "incident_ray")
    # The opening turn, then: a wrong part and its correction; then a wrong part twice.
    replies = [tutor(SAFE), tutor(SAFE, visual=[wrong]), tutor(SAFE, visual=[right]), tutor(SAFE, visual=[wrong]),
               tutor(SAFE, visual=[wrong])]  # fmt: skip
    # From S2 the Diagnoser reads a new problem before the Solver (AGT-15).
    diagnosis = {"in_scope": True, "subject": "physics", "topic_ref": None, "kc_refs": [], "question_kind": "diagram",
                 "knowns": [], "unknowns": [], "clarifying_question": None, "misconception_ref": None, "evidence": [],
                 "inference": "", "prerequisite_gap_refs": [], "confidence": "medium"}  # fmt: skip
    script = {"diagnoser": [reply(json.dumps(diagnosis))], "solver": solver_steps(), "checker": checker_steps(),
              "coach": replies}  # fmt: skip

    async def scenario():
        engine, provider = await make_engine(tmp_path, script)
        engine.deps.stage = "S2"
        entry = _refraction_entry()
        sources = {"diagrams": {ref: entry}, "presets": {}, "conventions": {}, "pack_values": {}}
        engine.deps.visual_sources = lambda code: sources
        await engine.start_problem(STATEMENT)
        opening = len(engine.events.frames)
        first = await engine.student_turn("Can you show me how the light goes through?")
        between = len(engine.events.frames)
        second = await engine.student_turn("And again?")
        await close(engine)
        frames = [f["event"] for f in engine.events.frames]
        return provider, frames[opening:between], frames[between:], first, second

    provider, turn1, turn2, first, second = run(scenario())
    coach = [r for r in provider.requests if r.get("_role") == "coach"]
    assert len(coach) == 5  # one opening call, two in each turn: the second failure is not retried
    # Turn 1: the model is told in one sentence what was wrong and that nothing was shown, then the correction draws.
    told = coach[2]["messages"][-1]["content"]
    assert "Nothing was shown" in told and "incident_ray" in told
    drawn = [e for e in turn1 if e["type"] == "visual.spec"]
    assert len(drawn) == 1 and drawn[0]["spec"]["steps"][0]["highlight"] == ["incident_ray"]
    assert drawn[0]["spec"]["ref"] == ref and first.status == "complete"
    # Turn 2: told once, wrong again: the words fallback, no drawing and no third call.
    assert "Nothing was shown" in coach[4]["messages"][-1]["content"]
    assert not [e for e in turn2 if e["type"] == "visual.spec"]
    assert "I can't draw this one" in json.dumps(turn2) and second.status == "complete"


def test_feedback_is_one_sentence_naming_the_fix():
    ctx = VisualContext("physics", "O", "S2", diagrams={"dgm.phy.refraction_glass_block.v1": _refraction_entry()})
    with pytest.raises(VisualError) as raised:
        validate(_library("dgm.phy.refraction_glass_block.v1", "prism"), ctx)
    sentence = feedback(raised.value)
    assert raised.value.retryable and sentence.startswith("Nothing was shown") and sentence.count(".") == 1
    assert "incident_ray" in sentence
    # Resolution failures (stage 7) and size (stage 9) are not the model's to correct.
    assert not VisualError("visual_resolution_failed").retryable and not VisualError("visual_too_large").retryable


def test_renderer_schemas_validate_every_fixture():
    for path in sorted((REPO_ROOT / "packages" / "renderers" / "fixtures" / "visuals").glob("*.json")):
        spec = json.loads(path.read_text())["spec"]
        assert contract_errors("visuals/visual-spec#/$defs/resolved", spec) == [], path.name
        assert kind_param_errors(spec["type"], spec["params"]) == [], path.name
