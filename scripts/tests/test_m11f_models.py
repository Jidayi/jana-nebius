"""M11.f: the recommendations file and the bake-off record behind each model's class (MDL-27, MDL-28).

The schema is the proposed `agents/model-recommendations` contract (contract-additions-m11.json), applied to a local
copy of the contracts. Bake-off results here are the synthetic ones of test_m7b_devlab (no model was run to make
them); the shipped file is checked as it is."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from agent_core.config.environments import Environment
from agent_core.router.capabilities import (
    RECOMMENDATIONS,
    pack_recommendation_problems,
    pack_recommendations,
    recommendation_errors,
)
from agent_core.store.model_packs import ModelManifestError, sign_manifest, verify_manifest
from jana_tools.fakes.models import MODEL_KEY_ID, install
from jana_tools.harness import bakeoff
from jana_tools.release.models import bakeoff_errors, release_errors
from signing_service.keys import dev_key
from test_m7b_devlab import _results

SHIPPED = json.loads(RECOMMENDATIONS.read_text())


def _entry(model: str, classes: dict[str, Any]) -> dict[str, Any]:
    template = copy.deepcopy(SHIPPED["models"][0])
    return {**template, "model": model, "classes": classes, "status": "synthetic"}


def mdl27_bakeoff_record_required() -> None:
    report = bakeoff.build(_results(), "bko_test", "2026-10-09")
    assert bakeoff.report_errors(report) == []
    recorded = {"bko_test": report}
    low = report["decision"]["fast"]["low"]
    high = report["decision"]["strong"]["high"]
    backed = {"version": 2, "models": [
        _entry(low, {"low": {"tiers": ["fast"], "bakeoff": "bko_test"}}),
        _entry(high, {"high": {"tiers": ["strong"], "bakeoff": "bko_test"}})]}  # fmt: skip
    assert release_errors(backed, recorded) == []
    # The same models with no record, an unknown record, or a class the record chose another model for.
    for classes, why in (
        ({"low": {"tiers": ["fast"], "bakeoff": None}}, f"{low}@low: no bake-off record"),
        ({"low": {"tiers": ["fast"], "bakeoff": "bko_elsewhere"}}, "(bko_elsewhere not found)"),
        ({"high": {"tiers": ["fast"], "bakeoff": "bko_test"}}, "for the fast tier, not this model"),
    ):
        refused = {"version": 2, "models": [_entry(low, classes)]}
        errors = release_errors(refused, recorded)
        assert any(why in e for e in errors), (why, errors)
    # A record that is not a complete EVL-15 record (no held-out confirmation) backs nothing.
    unconfirmed = copy.deepcopy(_results())
    for model in unconfirmed:
        unconfirmed[model]["held_out"] = {}
    partial = bakeoff.build(unconfirmed, "bko_partial", "2026-10-09")
    refused = {"version": 2, "models": [_entry(low, {"low": {"tiers": ["fast"], "bakeoff": "bko_partial"}})]}
    assert any("not a complete record" in e for e in bakeoff_errors(refused, {"bko_partial": partial}))
    # A model the record excluded on that class (here: it does not fit the minimum laptop) is refused there.
    excluded = {
        "version": 2,
        "models": [_entry("gemma-4-31b", {"low": {"tiers": ["fast"], "bakeoff": "bko_test"}})],
    }
    assert any("did not run it on this class" in e for e in bakeoff_errors(excluded, recorded))
    # The shipped file today: D6's assignments rest on a provisional bake-off with no complete record, so the
    # release check refuses every one of them.
    shipped = release_errors()
    assert {e.split(":")[0] for e in shipped} == {"qwen3-vl-8b@low", "gemma-4-12b@mid", "gemma-4-12b@high"}
    assert all("no bake-off record" in e for e in shipped)


def mdl28_recommendations_complete(tmp_path: Path) -> None:
    # The bundled file: every entry complete and valid.
    assert recommendation_errors(SHIPPED) == []
    # Each MDL-28 field is required: without any one of them an entry is refused, naming it.
    for field in ("family", "licence", "context_for_agents", "max_output", "thinking", "sampling",
                  "template_quirks", "feature_rejections"):  # fmt: skip
        broken = copy.deepcopy(SHIPPED)
        del broken["models"][0][field]
        assert any(field in e for e in recommendation_errors(broken)), field
    no_solver = copy.deepcopy(SHIPPED)
    del no_solver["models"][0]["sampling"]["solver"]
    assert any("solver" in e for e in recommendation_errors(no_solver))
    # A model pack: the synthetic pack's models have no entry in the bundled file, so it is incomplete there.
    manifest = install(tmp_path / "plain")
    problems = pack_recommendation_problems(manifest)
    assert problems == ["synthetic-large: no recommendations entry", "synthetic-small: no recommendations entry"]
    # The pack carries its own recommendations, signed with its manifest: complete, they are the ones in force.
    own = {"version": 2, "models": [_entry("synthetic-large", {}), _entry("synthetic-small", {})]}
    signed = sign_manifest({**{k: v for k, v in manifest.items() if k != "signature"}, "recommendations": own},
                           dev_key(_purpose()), MODEL_KEY_ID)  # fmt: skip
    verified = verify_manifest(signed, Environment.DEV)
    assert pack_recommendation_problems(verified) == []
    assert pack_recommendations(verified) == own
    # They update only with the pack: changing them breaks the manifest's signature.
    changed = copy.deepcopy(signed)
    changed["recommendations"]["models"][0]["max_output"] = 99999
    try:
        verify_manifest(changed, Environment.DEV)
    except ModelManifestError:
        pass
    else:
        raise AssertionError("a changed recommendations copy must not verify")
    # The bundled contracts carry the schema (D76), so the file validates in this build as it is.
    assert recommendation_errors(SHIPPED) == []
    # A build without the schema cannot pass the file as valid.
    from agent_core.router import capabilities

    adopted = capabilities.CONTRACT
    capabilities.CONTRACT = "agents/no-such-contract"
    try:
        assert "not in this build" in recommendation_errors(SHIPPED)[0]
    finally:
        capabilities.CONTRACT = adopted


def _purpose() -> Any:
    from agent_core.config.trust import Purpose

    return Purpose.MODEL
