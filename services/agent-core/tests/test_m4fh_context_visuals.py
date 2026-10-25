"""M4.f and M4.h: context budgets and compaction (MEM-15 to MEM-17, MEM-19) and the visual spec path (VSL-01, VSL-02,
VSL-09, VSL-12, VSL-13, VSL-15)."""

import asyncio
import copy
import json
import random
import re
from fractions import Fraction
from pathlib import Path

import pytest
from agent_core.assets.visuals import (
    TEXT_ONLY,
    Resolver,
    VisualContext,
    VisualError,
    advertised_kinds,
    kinds,
    render,
    strip_markup,
    validate,
)
from agent_core.config import Settings
from agent_core.engine.compaction import PLACEHOLDER, Compactor, validation_errors
from agent_core.engine.state import BoardStep, Plan, PlanStep, Problem, SessionState
from agent_core.tools.executor import ToolCall, ToolExecutor
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.registry import Registry, register_entries
from agent_core.tools.spec import SessionCtx, ToolMeta, ToolSpec
from agent_core.tools.spill import SpillStore

STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"


def guided_state() -> SessionState:
    state = SessionState("ses_x", hardware_class="low")
    state.problem = Problem("prb_1", STATEMENT, "prb_1#statement")
    state.plan = Plan(
        [PlanStep(1, "v^2 = u^2 + 2as", None, None, None), PlanStep(2, "0 = 14^2 - 2(9.8)s", "10", "m", "chk_A1")],
        "10",
        "m",
        "chk_A1",
    )
    state.check_values["chk_A1"] = [Fraction(10)]
    state.student_lines += [STATEMENT, "v^2 = u^2 + 2as"]
    state.board.steps.append(BoardStep("stp_1", 0, "v^2 = u^2 + 2as", None, "student", "correct", None))
    state.board.steps.append(BoardStep("stp_2", 1, "s = 10", None, "tutor", "final", "chk_A1"))
    return state


def transcript(n: int, chat: bool = False) -> list[dict]:
    out = [{"role": "user", "content": STATEMENT, "kind": "problem"}]
    for k in range(n):
        out.append(
            {"role": "user", "content": f"attempt {k}: " + "working " * 80, "kind": "chat" if chat else "attempt"}
        )
        out.append({"role": "assistant", "content": f"tutor reply {k}", "kind": "tutor"})
        if k % 3 == 0:
            out.append({"role": "tool", "content": '{"value": 1}', "kind": "tool"})
    return out


# --- MEM-15 to MEM-17, MEM-19 ---------------------------------------------------------------------------------------


def mem15_compaction_protects():
    settings = Settings()
    compactor = Compactor(settings)
    history = transcript(30)
    tokens = sum(len(m["content"]) for m in history) // 4
    assert compactor.needed(tokens, 6144)  # past 75% of the low class's context for agents
    sent, record = asyncio.run(compactor.compact(guided_state(), history))
    assert sent[0] == history[0]  # the first student message, verbatim
    assert "<compaction-record>" in sent[1]["content"] and record.after_chars < record.before_chars
    roles = [m["role"] for m in sent]
    assert roles[2] != "tool" and all(r != "tool" or roles[i - 1] in ("assistant", "tool") for i, r in enumerate(roles))
    assert sent[-1] == history[-1] and len(history) == len(transcript(30))  # stored transcript untouched


def mem16_deterministic_sections():
    calls = []

    async def summarise(text: str) -> str:
        calls.append(text)
        return "agreed to work in metres"

    compactor = Compactor(Settings())
    _, record = asyncio.run(compactor.compact(guided_state(), transcript(12), summarise))
    assert calls == [] and record.model_calls == 0  # no free dialogue, no model call
    assert list(record.sections) == [
        "Goal",
        "Constraints",
        "Problem state",
        "Steps done",
        "Student errors seen",
        "Agreements",
        "Exact values",
        "Next step",
    ]
    _, with_chat = asyncio.run(Compactor(Settings()).compact(guided_state(), transcript(12, chat=True), summarise))
    assert with_chat.model_calls == 1 and with_chat.sections["Agreements"] == "agreed to work in metres"


def mem16_exact_values_kept():
    state = guided_state()
    _, record = asyncio.run(Compactor(Settings()).compact(state, transcript(12)))
    for step in state.board.steps:
        if step.check_id:
            assert f"{step.latex} [{step.check_id}]" in record.sections["Exact values"]


def mem17_no_invented_numbers():
    state = guided_state()
    assert validation_errors("We used 10 m from the plan.", state.provenance(), Settings()) == []
    assert "numbers not in working state: 12" in validation_errors("It rose 12 m.", state.provenance(), Settings())[0]

    async def invents(text: str) -> str:
        return "the student agreed the answer is 37 m"

    _, record = asyncio.run(Compactor(Settings()).compact(state, transcript(12, chat=True), invents))
    assert (
        record.sections["Agreements"] == PLACEHOLDER and record.model_calls == 2
    )  # one correction, then the placeholder


