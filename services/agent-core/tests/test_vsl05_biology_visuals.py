"""The Biology kinds in the engine (VSL-05, VSL-46): each resolves through its contract schema; Punnett classes and
ratios come deterministically from the declared alleles with math_evaluate checks; food webs, pedigrees and gels are
checked and laid out with nothing inferred; cycles and keys come from the pack's science assets; a microscope view's
magnification is a check and its scale bar the library's; a comparison shows only a pair the library declares."""

import copy
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, validate
from agent_core.contracts import errors as contract_errors
from jana_tools.visual_fixtures import _call

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "packages" / "renderers" / "fixtures"
TALL = [
    {"symbol": "T", "phenotype": "tall", "dominance": "dominant"},
    {"symbol": "t", "phenotype": "short", "dominance": "recessive"},
]


def _library() -> dict[str, dict[str, Any]]:
    out = {}
    for path in (FIXTURES / "library").glob("*.json"):
        entry = json.loads(path.read_text())
        out[entry["id"]] = {**entry, "svg": (FIXTURES / "library" / Path(entry["svg_path"]).name).read_text()}
    return out


def _science() -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in (json.loads(p.read_text()) for p in (FIXTURES / "science").glob("*.json"))}


def _resolve(kind: str, params: dict[str, Any], level: str = "A", **extra: Any) -> dict[str, Any]:
    knowns = {k: Fraction(v) for k, v in extra.pop("knowns", {}).items()}
    ctx = VisualContext(
        "biology", level, "S3", knowns=knowns, diagrams=_library(), science_assets=extra.pop("assets", _science())
    )
    request = {"spec_version": 1, "type": kind, "params": params, **extra}
    resolved, _ = validate(request, ctx, Resolver(resolver(_call("vsl05"))))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    assert contract_errors(f"visuals/kinds/{kind}", resolved["params"]) == []
    return resolved


def _code(kind: str, params: dict[str, Any], **extra: Any) -> str:
    with pytest.raises(VisualError) as error:
        _resolve(kind, params, **extra)
    return error.value.code


def test_vsl05_punnett_monohybrid_ratios():
    resolved = _resolve("punnett_square", {"cross": "monohybrid", "parent1": "Tt", "parent2": "Tt", "alleles": TALL})
    computed = resolved["computed"]
    assert computed["grid"] == [["TT", "Tt"], ["Tt", "tt"]]
    assert computed["labels"] == {"genotype_ratio": "1 : 2 : 1", "phenotype_ratio": "3 : 1"}
    assert [c["probability"] for c in computed["phenotype_classes"]] == ["3/4", "1/4"]
    # Every class probability is a math_evaluate check, listed as the visual's source (N2).
    assert computed["check_ids"] and set(computed["check_ids"]) <= set(resolved["numbers_from"])
    assert "in the ratio 1 : 2 : 1" in resolved["alt"]["summary"]
    # The same request resolves to the same bytes (VSL-13), whatever order the parents write their alleles in.
    again = _resolve("punnett_square", {"cross": "monohybrid", "parent1": "tT", "parent2": "Tt", "alleles": TALL})
    assert again["computed"]["grid"] == computed["grid"]


def test_vsl05_punnett_dihybrid_sex_linked_and_blood_groups():
    seeds = [
        {"symbol": "R", "phenotype": "round", "dominance": "dominant"},
        {"symbol": "r", "phenotype": "wrinkled", "dominance": "recessive"},
        {"symbol": "Y", "phenotype": "yellow", "dominance": "dominant"},
        {"symbol": "y", "phenotype": "green", "dominance": "recessive"},
    ]
    dihybrid = _resolve("punnett_square", {"cross": "dihybrid", "parent1": "RrYy", "parent2": "RrYy", "alleles": seeds})
    assert dihybrid["computed"]["labels"]["phenotype_ratio"] == "9 : 3 : 3 : 1"
    assert len(dihybrid["computed"]["grid"]) == 4
    clotting = [
        {"symbol": "H", "phenotype": "normal clotting", "dominance": "dominant"},
        {"symbol": "h", "phenotype": "haemophilia", "dominance": "recessive"},
    ]
    linked = _resolve(
        "punnett_square", {"cross": "sex_linked", "parent1": "XHXh", "parent2": "XHY", "alleles": clotting}
    )
    assert linked["computed"]["grid"] == [["XHXH", "XHY"], ["XHXh", "XhY"]]
    assert linked["computed"]["labels"]["phenotype_ratio"] == "2 : 1 : 1"
    assert [c["phenotype"] for c in linked["computed"]["phenotype_classes"]] == [
        "normal clotting (female)",
        "normal clotting (male)",
        "haemophilia (male)",
    ]
    blood = [
        {"symbol": "IA", "phenotype": "A", "dominance": "codominant"},
        {"symbol": "IB", "phenotype": "B", "dominance": "codominant"},
        {"symbol": "IO", "phenotype": "O", "dominance": "recessive"},
    ]
    groups = _resolve(
        "punnett_square", {"cross": "multiple_alleles", "parent1": "IAIO", "parent2": "IBIO", "alleles": blood}
    )
    assert [c["phenotype"] for c in groups["computed"]["phenotype_classes"]] == ["A and B", "A", "B", "O"]
    assert groups["computed"]["labels"]["phenotype_ratio"] == "1 : 1 : 1 : 1"


