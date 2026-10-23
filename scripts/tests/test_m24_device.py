"""OPS-02/03/10/11/13/28/29: signed offline policy and target decisions."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from agent_core.config import Environment
from agent_core.config.operations import DevicePolicy, TargetDecision
from agent_core.config.trust import Purpose
from jana_tools.release.distribution import fetch_verified
from signing_service.hierarchy import dev_signer, dev_trust

AT = "2026-10-16T00:00:00Z"


def matrix(version=1):
    return {
        "matrix_version": version,
        "channel": "stable",
        "issued_at": AT,
        "apps": [
            {
                "app_version": "1.0.0",
                "status": "supported",
                "released_at": "2026-01-01",
                "supported_until": "2027-07-01",
                "platforms": ["linux_x64"],
                "contracts": dict.fromkeys(
                    (
                        "control_protocol",
                        "api_version",
                        "worker_protocol",
                        "trace_version",
                        "content_pack_format",
                        "model_pack_format",
                        "agent_bundle_schema",
                    ),
                    "1.0",
                ),
                "db_schema_version": 1,
                "agent_bundle_version": "1.0.0",
                "release_record_id": "rel_synthetic_app",
            }
        ],
        "content_packs": [
            {
                "pack_id": "pack.phy.o",
                "version": "1.0.0",
                "manifest_sha256": "a" * 64,
                "app_range": {"min_app_version": "1.0.0"},
                "status": "supported",
                "release_record_id": "rel_synthetic_pack",
            }
        ],
        "model_packs": [],
        "agent_bundles": [],
        "withdrawals": [],
        "known_issues": [],
    }


def signed(kind, body, purpose=Purpose.CONTENT):
    return dev_signer(purpose).sign(kind if purpose is Purpose.CONTENT else "model_manifest", body, now=AT)


def policy(tmp_path):
    return DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())


def entry(kind="tool", target="calculate", action="disable", **extra):
    return {
        "entry_id": f"synthetic-{kind}",
        "target_kind": kind,
        "target": target,
        "action": action,
        "reason_code": "synthetic_drill",
        "incident_id": "inc-synthetic",
        "lift_when": None,
        **extra,
    }


def safety(entries, sequence=1):
    return signed(
        "safety_configuration", {"sequence": sequence, "channel": "stable", "issued_at": AT, "entries": entries}
    )


def ops02_matrix_adopted_offline(tmp_path: Path):
    p = policy(tmp_path)
    root = tmp_path / "usb"
    root.mkdir()
    import json

    (root / "compatibility-matrix.json").write_text(json.dumps(signed("compatibility_matrix", matrix(4))))
    assert p.adopt_folder(root)["matrix"]
    assert policy(tmp_path).matrix()["matrix_version"] == 4
    assert not p.adopt_matrix(signed("compatibility_matrix", matrix(3)))
    bad = signed("compatibility_matrix", matrix(5), Purpose.MODEL)
    assert not p.adopt_matrix(bad)
    assert not DevicePolicy(
        tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust().with_revoked([dev_signer().key_id])
    ).matrix()


def ops02_incompatible_pack_not_offered(tmp_path: Path):
    p = policy(tmp_path)
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)
    assert p.adopt_matrix(signed("compatibility_matrix", matrix()))
    assert p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=2)
    assert not p.offered("content_pack", "unknown", "1.0.0", format_major=1)
    m = matrix(2)
    m["content_packs"][0]["app_range"]["min_app_version"] = "2.0.0"
    p.adopt_matrix(signed("compatibility_matrix", m))
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)


def ops03_unsupported_still_teaches(tmp_path: Path):
    p = policy(tmp_path)
    m = matrix()
    m["apps"][0]["status"] = "unsupported"
    p.adopt_matrix(signed("compatibility_matrix", m))
    assert p.teaching_allowed()
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)


def ops10_usb_kill_switch(tmp_path: Path):
    p = policy(tmp_path)
    folder = tmp_path / "usb"
    folder.mkdir()
    import json

    (folder / "safety-configuration.json").write_text(json.dumps(safety([entry()])))
    assert p.adopt_folder(folder)["safety"]
    assert p.decision("tool", "calculate").action == "allow"
    p.turn_boundary({})
    assert p.decision("tool", "calculate").action == "disable"
    assert policy(tmp_path).decision("tool", "calculate").action == "disable"
    bad = copy.deepcopy(safety([entry()], 2))
    bad["entries"] = []
    assert not p.adopt_safety(bad)
    assert p.decision("tool", "calculate").action == "disable"


def ops10_restrict_only(tmp_path: Path):
    p = policy(tmp_path)
    assert p.adopt_safety(
        safety([entry(), entry("online_feature", "cloud_tier", "enable"), entry("subject", "physics", "disable")])
    )
    rejected = p.turn_boundary({})
    assert len(rejected) == 2
    assert p.decision("tool", "calculate").action == "disable"
    assert p.decision("online_feature", "cloud_tier").action == "allow"
    assert not p.adopt_safety(safety([entry()], 1))


def ops10_entry_lifts_on_fix(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(
        safety([entry("item", "old", "withdraw", lift_when={"artefact_id": "pack.phy.o", "version": "1.0.1"})])
    )
    p.turn_boundary({"pack.phy.o": "1.0.0"})
    assert p.decision("item", "old").action == "withdraw"
    p.turn_boundary({"pack.phy.o": "1.0.1"})
    assert p.decision("item", "old").action == "allow"
    p.retire_item("old")
    assert p.decision("item", "old").action == "withdraw"  # CUR-36 retirement outlives a lifted entry.


def test_policy_ops11_each_target_kind(tmp_path: Path):
    p = policy(tmp_path)
    actions = {
        "item": "withdraw",
        "lesson": "withdraw",
        "worked_example": "withdraw",
        "diagram": "withdraw",
        "visual_kind": "disable",
        "skill": "disable",
        "model_pack": "disable",
        "router_candidate": "disable",
        "tool": "disable",
        "online_feature": "force_off",
        "app_version": "advise_update",
    }
    p.adopt_safety(safety([entry(k, "test", a) for k, a in actions.items()]))
    p.turn_boundary({})
    for kind, action in actions.items():
        decision = p.decision(kind, "test")
        assert isinstance(decision, TargetDecision) and decision.action == action and decision.entry_id
        assert decision.fallback
    assert p.decision("content_pack", "test").action == "allow"
    assert p.decision("tool", "other").action == "allow"


def test_policy_ops28_skill_pin_previous(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("skill", "solve", "pin_previous")]))
    p.turn_boundary({})
    assert p.skill_version("solve", "2.0.0", []) is None
    previous = [{"name": "solve", "version": "1.0.0", "reviewed": True, "sha256": "a" * 64}]
    assert p.skill_version("solve", "2.0.0", previous) == ("1.0.0", "a" * 64)
    assert p.skill_version("solve", "2.0.0", [{**previous[0], "reviewed": False}]) is None


def test_policy_ops29_withdraw_last_model(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("model_pack", "large", "disable")]))
    p.turn_boundary({})
    assert p.model_fallback("large", ["large"], {}) is None
    assert p.model_fallback("large", ["large", "small"], {}) == "small"
    assert p.model_fallback("large", ["large", "base", "small"], {"large": "base"}) == "base"
    assert p.teaching_allowed()


def ops13_origin_failover(tmp_path: Path):
    data = b"synthetic artefact"
    sha = hashlib.sha256(data).hexdigest()
    tried = []

    def fetch(url):
        tried.append(url)
        return b"corrupt" if "primary" in url else data

    seen = []
    path = fetch_verified(
        ("https://primary.invalid", "https://secondary.invalid"),
        "content_pack",
        "pack.phy.o",
        "1.0.0",
        sha,
        tmp_path / "pack",
        fetch,
        lambda body: seen.append(body),
    )
    assert path.read_bytes() == data and len(tried) == 2 and seen == [data]
    with pytest.raises(ValueError):
        fetch_verified(
            ("https://primary.invalid",),
            "content_pack",
            "../escape",
            "1.0.0",
            sha,
            tmp_path / "bad",
            fetch,
            lambda _: None,
        )


def test_ops_safety_contract():
    from agent_core.contracts import validate

    validate("ops/safety-configuration", safety([entry()]))
    validate("ops/safety-configuration#/$defs/Entry", entry())
    with pytest.raises(ValueError):
        validate("ops/safety-configuration#/$defs/Entry", entry("online_feature", "x", "enable"))
    # An entry the device would ignore still leaves the file valid, so its other entries apply (OPS-10, OPS-11).
    validate("ops/safety-configuration", safety([entry(), entry("content_pack", "pack.phy.o", "withdraw")]))


def test_ops_restriction_cannot_be_replaced_with_weaker_entry(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("skill", "solve", "disable")]))
    p.turn_boundary({})
    p.adopt_safety(safety([entry("skill", "solve", "pin_previous")], 2))
    assert p.turn_boundary({})
    assert p.decision("skill", "solve").action == "disable"


def test_ops_model_fallback_does_not_choose_larger_model(tmp_path: Path):
    p = policy(tmp_path)
    assert p.model_fallback("mid", ["large", "mid", "small"], {}) == "small"


def test_ops_multiple_imports_before_boundary_keep_all_restrictions(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("tool", "one", "disable")]))
    p.adopt_safety(safety([entry("model_pack", "two", "disable")], 2))
    p.turn_boundary({})
    assert p.decision("tool", "one").action == "disable"
    assert p.decision("model_pack", "two").action == "disable"


def test_ops_candidate_kit_refuses_stable_install(tmp_path: Path):
    import json

    from agent_core.api.packs import PackDesk
    from agent_core.store.pack_channels import ChannelError

    folder = tmp_path / "kit"
    folder.mkdir()
    (folder / "notes.txt").write_bytes(b"synthetic")
    entry = {"path": "notes.txt", "kind": "documentation", "size_bytes": 9,
             "sha256": hashlib.sha256(b"synthetic").hexdigest()}  # fmt: skip
    listing = signed("usb_kit", {"format": "jana.usb-kit.1", "kit_id": "kit-2026.3.1", "created_at": AT,
                                 "channel": "pilot", "candidate": True, "release_version": "1.0.0-rc.1",
                                 "matrix_version": 1, "files": [entry]})  # fmt: skip
    (folder / "kit.json").write_text(json.dumps(listing))
    desk = PackDesk(tmp_path / "device", Environment.DEV, "1.0.0", lambda _: None, trust=dev_trust(), channel="stable")
    with pytest.raises(ChannelError, match="candidate"):
        desk.install_source({"path": str(folder)}, "job_synthetic")


def test_ops_model_offers_obey_adopted_matrix(tmp_path: Path):
    from agent_core.api.packs import PackDesk

    p = policy(tmp_path)
    desk = PackDesk(
        tmp_path / "device",
        Environment.DEV,
        "1.0.0",
        lambda _: None,
        trust=dev_trust(),
        channel="stable",
        operations=p,
        available=lambda: [{"model_pack_id": "mp.unknown.low", "manifest": {"manifest_version": 1}}],
    )
    assert desk._offers() == []


def test_ops_kit_builder_uses_stable_inventory_and_hashes(tmp_path: Path):
    from dataclasses import replace
    from datetime import UTC, datetime

    from jana_tools.release.distribution import KitArtifact, build_kit
    from jana_tools.release.operations import FULL_KIT_PARTS, Candidate, Ring

    files = []
    for category in FULL_KIT_PARTS:
        source = tmp_path / f"{category}.bin"
        source.write_bytes(f"synthetic {category}".encode())
        files.append(
            KitArtifact(
                category,
                "content_pack",
                source,
                source.name,
                hashlib.sha256(source.read_bytes()).hexdigest(),
                "stable",
                "R3",
            )
        )
    c = Candidate("app", "1.0.0", "a" * 64, "stable")
    ring = Ring("1.0.0", "R3", datetime(2026, 10, 16, tzinfo=UTC))

    def sign(doc):
        return signed("usb_kit", doc)

    output = build_kit(c, ring, "school", files, tmp_path / "output", "kit-2026.3.1", 1, AT, sign)
    from agent_core.store.pack_channels import kit_listing

    listing = kit_listing(output, Environment.DEV, dev_trust())
    assert len(listing.files) == len(files) and listing.matrix_version == 1
    assert all(entry.size_bytes == (output / entry.path).stat().st_size for entry in listing.files)
    with pytest.raises(ValueError):
        build_kit(
            c,
            ring,
            "school",
            [replace(files[0], channel="pilot"), *files[1:]],
            tmp_path / "refused",
            "kit-2026.3.2",
            1,
            AT,
            sign,
        )
    assert not (tmp_path / "refused").exists()


def test_ops_kit_builder_checks_the_kit_contract_before_signing(tmp_path: Path):
    """A manifest the kit contract refuses (here a file kind it does not list) is never sent to the signer (D39)."""
    from datetime import UTC, datetime

    from jana_tools.release.distribution import KitArtifact, build_kit
    from jana_tools.release.operations import FULL_KIT_PARTS, Candidate, Ring

    files = []
    for category in sorted(FULL_KIT_PARTS):
        source = tmp_path / f"{category}.bin"
        source.write_bytes(f"synthetic {category}".encode())
        kind = "model_weights" if category == "models" else "content_pack"  # not a kit file kind
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        files.append(KitArtifact(category, kind, source, source.name, sha, "stable", "R3"))
    asked: list[dict] = []

    def sign(doc):
        asked.append(doc)
        return signed("usb_kit", doc)

    c = Candidate("app", "1.0.0", "a" * 64, "stable")
    ring = Ring("1.0.0", "R3", datetime(2026, 10, 16, tzinfo=UTC))
    with pytest.raises(ValueError, match="contract"):
        build_kit(c, ring, "school", files, tmp_path / "output", "kit-2026.3.1", 1, AT, sign)
    assert asked == [] and not (tmp_path / "output").exists()


def test_ops_channel_change_uses_separate_signed_state(tmp_path: Path):
    from agent_core.api.packs import PackDesk

    p = policy(tmp_path)
    p.adopt_matrix(signed("compatibility_matrix", matrix()))
    desk = PackDesk(
        tmp_path, Environment.DEV, "1.0.0", lambda _: None, trust=dev_trust(), channel="stable", operations=p
    )
    desk.set_channel("pilot")
    assert desk.operations.channel == "pilot" and desk.operations.matrix() == {}
    assert desk.channel == desk.packs.channel == "pilot"
    with pytest.raises(ValueError):
        desk.set_channel("arbitrary")


def test_ops_lift_can_target_app_and_bundle(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(
        safety(
            [
                entry(
                    "tool", "one", "disable", entry_id="app_fix", lift_when={"artefact_id": "app", "version": "1.0.1"}
                ),
                entry(
                    "tool",
                    "two",
                    "disable",
                    entry_id="bundle_fix",
                    lift_when={"artefact_id": "agent_bundle", "version": "1.0.1"},
                ),
            ]
        )
    )
    p.turn_boundary({"app": "1.0.0", "agent_bundle": "1.0.0"})
    assert p.decision("tool", "one").action == "disable"
    p.turn_boundary({"app": "1.0.1", "agent_bundle": "1.0.1"})
    assert p.decision("tool", "one").action == p.decision("tool", "two").action == "allow"


def test_ops_import_cannot_be_lost_during_boundary(tmp_path: Path, monkeypatch):
    import threading

    import agent_core.config.operations as module

    p, other = policy(tmp_path), policy(tmp_path)
    p.adopt_safety(safety([entry("tool", "one", "disable")]))
    doc = safety([entry("model_pack", "two", "disable")], 2)
    writing, imported = threading.Event(), threading.Event()
    original = module.atomic_json

    def atomic(path, data):
        if path.name == "active.json" and not writing.is_set():
            writing.set()
            imported.wait(timeout=1)
        original(path, data)

    monkeypatch.setattr(module, "atomic_json", atomic)

    def second():
        assert writing.wait(timeout=5)
        other.adopt_safety(doc)
        imported.set()

    worker = threading.Thread(target=second)
    worker.start()
    p.turn_boundary({})
    worker.join(timeout=5)
    assert not worker.is_alive()
    p.turn_boundary({})
    assert p.decision("tool", "one").action == "disable"
    assert p.decision("model_pack", "two").action == "disable"


def test_ops_wrong_key_item_stays_retired_after_fix_arrives(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(
        safety(
            [
                entry(
                    "item",
                    "itm.old",
                    "withdraw",
                    reason_code="wrong_key",
                    lift_when={"artefact_id": "pack.phy.o", "version": "1.0.1"},
                )
            ]
        )
    )
    p.turn_boundary({"pack.phy.o": "1.0.1"})
    assert p.decision("item", "itm.old").action == "withdraw"
    assert policy(tmp_path).decision("item", "itm.old").action == "withdraw"


def test_ops_unsupported_pack_is_not_offered(tmp_path: Path):
    p = policy(tmp_path)
    doc = matrix()
    doc["content_packs"][0]["status"] = "unsupported"
    p.adopt_matrix(signed("compatibility_matrix", doc))
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)


def test_ops_release_candidate_does_not_satisfy_final_minimum(tmp_path: Path):
    p = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0-rc.1", dev_trust())
    doc = matrix()
    doc["apps"][0]["app_version"] = "1.0.0-rc.1"
    assert p.adopt_matrix(signed("compatibility_matrix", doc))
    assert not p.offered("content_pack", "pack.phy.o", "1.0.0", format_major=1)


def test_ops_key_revocation_does_not_lift_accepted_restriction(tmp_path: Path):
    current = [dev_trust()]
    p = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", lambda: current[0])
    p.adopt_safety(safety([entry("online_feature", "cloud_tier", "force_off")]))
    p.turn_boundary({})
    current[0] = current[0].with_revoked([dev_signer().key_id])
    assert p.decision("online_feature", "cloud_tier").action == "force_off"
    assert not p.adopt_safety(safety([entry()], 2))


def test_ops_endpoint_catalogue():
    from agent_core.contracts import validate
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    validate("api/commands#/$defs/CatalogueImport", {"safety_configuration": safety([entry()])})
    validate("api/commands#/$defs/CatalogueImportReply", {"matrix_adopted": False, "safety_adopted": True})
    assert {"GET /v1/help", "GET /v1/settings/sections", "POST /v1/operations/catalogue"} <= set(ENDPOINTS_BY_KEY)


def test_ops_stronger_restriction_can_replace_same_entry(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("skill", "solve", "pin_previous")]))
    p.turn_boundary({})
    p.adopt_safety(safety([entry("skill", "solve", "disable")], 2))
    p.turn_boundary({})
    assert p.decision("skill", "solve").action == "disable"


def test_ops_retired_item_is_not_restored_by_channel_change(tmp_path: Path):
    p = policy(tmp_path)
    p.retire_item("itm.old")
    pilot = DevicePolicy(tmp_path, Environment.DEV, "pilot", "1.0.0", dev_trust())
    assert pilot.decision("item", "itm.old").action == "withdraw"


def test_ops_summary_distinguishes_pending_from_active(tmp_path: Path):
    p = policy(tmp_path)
    p.adopt_safety(safety([entry("app_version", "1.0.0", "advise_update")]))
    assert p.summary()["sequence"] == 0 and p.summary()["pending_sequence"] == 1
    p.turn_boundary({})
    summary = p.summary()
    assert summary["sequence"] == 1 and summary["pending_sequence"] == 0
    assert summary["entries"][0]["action"] == "advise_update"


def test_ops_empty_policy_does_not_create_stores(tmp_path: Path):
    p = policy(tmp_path)
    p.turn_boundary({"app": "1.0.0"})
    assert not list(tmp_path.rglob("*"))
