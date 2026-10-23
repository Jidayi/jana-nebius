"""Item quantities extracted for misconception signatures and proved by tool (CUR-18, ASM-06, VER-12, D90), the edit
they make through the pipeline (CUR-19) and the bank's rule for edited records (CUR-22).

Items here are copies of pack items with their quantities removed, or synthetic items; nothing is student work."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.contracts import document
from agent_core.engine.marking import mark
from agent_core.engine.signatures import SignatureContext
from jana_tools import marking_golden as golden
from pack_builder import api, heldout, proposals
from pack_builder import quantities as qty
from pack_builder import source as tree
from pack_builder.accounts import Accounts, AuditLog
from test_m8_authoring import Repo
from test_m8_authoring import repo as authoring_repo  # noqa: F401 - the authoring repository fixture

REPO = Path(__file__).resolve().parents[3]
CURRICULUM = REPO / "content" / "curriculum"
SETTINGS = Settings()


def _library() -> dict[str, dict[str, Any]]:
    return {str(r.record["id"]): r.record for d in api.pack_dirs(CURRICULUM)
            for r in tree.read_pack(d)[1]["misconceptions"]}  # fmt: skip


LIBRARY = _library()


def _item(item_id: str) -> dict[str, Any]:
    """A pack item as its source states it, without quantities (the state before extraction)."""
    subject = item_id.split(".")[1]
    record = yaml.safe_load((CURRICULUM / subject / "o" / "items" / f"{item_id}.yaml").read_text())
    record.pop("quantities", None)
    return dict(record)


def _numeric(value: str, unit: str | None, check_id: str = "chk_test_ans") -> dict[str, Any]:
    return {"kind": "numeric", "value": value, "unit": unit, "unit_policy": "equivalent" if unit else "none",
            "tolerance": {"mode": "relative", "value": 0.005}, "check_id": check_id}  # fmt: skip


def _synthetic(stem: str, steps: list[dict[str, Any]], checks: dict[str, Any], answer: dict[str, Any],
               misconceptions: list[str], subject: str = "phy") -> dict[str, Any]:  # fmt: skip
    return {"id": f"itm.{subject}.o.test.0001", "version": "0.1.0", "type": "numeric", "subject": subject,
            "level": "o", "kc_ids": [f"kc.{subject}.o.test.one"], "stem": stem,
            "parts": [{"id": "a", "prompt": "Find it.", "marks": 1, "answer": answer, "hints": [],
                       "misconception_ids": misconceptions}],
            "solution": {"steps": steps}, "checks": checks,
            "review": {"status": "published", "reviewers": []}}  # fmt: skip


def _misconception(mc_id: str, expression: str, subject: str = "phy") -> dict[str, Any]:
    return {"id": mc_id, "kc_ids": [f"kc.{subject}.o.test.one"],
            "signatures": [{"kind": "answer_transform", "expression": expression}]}  # fmt: skip


def _live(outcome: qty.ItemOutcome) -> set[str]:
    return {s.misconception_id for s in outcome.live}


# --- reading the item's own structure -------------------------------------------------------------------------------


def test_cur18_quantities_from_the_solution_formula() -> None:
    """`N = A - Z = 241 - 95` binds A and Z; the key recomputes from them and each listed signature fires apart from
    the key."""
    outcome = qty.extract(_item("itm.phy.o.atom.0001"), LIBRARY, SETTINGS)
    assert outcome.quantities == {"A": "241", "Z": "95"}
    assert outcome.recompute == {"a": "(A - Z)"}
    assert _live(outcome) == {"mc.phy.o.neutrons_equal_nucleon_number", "mc.phy.o.protons_neutrons_assumed_equal",
                              "mc.phy.o.nuclide_numbers_added"}  # fmt: skip
    assert {s.value for s in outcome.live} == {"241", "95", "336"}


def test_cur18_quantities_formula_in_an_earlier_step() -> None:
    """`A = 2\\pi rh` and then `A = 2 \\times \\pi \\times 4 \\times 7`: the same left side ties the formula to its
    numbers."""
    item = _synthetic("A cylinder has radius 4 cm and height 7 cm.",
                      [{"n": 1, "latex": "A = 2\\pi rh"},
                       {"n": 2, "latex": "A = 2 \\times \\pi \\times 4 \\times 7 = 176\\ \\text{cm}^2",
                        "check_id": "chk_test_ans"}],
                      {"chk_test_ans": {"tool": "math_evaluate", "args": {"expression": "2*pi*4*7", "sf": 3}}},
                      _numeric("176", "cm^2"), ["mc.mth.o.test_radius_not_doubled"], "mth")  # fmt: skip
    library = {"mc.mth.o.test_radius_not_doubled": _misconception("mc.mth.o.test_radius_not_doubled", "pi*r*h", "mth")}
    outcome = qty.extract(item, library, SETTINGS)
    assert outcome.quantities == {"h": "7", "r": "4"}
    assert outcome.live[0].value == "87.9645943005"


def test_cur18_quantities_never_matched_by_position() -> None:
    """A solution that writes only numbers names no symbol: two numbers in the stem are never assigned by their
    order."""
    item = _synthetic("A charge of 45 C flows in 90 s.",
                      [{"n": 1, "latex": "\\frac{45}{90} = 0.5\\ \\text{A}", "check_id": "chk_test_ans"}],
                      {"chk_test_ans": {"tool": "math_evaluate", "args": {"expression": "45/90"}}},
                      _numeric("0.5", "A"), ["mc.phy.o.test_multiplied"])  # fmt: skip
    outcome = qty.extract(item, {"mc.phy.o.test_multiplied": _misconception("mc.phy.o.test_multiplied", "Q*t")})
    assert outcome.quantities == {}
    assert outcome.symbols == {"Q": qty.UNBOUND, "t": qty.UNBOUND}


def test_cur18_misconception_formula_never_binds() -> None:
    """A misconception's own formula is never matched against the key's computation: `F*A` has the shape of
    `1500*10` (mass times g) inside the key, but those are not a force and an area."""
    item = _synthetic("A car of mass 1500 kg rests on tyres of total area 0.1 m². Take g = 10 N/kg.",
                      [{"n": 1, "latex": "p = \\frac{1500 \\times 10}{0.1} = 150000\\ \\text{Pa}",
                        "check_id": "chk_test_ans"}],
                      {"chk_test_ans": {"tool": "math_evaluate", "args": {"expression": "1500*10/0.1"}}},
                      _numeric("150000", "Pa"), ["mc.phy.o.test_force_times_area"])  # fmt: skip
    library = {"mc.phy.o.test_force_times_area": _misconception("mc.phy.o.test_force_times_area", "F*A")}
    assert qty.extract(item, library).quantities == {}


# --- refusing what does not verify ----------------------------------------------------------------------------------


def test_cur18_quantities_refuse_a_converted_unit() -> None:
    """`m = 45 g = 0.045 kg` and `p = mv = 0.045 \\times 25`: the solution reads m two ways, so m is not given (the
    stem's 45 would make `m*v^2/2` predict a value no student gives)."""
    outcome = qty.extract(_item("itm.phy.o.momentum.0010"), LIBRARY, SETTINGS)
    assert outcome.quantities == {}
    assert outcome.symbols["m"] == qty.CONFLICT


def test_cur18_signature_scale_against_the_key_unit() -> None:
    """`r/T` over km and days is a speed, but not the number in km/s a student gives: refused. `pi*r^2/T` is not a
    speed; the stem's units are then what matters, and days for km/s are a conversion: refused too."""
    outcome = qty.extract(_item("itm.phy.o.solar_system.0016"), LIBRARY, SETTINGS)
    assert outcome.quantities == {}
    assert {s.reason for s in outcome.signatures} == {qty.SCALE}


def test_cur18_quantities_scale_of_percent() -> None:
    """A percentage is a number in % in the stem: `cost * rate` over $7900 and 30% is not 30% of the cost."""
    assert not qty.scale_kept("cost * rate", {"cost": "7900", "rate": "30"}, {"cost": "currency", "rate": "percent"},
                              "$", qty.Decimal("237000"), True)  # fmt: skip
    assert qty.scale_kept("x/2", {"x": "120"}, {"x": "kBq"}, "kBq", qty.Decimal("60"), False)
    assert qty.scale_kept("p1", {"p1": "160"}, {"p1": "kPa"}, "cm^3", qty.Decimal("160"), True)
    assert not qty.scale_kept("p1", {"p1": "160"}, {"p1": "kPa"}, "cm^3", qty.Decimal("160"), False)


def test_cur18_signature_equal_to_the_key_is_not_live() -> None:
    """A transform that gives the key would describe a right answer: it is reported, never made live."""
    item = _synthetic("A torch beam meets a mirror at an angle of incidence of 30°.",
                      [{"n": 1, "latex": "r = i = 30^\\circ", "check_id": "chk_test_ans"}],
                      {"chk_test_ans": {"tool": "math_evaluate", "args": {"expression": "30"}}},
                      _numeric("30", None), ["mc.phy.o.test_same", "mc.phy.o.test_from_surface"])  # fmt: skip
    library = {"mc.phy.o.test_same": _misconception("mc.phy.o.test_same", "i"),
               "mc.phy.o.test_from_surface": _misconception("mc.phy.o.test_from_surface", "90 - i")}  # fmt: skip
    outcome = qty.extract(item, library)
    reasons = {s.misconception_id: s.reason for s in outcome.signatures}
    assert reasons == {"mc.phy.o.test_same": qty.EQUALS_KEY, "mc.phy.o.test_from_surface": None}
    assert outcome.quantities == {"i": "30"}


def test_cur18_quantities_unit_must_fit_the_symbol() -> None:
    """The same number stated as a length and as g's value: g takes the one in N/kg; a force never takes a mass."""
    assert qty.fits("phy", "g", "N/kg") and not qty.fits("phy", "g", "cm")
    assert not qty.fits("phy", "F", "kg") and qty.fits("phy", "F", "kN")
    assert qty.fits("mth", "x", "cm") and qty.fits("phy", "m", None)


def test_cur18_quantity_name_limit_from_contract() -> None:
    """The name limit is the contract's (D91 widened it to 32): `profit_for_the_year` is bound like any name, and a
    signature over a name the contract's pattern does not allow leaves its item out of the run, listed."""
    pattern = document("content/content-pack")["$defs"]["Item"]["properties"]["quantities"]["propertyNames"]
    assert qty.name_pattern().pattern == pattern["pattern"]
    assert qty.name_limit() == 32
    assert qty.allowed_name("a" * 32) and not qty.allowed_name("a" * 33)
    item = _synthetic("Profit for the year was $5000 and drawings were $1200.",
                      [{"n": 1, "latex": "\\text{drawings} = 1200", "check_id": "chk_test_ans"}],
                      {"chk_test_ans": {"tool": "math_evaluate", "args": {"expression": "5000 - 1200"}}},
                      _numeric("3800", "$"), ["mc.acc.o.test_drawings"], "acc")  # fmt: skip
    library = {"mc.acc.o.test_drawings": _misconception("mc.acc.o.test_drawings", "profit_for_the_year + drawings",
                                                        "acc")}  # fmt: skip
    planned = qty.plan([item], library)
    assert planned.long_names == {}
    assert planned.write == {item["id"]: {"drawings": "1200", "profit_for_the_year": "5000"}}
    too_long = "profit_for_the_year_before_any_drawings"
    library["mc.acc.o.test_drawings"] = _misconception("mc.acc.o.test_drawings", f"{too_long} + drawings", "acc")
    planned = qty.plan([item], library)
    assert planned.long_names == {item["id"]: [too_long]} and planned.write == {}


def test_cur18_check_arguments_bind() -> None:
    """A tool check that names a quantity as its argument (`acc_ratios` with `closing_inventory: '7600'`) binds it; a
    key in a unit word the marker ignores (`times`, `unit_policy: none`) is a pure number."""
    outcome = qty.extract(_item("itm.acc.o.ratios.0034"), LIBRARY, SETTINGS)
    assert outcome.quantities == {"closing_inventory": "7600", "cost_of_sales": "58000"}
    assert "check" in outcome.sources["closing_inventory"]
    assert _live(outcome) == {"mc.acc.o.rat_closing_inventory_used"}
    assert qty.key_unit_of({"unit": "times", "unit_policy": "none"}) is None
    assert qty.key_unit_of({"unit": "m/s", "unit_policy": "equivalent"}) == "m/s"


# --- a model's proposal, proved by the item --------------------------------------------------------------------------


def test_cur18_model_proposal_proved_by_the_item() -> None:
    """A proposal binds a symbol only where its formula, with the numbers it names, is what the item computes
    (`16 - (-2)`); a formula the item does not compute, or numbers the match does not give, bind nothing."""
    item = _item("itm.phy.o.atom.0004")
    assert qty.extract(item, LIBRARY, SETTINGS).quantities == {}
    assert qty.unbound(qty.extract(item, LIBRARY, SETTINGS)) == ["A", "Z", "q"]
    proposed = {"formulas": {"a": "Z - q"}, "quantities": {"Z": "16", "q": "-2", "A": "32"}}
    outcome = qty.extract(item, LIBRARY, SETTINGS, proposed)
    assert outcome.quantities == {"Z": "16", "q": "-2"} and outcome.sources == {"Z": ["model"], "q": ["model"]}
    assert _live(outcome) == {"mc.phy.o.ion_charge_sign_reversed", "mc.phy.o.ion_charge_ignored"}
    assert outcome.recompute == {"a": "(Z - q)"}
    for wrong in (
        {"formulas": {"a": "q - Z"}, "quantities": {"Z": "16", "q": "-2"}},  # not what the item computes
        {"formulas": {"a": "Z - q"}, "quantities": {"Z": "-2", "q": "16"}},  # numbers swapped
        {"formulas": {"a": "Z * 2"}, "quantities": {"Z": "16"}},  # a formula of its own
        {"quantities": {"Z": "16", "q": "-2"}},
    ):  # a mapping with no formula proves nothing
        assert qty.extract(item, LIBRARY, SETTINGS, wrong).quantities == {}, wrong


def test_cur18_model_proposal_never_overrides_a_reading() -> None:
    """A symbol a deterministic reading binds keeps that binding whatever a proposal says, so an item the extractor
    already verifies is unchanged by any proposal."""
    item = _item("itm.phy.o.atom.0001")
    proposed = {"formulas": {"a": "A - Z"}, "quantities": {"A": "95", "Z": "241"}}
    outcome = qty.extract(item, LIBRARY, SETTINGS, proposed)
    assert outcome.quantities == {"A": "241", "Z": "95"} and "model" not in {s for v in outcome.sources.values()
                                                                              for s in v}  # fmt: skip


class _Provider:
    """A stand-in for the provider: records each request body and answers with a fixed proposal and token counts."""

    def __init__(self, proposal: dict[str, Any], tokens: tuple[int, int] = (600, 80)) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.proposal = proposal
        self.tokens = tokens

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        usage = {"promptTokenCount": self.tokens[0], "candidatesTokenCount": self.tokens[1]}
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(self.proposal)}]}}], "usageMetadata": usage}