def test_vsl05_punnett_refuses_undeclared_alleles():
    for parents in (("Tt", "Ta"), ("Tt", "TtTt")):
        params = {"cross": "monohybrid", "parent1": parents[0], "parent2": parents[1], "alleles": TALL}
        assert _code("punnett_square", params) == "visual_resolution_failed", parents
    # Two fathers make no sex-linked cross.
    clotting = [{**a, "symbol": s} for a, s in zip(TALL, "Hh", strict=True)]
    params = {"cross": "sex_linked", "parent1": "XHY", "parent2": "XhY", "alleles": clotting}
    assert _code("punnett_square", params) == "visual_resolution_failed"


FOOD_WEB = {
    "organisms": [
        {"id": "grass", "label": "Grass", "trophic_level": 1},
        {"id": "rabbit", "label": "Rabbit", "trophic_level": 2},
        {"id": "fox", "label": "Fox", "trophic_level": 3},
    ],
    "links": [{"from": "grass", "to": "rabbit"}, {"from": "rabbit", "to": "fox"}],
}


def test_vsl46_food_web_checks():
    resolved = _resolve("food_web", FOOD_WEB, level="O")
    assert [p["id"] for p in resolved["parts"]] == [
        "org.grass",
        "org.rabbit",
        "org.fox",
        "link.grass.rabbit",
        "link.rabbit.fox",
    ]
    assert resolved["computed"]["levels"] == [1, 2, 3]
    # Arrows run from food to consumer up the levels; links name organisms of the web; a consumer eats something.
    for links in (
        [{"from": "rabbit", "to": "grass"}, {"from": "rabbit", "to": "fox"}],
        [{"from": "grass", "to": "rabbit"}, {"from": "rabbit", "to": "wolf"}],
        [{"from": "grass", "to": "rabbit"}],
    ):
        assert _code("food_web", {**FOOD_WEB, "links": links}) == "visual_resolution_failed", links


PEDIGREE = {
    "individuals": [
        {"id": "dad", "generation": 1, "sex": "male", "phenotype": "unaffected", "carrier": True},
        {"id": "mum", "generation": 1, "sex": "female", "phenotype": "unaffected", "carrier": None},
        {"id": "kid", "generation": 2, "sex": "unspecified", "phenotype": "affected", "carrier": None},
    ],
    "parents": [{"child": "kid", "parent1": "dad", "parent2": "mum"}],
}


def test_vsl46_pedigree_checks():
    resolved = _resolve("pedigree_chart", PEDIGREE)
    assert resolved["computed"]["labels"] == {"ind.dad": "I-1", "ind.kid": "II-1", "ind.mum": "I-2"}
    # An unknown carrier status stays unknown: nothing is inferred from the affected child.
    assert [p["carrier"] for p in resolved["computed"]["people"]] == [True, None, None]
    assert "Known carriers: I-1." in resolved["alt"]["summary"]
    later = copy.deepcopy(PEDIGREE)
    later["individuals"][0]["generation"] = 2
    missing = {**PEDIGREE, "parents": [{"child": "kid", "parent1": "dad", "parent2": "gran"}]}
    twice = {**PEDIGREE, "parents": PEDIGREE["parents"] * 2}
    for bad in (later, missing, twice):
        assert _code("pedigree_chart", bad) == "visual_resolution_failed"


GEL_KNOWNS = {"kn_bp1000": "1000", "kn_bp500": "500", "kn_bp100": "100"}


def test_vsl46_gel_positions_and_traced_sizes():
    params = {
        "ladder_bp": [100, 1000, 500],
        "lanes": [{"id": "a", "label": "Sample", "fragments_bp": [100, 500, 500]}],
        "migration": "log_size",
    }
    resolved = _resolve("gel_electrophoresis", params, numbers_from=list(GEL_KNOWNS), knowns=GEL_KNOWNS)
    ladder = resolved["computed"]["ladder"]
    assert [b["bp"] for b in ladder] == [1000, 500, 100]
    # Logarithmic: 1000 at the well, 100 furthest, 500 at log(1000/500)/log(1000/100) of the way.
    assert [b["position"] for b in ladder] == [0.0, 0.301, 1.0]
    assert [b["bp"] for b in resolved["computed"]["lanes"][0]["bands"]] == [500, 100]
    # Sizes are the question's givens (N1): a size no known gives is refused.
    assert (
        _code("gel_electrophoresis", {**params, "ladder_bp": [1000, 500, 250]}, numbers_from=list(GEL_KNOWNS),
              knowns=GEL_KNOWNS)
        == "visual_untraced_number"
    )  # fmt: skip
    lanes = params["lanes"] * 2
    assert (
        _code("gel_electrophoresis", {**params, "lanes": lanes}, numbers_from=list(GEL_KNOWNS), knowns=GEL_KNOWNS)
        == "visual_resolution_failed"
    )


