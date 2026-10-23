"""ARC-27 configuration layers, ARC-28 typed and validated keys, OPS-35 environments."""

import json
import logging
import re
from pathlib import Path

import pytest
from agent_core.config import (
    ConfigError,
    Layer,
    Settings,
    Source,
    check_write,
    environment_source,
    resolve,
    toml_source,
)
from agent_core.config.environments import RELEASE_ENVIRONMENTS, Environment, signing_root_allowed, store_violations
from agent_core.config.keys import declaration

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "docs" / "specification"


def arc27_release_ignores_dev_overrides(tmp_path: Path):
    dev_toml = tmp_path / "dev.toml"
    dev_toml.write_text("net_connect_timeout_s = 9.5\nlow_power = true\n")
    env = environment_source({"JANA_STARTUP_MODEL_WARM_BUDGET_S": "120", "PATH": "/usr/bin"})
    sources = [toml_source(Layer.DEVELOPER, dev_toml), env]

    development = resolve(sources, build="development")
    assert development.settings.net_connect_timeout_s == 9.5
    assert development.settings.startup_model_warm_budget_s == 120
    assert development.provenance["low_power"] is Layer.DEVELOPER

    release = resolve(sources, build="release")
    assert release.settings == Settings()
    assert Layer.DEVELOPER not in release.provenance.values()
    assert release.sha256 != development.sha256


def arc27_policy_restriction_wins(tmp_path: Path):
    adult = Source(Layer.ONLINE_FEATURES, "online-feature store", {"online_cloud_tier": False})

    # The answer-policy key is removed (D86, D87): a write of it is rejected from every layer.
    assert "solution_policy" not in Settings.model_fields
    assert not check_write("solution_policy", "on_request", Layer.PROFILE).ok
    assert not check_write("solution_policy", "on_request", Layer.ONLINE_FEATURES).ok
    # An online-feature switch is never a profile setting (ARC-11, D53, D86).
    assert check_write("online_cloud_tier", True, Layer.PROFILE).reason == "online_feature_switch"
    # Student preferences remain the student's own.
    assert check_write("text_scale", 1.25, Layer.PROFILE).ok

    # A layer that tries to carry the removed key does not load.
    profile = Source(Layer.PROFILE, "settings store (profile)", {"solution_policy": "after_attempt"})
    with pytest.raises(ConfigError, match="unknown key 'solution_policy'"):
        resolve([adult, profile], build="release")
    # No lower layer relaxes the adult's restriction.
    relaxing = Source(Layer.PROFILE, "settings store (profile)", {"online_cloud_tier": True})
    with pytest.raises(ConfigError, match="cannot be set by the profile layer"):
        resolve([adult, relaxing], build="release")
    resolved = resolve([adult, Source(Layer.PROFILE, "settings store (profile)", {"text_scale": 1.5})], "release")
    assert resolved.settings.online_cloud_tier is False
    assert resolved.provenance["online_cloud_tier"] is Layer.ONLINE_FEATURES


def arc27_safety_layer_restrict_only(caplog: pytest.LogCaptureFixture):
    adult = Source(Layer.ONLINE_FEATURES, "online-feature store", {"online_downloads": True})
    safety = Source(
        Layer.SAFETY,
        "safety-config.json (signed)",
        {
            "online_cloud_tier": True,  # would enable a feature: ignored
            "online_downloads": False,  # withdraws a feature: applies
        },
    )
    with caplog.at_level(logging.WARNING):
        resolved = resolve([adult, safety], build="release")
    assert resolved.settings.online_cloud_tier is False
    assert resolved.settings.online_downloads is False and resolved.provenance["online_downloads"] is Layer.SAFETY
    assert len(resolved.ignored) == 1
    assert sum("would relax" in r.message for r in caplog.records) == 1
    with pytest.raises(ConfigError, match="unknown key 'solution_policy'"):
        resolve([Source(Layer.SAFETY, "signed safety settings", {"solution_policy": "on_request"})], "release")
    with pytest.raises(ConfigError, match="cannot be set by the safety layer"):
        resolve([Source(Layer.SAFETY, "safety-config.json", {"text_scale": 1.0})], build="release")


def arc28_unknown_or_out_of_range_key_rejected(tmp_path: Path):
    unknown = tmp_path / "defaults.toml"
    unknown.write_text("net_conect_timeout_s = 5\n")
    with pytest.raises(ConfigError) as error:
        resolve([toml_source(Layer.DEFAULTS, unknown)], build="release")
    assert str(error.value) == f"{unknown}: unknown key 'net_conect_timeout_s'"

    out_of_range = tmp_path / "mid.toml"
    out_of_range.write_text("net_connect_timeout_s = 600\n")
    with pytest.raises(ConfigError) as error:
        resolve([toml_source(Layer.HARDWARE, out_of_range)], build="release")
    assert str(error.value) == f"{out_of_range}: key 'net_connect_timeout_s' = 600 is out of range (0.1..60)"

    profile = Source(Layer.PROFILE, "settings store (profile)", {"text_scale": 2.0})
    with pytest.raises(ConfigError, match=r"'text_scale' = 2.0 is out of range \(1.0..1.5\)"):
        resolve([profile], build="release")

    # Every key is declared once with its type, default, allowed layers and the requirement it serves.
    documents = [*SPEC.glob("*.md"), *(REPO / "docs" / "product").glob("*.md")]
    text = "\n".join(p.read_text() for p in documents)
    requirement_ids = set(re.findall(r"^### ([A-Z0-9]{3}-\d{2}) ", text, re.MULTILINE))
    for name, field in Settings.model_fields.items():
        decl = declaration(name)
        assert set(str(decl["serves"]).split(", ")) <= requirement_ids, name
        assert decl["layers"] and int(Layer.DEFAULTS) in decl["layers"], name
        assert field.default is not None, name


def ops35_release_refuses_test_root():
    assert RELEASE_ENVIRONMENTS == {Environment.PILOT, Environment.PRODUCTION}
    for environment in RELEASE_ENVIRONMENTS:
        assert signing_root_allowed(environment, "release")
        assert not signing_root_allowed(environment, "test")
        assert not signing_root_allowed(environment, "staging")
    assert signing_root_allowed(Environment.DEV, "test")
    assert not signing_root_allowed(Environment.DEV, "release")
    assert signing_root_allowed(Environment.STAGING, "staging")


def ops35_no_production_data_in_staging(tmp_path: Path):
    store = tmp_path / "staging-store"
    (store / "events").mkdir(parents=True)
    (store / "profiles.json").write_text(json.dumps([
        {"synthetic": True, "display_name": "Test Student A"},
        {"origin_env": "staging", "display_name": "Staff test account"},
    ]))  # fmt: skip
    (store / "events" / "log.jsonl").write_text(
        json.dumps({"synthetic": True, "type": "session_started"}) + "\n"
        + json.dumps({"origin_env": "dev", "type": "attempt"}) + "\n"
    )  # fmt: skip
    assert store_violations(store, Environment.STAGING) == []

    (store / "events" / "import.jsonl").write_text(
        json.dumps({"origin_env": "production", "type": "attempt"}) + "\n"
        + json.dumps({"origin_env": "pilot", "type": "hint"}) + "\n"
        + json.dumps({"type": "attempt"}) + "\n"
    )  # fmt: skip
    assert store_violations(store, Environment.STAGING) == [
        "events/import.jsonl#0: record from production in staging",
        "events/import.jsonl#1: record from pilot in staging",
        "events/import.jsonl#2: record from an unknown origin in staging",
    ]
    assert "profiles.json#1: record from staging in dev" in store_violations(store, Environment.DEV)