MODEL = proposals.Model("gemini", "test-flash", "https://example.test/v1beta", "low", 0.5, 3.0)


def test_cur18_proposal_payload_is_the_item_only() -> None:
    """A request carries the item's stem, numeric parts with keys and checks, and its solution, with the symbol
    names: never its id, review or authoring data, hints or any misconception record."""
    item = _item("itm.phy.o.atom.0004")
    sent = proposals.payload(item, ["Z", "q"])
    assert set(sent) == {"stem", "parts", "solution", "symbols"} and sent["symbols"] == ["Z", "q"]
    assert sent["parts"] == [{"id": "a", "prompt": item["parts"][0]["prompt"],
                              "key": {"value": "18", "check": "16 - (-2)"}}]  # fmt: skip
    text = proposals.request_text(sent)
    for absent in (item["id"], "review", "authoring", "hints", "mc.phy.o", "provenance"):
        assert absent not in text


def test_cur18_proposals_cached_within_budget(tmp_path: Path) -> None:
    """Each answer is cached with the spend the provider's tokens cost; a rerun asks nothing; the budget is checked
    before each request against its worst case and holds over every run against the cache; every request is
    audited and listed in the egress log (AUT-02, AUT-20)."""
    item = _item("itm.phy.o.atom.0004")
    provider = _Provider({"formulas": {"a": "Z - q"}, "quantities": {"Z": "16", "q": "-2"}})
    cache = proposals.Cache(tmp_path / "proposals.json")
    audit = AuditLog(tmp_path / "home")
    egress = tmp_path / "home" / "egress.jsonl"
    run = proposals.propose([(item, ["Z", "q"])], cache, MODEL, provider, heldout.HeldOut(), audit, "author",
                            SETTINGS, egress)  # fmt: skip
    assert run.asked == [item["id"]] and len(provider.bodies) == 1
    assert cache.spend == pytest.approx(MODEL.cost(600, 80))
    assert proposals.Cache(tmp_path / "proposals.json").proposals()[item["id"]]["formulas"] == {"a": "Z - q"}
    assert [e["action"] for e in audit.entries()] == ["ai_propose:quantity_mapping"]
    assert json.loads(egress.read_text())["model"] == "test-flash"
    body = provider.bodies[0]
    assert body["generationConfig"]["maxOutputTokens"] == SETTINGS.quantity_proposal_max_output_tokens
    again = proposals.propose([(item, ["Z", "q"])], cache, MODEL, provider, heldout.HeldOut(), audit, "author",
                              SETTINGS, egress)  # fmt: skip
    assert again.cached == [item["id"]] and len(provider.bodies) == 1, "a rerun costs nothing"
    # The budget: a request whose worst case does not fit what is left is never sent.
    tight = Settings(quantity_proposal_budget_usd=cache.spend + MODEL.cost(1, 0))
    other = _item("itm.phy.o.atom.0003")
    spent = proposals.propose([(other, ["A"])], cache, MODEL, provider, heldout.HeldOut(), audit, "author", tight,
                              egress)  # fmt: skip
    assert spent.unaffordable == [other["id"]] and len(provider.bodies) == 1
    assert spent.report(tight.quantity_proposal_budget_usd)["spend_usd_this_run"] == 0