def mem19_spill_reference(tmp_path: Path):
    async def big(args, context):
        return "x" * 30_000

    entry = {**register_entries(REGISTER, "S1")["math_parse"][1], "executor": "host"}
    spec = ToolSpec("big_tool", "compute", 1, "S1", "x", {"type": "object"}, ToolMeta.from_register(entry))
    settings = Settings()
    executor = ToolExecutor(Registry({spec.name: spec}), settings, SpillStore(tmp_path))
    executor.host_executors["big_tool"] = big
    executor.grants = {"solver": ["compute:*"]}
    small = SessionCtx(profile="small", subject="physics", session_id="ses_01JZ0000000000000000000001")
    result = asyncio.run(executor.run_one(ToolCall("call_m_1", "big_tool", {}), "solver", small))
    assert len(result["output"]) <= settings.tool_max_result_chars_small
    assert re.fullmatch(r"spill_[A-Za-z0-9]{8,64}", result["meta"]["truncated"]["spill_ref"])


# --- VSL-01, VSL-02, VSL-09 -----------------------------------------------------------------------------------------


def source_examples() -> list[dict]:
    """Synthetic visual requests: a checked force diagram and an approved library diagram."""
    return [
        {
            "spec_version": 1,
            "type": "free_body",
            "params": {
                "object": "block",
                "surface": {"kind": "incline", "incline_deg": 30},
                "forces": [
                    {"id": "W", "name": "Weight", "magnitude": "49 N", "direction_deg": 270},
                    {"id": "R", "name": "Reaction", "magnitude": "42.4 N", "direction_deg": 60},
                ],
            },
            "numbers_from": ["chk_118", "chk_119"],
            "steps": [{"highlight": ["W"]}],
        },
        {
            "spec_version": 1,
            "type": "library_diagram",
            "ref": "dgm.bio.heart.v1",
            "params": {},
            "steps": [{"highlight": ["right_atrium"]}],
        },
    ]


def ctx(**kw) -> VisualContext:
    base = {
        "check_values": {"chk_118": [Fraction(49)], "chk_119": [Fraction(424, 10), Fraction(245, 10)]},
        "diagrams": {
            "dgm.bio.heart.v1": {
                "approved": True,
                "licence": True,
                "parts": ["vena_cava", "right_atrium", "right_ventricle", "pulmonary_artery"],
            }
        },
    }
    return VisualContext(kw.pop("subject", "physics"), "O", kw.pop("stage", "S2"), **{**base, **kw})


def vsl01_inline_svg_stripped():
    text, stripped = strip_markup('Look at this: <svg width="10"><circle r="4"/></svg> Which force is the weight?')
    assert stripped and "<svg" not in text and text.endswith("Which force is the weight?")
    # Through Finalise the stripped markup is logged as a trace entry: see agt-level test below.
    assert strip_markup("No drawing here.") == ("No drawing here.", False)


def vsl01_freeform_fields_rejected():
    for field in ("path", "svg", "points_raw", "html"):
        spec = copy.deepcopy(source_examples()[0])
        spec["params"][field] = "M0 0 L10 10"
        with pytest.raises(VisualError) as raised:
            validate(spec, ctx())
        assert raised.value.code == "visual_unknown_field", field


def vsl02_advertised_kinds_filtered():
    advertised = advertised_kinds("physics", "O", "S2")
    assert "free_body" in advertised
    assert "punnett_square" not in advertised and "born_haber_cycle" not in advertised
    assert advertised_kinds("physics", "O", "S1") == ["knowns_panel", "working_board"]


def vsl02_register_tool_names():
    tools = {t["name"]: t["stage"] for ts in REGISTER["toolsets"].values() for t in ts["tools"]}
    for kind in kinds().values():
        for tool in kind.get("tools", []):
            assert tool in tools, (kind["kind"], tool)
            assert tools[tool] <= kind["stage"], (kind["kind"], tool)


def vsl09_source_examples_validate():
    free_body, heart = source_examples()
    resolved, _ = validate(free_body, ctx())
    assert resolved["type"] == "free_body" and resolved["visual_id"].startswith("vis_")
    resolved, _ = validate(heart, ctx(subject="biology", stage="S3"))
    assert resolved["ref"] == "dgm.bio.heart.v1"


def vsl09_engine_fields_rejected():
    for field, value in (("alt", {"summary": "x", "steps": [], "locale": "en"}), ("computed", {})):
        spec = {**source_examples()[0], field: value}
        with pytest.raises(VisualError) as raised:
            validate(spec, ctx())
        assert raised.value.code == "visual_engine_field", field


# --- VSL-12, VSL-13, VSL-15 -----------------------------------------------------------------------------------------


def vsl12_untraced_force_rejected():
    spec = copy.deepcopy(source_examples()[0])
    spec["params"]["forces"][0]["magnitude"] = "50 N"  # the check says 49 N
    result = render(spec, ctx())
    assert result.resolved is None and result.error == "visual_untraced_number"