def test_vsl46_cycle_and_key_from_science_assets():
    cycle = _resolve("cycle_diagram", {"cycle_id": "dgm.bio.carbon_cycle.v1", "start_stage": "plants"}, level="O")
    assert cycle["parts"][0]["id"] == "stage.plants"
    assert cycle["computed"]["asset"]["id"] == "dgm.bio.carbon_cycle.v1"
    key = _resolve("classification_key", {"key_id": "dgm.bio.vertebrate_key.v1", "start_node": "q_fins"}, level="O")
    assert [p["id"] for p in key["parts"]] == ["node.q_fins", "group.fish", "node.q_dry", "group.reptiles",
                                               "group.amphibians"]  # fmt: skip
    # An id the pack does not have is a missing reference; a definition that breaks the rules is refused.
    assert _code("cycle_diagram", {"cycle_id": "dgm.bio.water_cycle.v1"}) == "visual_ref_missing"
    assert _code("cycle_diagram", {"cycle_id": "dgm.bio.carbon_cycle.v1", "start_stage": "sea"}) == (
        "visual_resolution_failed"
    )
    broken = copy.deepcopy(_science())
    nodes = broken["dgm.bio.vertebrate_key.v1"]["definition"]["nodes"]
    nodes[1]["no"] = "birds"  # birds reached by two paths
    assert _code("classification_key", {"key_id": "dgm.bio.vertebrate_key.v1"}, assets=broken) == (
        "visual_resolution_failed"
    )
    open_cycle = copy.deepcopy(_science())
    links = open_cycle["dgm.bio.carbon_cycle.v1"]["definition"]["links"]
    open_cycle["dgm.bio.carbon_cycle.v1"]["definition"]["links"] = [x for x in links if x["to"] != "air"]
    assert _code("cycle_diagram", {"cycle_id": "dgm.bio.carbon_cycle.v1"}, assets=open_cycle) == (
        "visual_resolution_failed"
    )


MICROSCOPE = {
    "diagram_id": "dgm.bio.onion_cells.v1",
    "image_length_mm": 25,
    "actual_length_um": 250,
    "lengths_from": "kn_drawn",
}


def test_vsl46_microscope_magnification_and_scale():
    knowns = {"kn_drawn": "25", "kn_actual": "250"}
    resolved = _resolve(
        "microscope_view",
        MICROSCOPE,
        level="O",
        ref="dgm.bio.onion_cells.v1",
        numbers_from=["kn_actual"],
        knowns=knowns,
    )
    labels = resolved["computed"]["labels"]
    assert (labels["magnification"], labels["scale_bar"]) == ("×100", "250 µm")
    # The lengths' own source (lengths_from) joins the sources; the magnification is a check.
    assert "kn_drawn" in resolved["numbers_from"] and resolved["computed"]["check_ids"]
    assert [p["id"] for p in resolved["parts"]][-2:] == ["scale_bar", "magnification"]
    # Lengths from the pack must give the entry's own magnification.
    pack = {**MICROSCOPE, "image_length_mm": 50, "lengths_from": "pack:pack.bio.o/diagrams/dgm.bio.onion_cells.v1"}
    assert _code("microscope_view", pack, ref="dgm.bio.onion_cells.v1") in (
        "visual_resolution_failed",
        "visual_untraced_number",
    )
    # The params name the visual's own drawing.
    assert _code("microscope_view", MICROSCOPE, ref="dgm.bio.plant_cell.v1", knowns=knowns) == "visual_param_invalid"


def test_vsl46_comparison_only_declared_pairs():
    params = {"left_ref": "dgm.bio.plant_cell.v1", "right_ref": "dgm.bio.animal_cell.v1", "pair_id": "cells"}
    resolved = _resolve("diagram_comparison", params, level="O", ref="dgm.bio.plant_cell.v1")
    ids = [p["id"] for p in resolved["parts"]]
    assert ids[0] == "left.cell_wall" and "right.nucleus" in ids
    assert {d["left"] for d in resolved["computed"]["differences"]} == {
        "left.cell_wall",
        "left.vacuole",
        "left.chloroplast",
    }
    # Either entry may declare the pair; an undeclared pair is refused.
    swapped = {"left_ref": "dgm.bio.animal_cell.v1", "right_ref": "dgm.bio.plant_cell.v1", "pair_id": "cells"}
    flipped = _resolve("diagram_comparison", swapped, level="O", ref="dgm.bio.animal_cell.v1")
    assert {d["right"] for d in flipped["computed"]["differences"]} == {
        "right.cell_wall",
        "right.vacuole",
        "right.chloroplast",
    }
    unrelated = {"left_ref": "dgm.bio.plant_cell.v1", "right_ref": "dgm.bio.heart.v1", "pair_id": "odd"}
    assert _code("diagram_comparison", unrelated, ref="dgm.bio.plant_cell.v1") == "visual_param_invalid"