def test_aut20_proposal_never_sends_held_out(tmp_path: Path) -> None:
    """A request whose text matches a held-out item is blocked before it leaves the machine, and audited."""
    item = _item("itm.phy.o.atom.0004")
    provider = _Provider({})
    forbidden = heldout.HeldOut(frozenset(heldout.item_hashes([item])))
    audit = AuditLog(tmp_path / "home")
    run = proposals.propose([(item, ["Z"])], proposals.Cache(tmp_path / "p.json"), MODEL, provider, forbidden, audit,
                            "author", SETTINGS, tmp_path / "egress.jsonl")  # fmt: skip
    assert run.blocked == [item["id"]] and provider.bodies == []
    assert audit.entries()[-1]["outcome"] == "blocked"


def test_cur18_proposal_needs_the_developer_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The key comes from the environment or a dotenv file only; without it `--propose` stops before any request."""
    monkeypatch.delenv(proposals.KEY_ENV, raising=False)
    with pytest.raises(RuntimeError, match=proposals.KEY_ENV):
        proposals.api_key(tmp_path / "missing.env")
    env = tmp_path / ".env"
    env.write_text(f"OTHER=1\n{proposals.KEY_ENV}=test-key-not-real\n")
    assert proposals.api_key(env) == "test-key-not-real"
    model = proposals.gateway_model()
    assert model.provider == "gemini" and "flash" in model.model_id and model.input_per_m > 0


def test_aut19_model_quantities_record_their_provenance(authoring_repo: Repo, tmp_path: Path) -> None:  # noqa: F811
    """An item given a quantity a proposal bound records the field's AI origin, model, prompt and the tools'
    verification (AUT-19); it promotes like any edit, and a rerun with the same cache writes nothing."""
    repo = authoring_repo
    item_id = _with_atom_item(repo, "itm.phy.o.atom.0004")
    cache = proposals.Cache(tmp_path / "proposals.json")
    provider = _Provider({"formulas": {"a": "Z - q"}, "quantities": {"Z": "16", "q": "-2"}})
    audit = repo.ctx("author").audit
    proposals.propose([(repo.record(item_id), ["Z", "q"])], cache, MODEL, provider, heldout.HeldOut(), audit,
                      "author", SETTINGS, tmp_path / "egress.jsonl")  # fmt: skip
    result = api.quantities(repo.ctx("author"), repo.pack, write=True, cache=cache)["results"][0]
    assert result["written"] == [item_id]
    record = repo.record(item_id)
    assert record["quantities"] == {"Z": "16", "q": "-2"}
    field = record["authoring"]["fields"]["quantities"]
    assert field["origin"] == "ai_accepted" and field["status"] == "passed" and field["model"] == "test-flash"
    assert field["accepted_by"] == Accounts(repo.home).get("author").rev_id and field["inputs"] == [item_id]
    assert record["provenance"]["drafted_with_ai"] and record["provenance"]["ai_model"]
    assert api.promote(repo.ctx("author"), repo.pack, [item_id])["verified"] == [item_id]
    assert api.quantities(repo.ctx("author"), repo.pack, write=True, cache=cache)["results"][0]["written"] == []


# --- reading the stem -----------------------------------------------------------------------------------------------


def test_cur18_stated_numbers() -> None:
    item = {
        "subject": "phy",
        "stem": "Mars orbits at 2.28 × 10⁸ km in 687 days. Give the answer to 3 significant figures.",
        "parts": [{"prompt": "The current is 0.25 A; take g = 9.8 N/kg."}],
    }
    stated = [(str(s.value), s.unit) for s in qty.stated_numbers(item)]
    assert stated == [("228000000.00", "km"), ("687", "day"), ("0.25", "A"), ("9.8", "N/kg")]
    maths = {"subject": "mth", "stem": "Solve $2x + 2y = 0$.", "parts": []}
    assert [(str(s.value), s.unit) for s in qty.stated_numbers(maths)][-1] == ("0", None)
    money = {"subject": "acc", "stem": "Bought for $1,200; rate 30%.", "parts": []}
    assert [(str(s.value), s.unit) for s in qty.stated_numbers(money)] == [("1200", "currency"), ("30", "percent")]


def test_cur18_solution_latex_subset() -> None:
    chains = qty.statements("2(4) + 2y = 0 \\Rightarrow y = -4")
    assert len(chains) == 2
    tokens = qty.segments("F = mg = 50 \\times 9.8 = 490\\ \\text{N}")
    assert [[t.text for t in side] for side in tokens] == [["F"], ["m", "*", "g"], ["50", "*", "9.8"], ["490"]]
    assert tokens[3][0].unit == "N"
    delta = qty.segments("\\Delta\\theta = 45 - 18 = 27\\ ^\\circ\\text{C}")
    assert delta[0][0].text == "dtheta" and delta[2][0].unit == "delta_degC"
    fraction = qty.tree(qty.segments("p_2 = \\frac{p_1V_1}{V_2}")[1])
    assert fraction is not None and qty.render(fraction) == "((p1 * V1) / V2)"
    power = qty.segments("c = 3.0 \\times 10^{8}\\ \\text{m/s}")[1]
    assert [t.text for t in power] == ["3.0e8"]


# --- writing through the pipeline (CUR-19) and banking an edit (CUR-22) ---------------------------------------------


def _with_atom_item(repo: Repo, item_id: str = "itm.phy.o.atom.0001") -> str:
    """The fixture pack plus an atom item and its misconceptions, copied as published records."""
    item = yaml.safe_load((CURRICULUM / "phy" / "o" / "items" / f"{item_id}.yaml").read_text())
    item.pop("quantities", None)
    item.update(version="0.1.0", review={"status": "published", "reviewers": []},
                authoring={"drafted_by": "rev_author_test", "history": ["drafted", "verified", "in_eval_bank",
                                                                        "published"]})  # fmt: skip
    tree.save_record(repo.pack, "items", item)
    for part in item["parts"]:
        for mc_id in part.get("misconception_ids") or []:
            tree.save_record(repo.pack, "misconceptions", LIBRARY[mc_id])
    return str(item["id"])


def test_cur19_quantities_written_as_a_registered_edit(authoring_repo: Repo) -> None:  # noqa: F811
    """`aut quantities --write` saves the verified quantities as an edit: a published record starts a new version at
    `drafted`, the editor is its author, the audit log records it; a second run changes nothing."""
    repo = authoring_repo
    item_id = _with_atom_item(repo)
    before = repo.record(item_id)
    result = api.quantities(repo.ctx("author"), repo.pack, write=True)["results"][0]
    assert result["written"] == [item_id]
    after = repo.record(item_id)
    assert after["quantities"] == {"A": "241", "Z": "95"}
    assert after["review"]["status"] == "drafted"
    assert after["version"] == "0.1.1" and before["version"] == "0.1.0"
    assert after["authoring"]["history"] == [*before["authoring"]["history"], "drafted"]
    assert any(e["action"] == "edit" and e["subject"] == item_id for e in repo.ctx("author").audit.entries())
    again = api.quantities(repo.ctx("author"), repo.pack, write=True)["results"][0]
    assert again["written"] == [] and item_id in again["unchanged"]
    assert repo.record(item_id)["version"] == "0.1.1"


def test_asm15_published_paper_travels_with_its_edited_item(authoring_repo: Repo) -> None:  # noqa: F811
    """A published mock paper that uses an item given quantities is registered as edited with it, so a published
    paper never points at an item whose new version is still in the pipeline; a paper that does not use it stays."""
    repo = authoring_repo
    item_id = _with_atom_item(repo)
    published = {"review": {"status": "published", "reviewers": []},
                 "authoring": {"drafted_by": "rev_author_test",
                               "history": ["drafted", "verified", "in_eval_bank", "published"]}}  # fmt: skip
    for paper_id, used in (("mck.phy.o.0001", item_id), ("mck.phy.o.0002", "itm.phy.o.motion.0001")):
        tree.save_record(repo.pack, "mock_papers", {"id": paper_id, "version": "0.1.0", **published,
                                                    "sections": [{"questions": [{"item_id": used}]}]})  # fmt: skip
    result = api.quantities(repo.ctx("author"), repo.pack, write=True)["results"][0]
    assert result["papers"] == ["mck.phy.o.0001"]
    paper = repo.record("mck.phy.o.0001")
    assert paper["review"]["status"] == "drafted" and paper["version"] == "0.1.1"
    assert repo.record("mck.phy.o.0002")["review"]["status"] == "published"


def test_asm15_edit_carries_its_published_paper(authoring_repo: Repo) -> None:  # noqa: F811
    """`aut edit` on a published item a published mock paper uses registers the paper as edited with it, as
    `aut quantities --write` does: the pack stays buildable (a published paper uses published items only) and the
    paper reaches the next release with its item (CUR-19)."""
    repo = authoring_repo
    item_id = _with_atom_item(repo)
    published = {"review": {"status": "published", "reviewers": []},
                 "authoring": {"drafted_by": "rev_author_test",
                               "history": ["drafted", "verified", "in_eval_bank", "published"]}}  # fmt: skip
    for paper_id, used in (("mck.phy.o.0001", item_id), ("mck.phy.o.0002", "itm.phy.o.motion.0001")):
        tree.save_record(repo.pack, "mock_papers", {"id": paper_id, "version": "0.1.0", **published,
                                                    "sections": [{"questions": [{"item_id": used}]}]})  # fmt: skip
    result = api.touch(repo.ctx("author"), item_id)
    assert result["papers"] == ["mck.phy.o.0001"]
    paper = repo.record("mck.phy.o.0001")
    assert paper["review"]["status"] == "drafted" and paper["version"] == "0.1.1"
    assert paper["authoring"]["authors"] == [Accounts(repo.home).get("author").rev_id]
    assert repo.record("mck.phy.o.0002")["review"]["status"] == "published"
    assert any(e["action"] == "edit" and e["subject"] == "mck.phy.o.0001" for e in repo.ctx("author").audit.entries())
    assert api.touch(repo.ctx("author"), item_id)["papers"] == [], "a paper already in the pipeline is not edited twice"


def test_cur19_quantities_dry_run_writes_nothing(authoring_repo: Repo) -> None:  # noqa: F811
    repo = authoring_repo
    item_id = _with_atom_item(repo)
    result = api.quantities(repo.ctx("author"), repo.pack)["results"][0]
    assert result["write"] == {item_id: {"A": "241", "Z": "95"}} and result["written"] == []
    assert "quantities" not in repo.record(item_id)


def test_cur22_banked_record_edit_never_held_out(authoring_repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """A new version of a published record goes back to the bank whatever the held-out share, and naming it as held
    out is refused: its earlier version has been seen, so it cannot be an unseen evaluation item."""
    repo = authoring_repo
    item_id = _with_atom_item(repo)
    api.quantities(repo.ctx("author"), repo.pack, write=True)
    edited = repo.record(item_id)
    history = [*edited["authoring"]["history"], "verified"]  # as `aut promote` leaves it
    tree.save_record(repo.pack, "items", {**edited, "review": {**edited["review"], "status": "verified"},
                                          "authoring": {**edited["authoring"], "history": history}})  # fmt: skip
    monkeypatch.delenv(heldout.KEY_ENV, raising=False)  # no sealing can happen: nothing is held out
    with pytest.raises(ValueError, match="never held out"):
        api.bank(repo.ctx("lead"), repo.pack, held_out_share=1.0, held_ids=[item_id])
    moved = api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)
    assert item_id in moved["in_eval_bank"] and item_id not in moved["held_out"]
    assert repo.record(item_id)["authoring"]["history"][-3:] == ["drafted", "verified", "in_eval_bank"]


# --- the marker names the misconception (end to end) ----------------------------------------------------------------


def test_cur18_extracted_quantities_name_the_misconception() -> None:
    """An item given quantities by the extractor: a wrong answer equal to a listed `answer_transform` signature gets
    that misconception from the marker, the right answer gets none, and without the quantities nothing fires."""
    item = _item("itm.phy.o.electrical_quantities.0016")
    outcome = qty.extract(item, LIBRARY, SETTINGS)
    assert outcome.quantities == {"I": "0.4", "t": "40"}
    marked = {**copy.deepcopy(item), "quantities": outcome.quantities}
    context = SignatureContext(misconceptions=list(LIBRARY.values()))

    def run(answer: str) -> Any:
        return asyncio.run(mark(marked, "a", answer, golden.convert, SETTINGS, golden.run_tool, signatures=context))

    wrong = run("0.01 C")  # I/t: the current divided by the time
    assert wrong.outcome == "incorrect"
    assert wrong.misconception_id == "mc.phy.o.charge_current_divided_by_time"
    right = run("16 C")
    assert right.outcome == "correct" and right.misconception_id is None
    without = asyncio.run(mark(item, "a", "0.01 C", golden.convert, SETTINGS, golden.run_tool, signatures=context))
    assert without.misconception_id is None  # before extraction the signature could not fire


# --- the packs ------------------------------------------------------------------------------------------------------


def test_cur18_pack_quantities_reverify() -> None:
    """Every pack item that carries quantities verifies again: a fresh run gives it the same quantities and would
    write nothing, and no item carries quantities the tool would not give (the run is idempotent). Model proposals
    are read from the committed cache, so this asks no model; an item a proposal bound says so in its field record."""
    carried = 0
    cache = proposals.Cache(CURRICULUM.parent / "agent" / "drafting" / "quantity-proposals.json")
    for directory in api.pack_dirs(CURRICULUM):
        items = [located.record for located in tree.read_pack(directory)[1]["items"]]
        planned = qty.plan(items, LIBRARY, SETTINGS, proposals=cache.proposals())
        for outcome in planned.outcomes:
            if outcome.item_id in planned.unchanged and any("model" in s for s in outcome.sources.values()):
                record = next(r for r in items if r["id"] == outcome.item_id)
                assert record["authoring"]["fields"]["quantities"]["origin"] == "ai_accepted", outcome.item_id
        assert planned.write == {}, directory
        assert {str(i["id"]) for i in items if i.get("quantities")} == set(planned.unchanged), directory
        carried += len(planned.unchanged)
    assert carried > 0


def test_proposal_cache_stays_out_of_the_authoring_sources() -> None:
    """The proposal cache is tooling state, not a source: kept outside content/curriculum, the studio still opens the
    real workspace (its preflight refuses any source over its size limit) (AUT-02, CUR-18)."""
    from pack_builder.studio import Workspace

    assert not (CURRICULUM / "quantity-proposals.json").exists()
    Workspace(CURRICULUM.parent.parent)  # raises if any authoring source breaks the preflight