def vsl12_fuzz_no_untraced_numbers():
    rng = random.Random(12)
    traced = {Fraction(49), Fraction(424, 10), Fraction(245, 10)}
    rendered_untraced = 0
    for _ in range(1000):
        spec = copy.deepcopy(source_examples()[0])
        for force in spec["params"]["forces"]:
            if rng.random() < 0.5:
                force["magnitude"] = f"{round(rng.uniform(1, 99), rng.choice([0, 1, 2]))} N"
        result = render(spec, ctx())
        if result.resolved is not None:
            for force in result.resolved["params"]["forces"]:
                shown = Fraction(force["magnitude"].split()[0])
                if not any(abs(shown - t) <= Fraction(1, 10**9) or _rounds_to(t, force["magnitude"]) for t in traced):
                    rendered_untraced += 1
    assert rendered_untraced == 0


def _rounds_to(value: Fraction, written: str) -> bool:
    from decimal import ROUND_HALF_UP, Decimal

    number = written.split()[0]
    decimals = len(number.split(".")[1]) if "." in number else 0
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP) == Decimal(number)


def vsl12_label_claim_binding():
    spec = {**copy.deepcopy(source_examples()[0]), "caption": "2 - 2 = 4", "numbers_from": ["chk_118", "chk_sum"]}
    claims = {"chk_sum": "2+2=4"}
    values = {"chk_118": [Fraction(49)], "chk_sum": [Fraction(2), Fraction(4)], "chk_119": [Fraction(424, 10)]}
    context = ctx(check_values=values, check_claims=claims)
    with pytest.raises(VisualError) as raised:
        validate({**spec, "params": {**spec["params"], "forces": spec["params"]["forces"][:1]}}, context)
    assert raised.value.code == "visual_untraced_number"
    honest = {**spec, "caption": "2 + 2 = 4", "params": {**spec["params"], "forces": spec["params"]["forces"][:1]}}
    assert validate(honest, context)[0]["caption"] == "2 + 2 = 4"


def vsl13_resolution_deterministic():
    calls = []

    def tools(spec):
        calls.append(spec["type"])
        return {"components": {"W.parallel": "24.5 N", "W.perpendicular": "42.4 N"}}

    resolver = Resolver(tools)
    spec = source_examples()[0]
    first, _ = validate(spec, ctx(), resolver)
    second, _ = validate(copy.deepcopy(spec), ctx(), resolver)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True) and calls == ["free_body"]


def vsl15_error_code_fixtures():
    base = source_examples()[0]
    fixtures = {
        "visual_unparseable": "{not json",
        "visual_envelope_invalid": {**base, "labels": "sideways"},
        "visual_engine_field": {**base, "visual_id": "vis_" + "0" * 26},
        "visual_unknown_field": {**base, "colour": "red"},
        "visual_kind_unknown": {**base, "type": "heart_3d"},
        "visual_kind_not_enabled": {**base, "type": "punnett_square"},
        "visual_param_invalid": {**base, "params": {"object": "block"}},
        "visual_ref_missing": {"spec_version": 1, "type": "library_diagram", "ref": "dgm.bio.lung.v1", "params": {}},
        "visual_ref_unapproved": {"spec_version": 1, "type": "library_diagram", "ref": "dgm.bio.eye.v1", "params": {}},
        "visual_part_unknown": {**base, "steps": [{"highlight": ["Z"]}]},
        "visual_untraced_number": {**base, "numbers_from": []},
        "visual_too_large": {
            **base,
            "caption": "x" * 120,
            "params": {**base["params"], "forces": base["params"]["forces"]},
            "steps": [{"highlight": ["W"]}] * 20,
        },
    }
    context = ctx(stage="S3", diagrams={"dgm.bio.eye.v1": {"approved": False, "licence": True, "parts": []}})
    context.subject = "physics"
    for code, request in fixtures.items():
        local = context
        if code.startswith("visual_ref"):
            local = ctx(subject="biology", stage="S3", diagrams=context.diagrams)
        if code == "visual_too_large":
            local = ctx(max_resolved_bytes=500)
        with pytest.raises(VisualError) as raised:
            validate(request, local)
        assert raised.value.code == code, (code, raised.value)
    # Resolution failures are codes too.
    with pytest.raises(VisualError) as raised:
        validate(base, ctx(), Resolver(lambda spec: (_ for _ in ()).throw(RuntimeError("worker down"))))
    assert raised.value.code == "visual_resolution_failed"


def vsl15_unknown_part_repaired():
    spec = {**source_examples()[0], "steps": [{"highlight": ["W", "Q"]}]}
    resolved, repairs = validate(spec, ctx())
    assert (
        resolved["steps"][0]["highlight"] == ["W"] and "part:Q dropped" in repairs and resolved["status"] == "repaired"
    )


def test_text_only_never_shows_untraced_words():
    result = render({**source_examples()[0], "numbers_from": []}, ctx())
    assert result.status == "text_only" and result.alt.startswith(TEXT_ONLY)
