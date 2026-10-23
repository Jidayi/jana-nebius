"""OPS-02..19, OPS-37: synthetic release-policy regressions, not field evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.config import Settings
from jana_tools.release import operations as ops
from jana_tools.release import rollout

NOW = datetime(2026, 10, 16, tzinfo=UTC)
HASH = "a" * 64


def candidate(kind="app", **changes):
    return replace(
        ops.Candidate(
            kind=kind, version="mp.synthetic.low@1" if kind == "model_pack" else "1.2.3", sha256=HASH, channel="stable"
        ),
        **changes,
    )


def gates(c):
    return {
        g: ops.GateResult(
            candidate_sha256=c.sha256, passed=True, report_sha256=HASH, measured_at=NOW, reviewer="synthetic-reviewer"
        )
        for g in ops.required_gates(c.kind)
    }


def ops02_patch_cannot_raise_min_app():
    assert ops.pack_change_errors("1.2.0", "1.2.1", "1.0.0", "1.1.0")
    assert not ops.pack_change_errors("1.2.0", "1.3.0", "1.0.0", "1.1.0")
    with pytest.raises(ValueError):
        ops.pack_change_errors("junk", "1.2.1", "1.0.0", "1.1.0")


def ops03_corrections_reach_supported_versions():
    apps = [ops.AppSupport("1.0.0", NOW - timedelta(days=20)), ops.AppSupport("2.0.0", NOW)]
    assert ops.correction_errors(apps, {"2.0.0"}, NOW)
    assert not ops.correction_errors(apps, {a.version for a in apps}, NOW)


def ops04_freeze_window_enforced():
    freeze = [(NOW - timedelta(days=1), NOW + timedelta(days=1))]
    assert ops.freeze_errors(candidate(), NOW, freeze)
    assert not ops.freeze_errors(candidate(security_hotfix=True), NOW, freeze)
    assert not ops.freeze_errors(candidate(channel="dev"), NOW, freeze)
    assert ops.freeze_errors(candidate(severity="SEV3"), NOW, freeze)


def ops06_missing_gate_blocks_promotion():
    for kind in ("app", "agent_bundle", "content_pack", "model_pack"):
        c = candidate(kind)
        results = gates(c)
        assert not ops.promotion_errors(c, results, ops.Signoffs("manager", "eval", "safe", "security", "go"), NOW)
        for gate in results:
            assert ops.promotion_errors(
                c,
                {k: v for k, v in results.items() if k != gate},
                ops.Signoffs("manager", "eval", "safe", "security", "go"),
                NOW,
            )
        results[next(iter(results))] = replace(next(iter(results.values())), candidate_sha256="b" * 64)
        assert ops.promotion_errors(c, results, ops.Signoffs("manager", "eval", "safe", "security", "go"), NOW)


def ops06_signoffs_required():
    c = candidate()
    assert ops.promotion_errors(c, gates(c), ops.Signoffs("", "eval", "safe", "security", "go"), NOW)
    assert ops.promotion_errors(c, gates(c), ops.Signoffs("manager", "eval", "safe", "security", "no_go"), NOW)


def ops37_data_changes_flagged():
    notes = ops.ReleaseNotes("IT", "review", "parent", ("A",), "n2", ("data_changes", "changes"))
    assert ops.notes_errors(notes, data_changed=True, previous_notice="n2")
    assert not ops.notes_errors(notes, data_changed=True, previous_notice="n1")
    assert ops.notes_errors(replace(notes, students=("A", "B", "C", "D")), data_changed=False)


def lifecycle():
    return [
        ops.LifecycleRun(
            hw,
            os,
            previous,
            route,
            HASH,
            HASH,
            True,
            True,
            frozenset(ops.LIFECYCLE_STEPS),
            f"synthetic-{hw}-{os}-{previous}-{route}",
        )
        for hw in ("low", "mid", "high")
        for os in ("windows", "macos", "linux")
        for previous in ("fresh", "1.0.0", "1.1.0")
        for route in (("kit",) if previous == "fresh" else ("usb_update", "online_update"))
    ]


PLATFORMS = ("windows", "macos", "linux")


def test_policy_ops07_offline_lifecycle_script():
    assert not ops.lifecycle_errors(lifecycle(), ("1.0.0", "1.1.0"), PLATFORMS, "1.2.0")
    broken = lifecycle()
    broken[0] = replace(broken[0], zero_egress=False)
    assert ops.lifecycle_errors(broken, ("1.0.0", "1.1.0"), PLATFORMS, "1.2.0")


def test_policy_ops07_skip_version_upgrades():
    runs = [r for r in lifecycle() if r.previous != "1.0.0"]
    assert ops.lifecycle_errors(runs, ("1.0.0", "1.1.0"), PLATFORMS, "1.2.0")
    broken = lifecycle()
    broken[0] = replace(broken[0], replay_after="b" * 64)
    assert ops.lifecycle_errors(broken, ("1.0.0", "1.1.0"), PLATFORMS, "1.2.0")


def ops07_first_release_is_its_own_baseline():
    """D96: the very first release has no earlier version, so it lists its own version alone and needs the fresh runs
    only; listing itself is refused in any other case, and so is a supported version not earlier than the candidate."""
    fresh = [r for r in lifecycle() if r.previous == "fresh"]
    assert ops.lifecycle_matrix(("1.0.0",), PLATFORMS, "1.0.0") == [
        (r.hardware, r.platform, r.previous, r.route) for r in fresh
    ]
    assert ops.lifecycle_errors(fresh, ("1.0.0",), PLATFORMS, "1.0.0") == []
    # Without listing itself a first release still has no baseline; the fresh runs alone do not cover a later release.
    assert ops.lifecycle_errors(fresh, (), PLATFORMS, "1.0.0")
    assert any("missing run" in e for e in ops.lifecycle_errors(fresh, ("1.0.0",), PLATFORMS, "1.1.0"))
    # Its own version beside an earlier one: not a first release, so it cannot be its own baseline.
    errors = ops.lifecycle_errors(lifecycle(), ("1.0.0", "1.1.0"), PLATFORMS, "1.1.0")
    assert any("beside others" in e for e in errors)
    # A later or equal version listed as supported is refused; so is an unparseable one.
    assert any("not earlier" in e for e in ops.lifecycle_errors(lifecycle(), ("1.0.0", "1.1.0"), PLATFORMS, "1.0.5"))
    assert ops.lifecycle_errors(fresh, ("first",), PLATFORMS, "1.0.0")
    assert ops.lifecycle_errors(fresh, ("1.0.0", "1.0.0"), PLATFORMS, "1.0.0")


def ops08_device_side_bucket(tmp_path: Path):
    path = tmp_path / "bucket"
    bucket = rollout.device_bucket(path)
    assert 0 <= bucket < 1 and rollout.device_bucket(path) == bucket
    assert not rollout.offered(bucket, 0)
    assert rollout.offered(bucket, 1)
    for bad in (-0.1, 1.1, float("nan")):
        assert not rollout.offered(bad, 1)
    assert "device" not in rollout.publication(rollout.start("1.0.0", 0))


def ops08_soak_enforced():
    cfg = Settings()
    health = ops.RingHealth(1000, 0, 1000, 0, 0, 1, cfg.ops_pilot_school_days, False, True)
    r0 = ops.Ring("1.2.3", "R0", NOW)
    assert ops.advance_ring(r0, NOW, health, cfg) == r0
    r1 = ops.advance_ring(r0, NOW + timedelta(days=cfg.ops_r0_days), health, cfg)
    assert r1.name == "R1"
    assert (
        ops.advance_ring(r1, r1.started + timedelta(days=cfg.ops_r1_days), replace(health, school_days=0), cfg).name
        == "R1"
    )
    hot = replace(r0, hotfix=True)
    assert ops.advance_ring(hot, NOW + timedelta(hours=cfg.ops_hotfix_soak_hours), health, cfg).name == "R1"


def ops09_auto_halt():
    r = rollout.Rollout("1.2.3", 2, 0)
    halted = rollout.advance(r, 99999999, rollout.CrashStats(1000, 100))
    assert halted.halted and rollout.fraction(halted) == 0
    assert rollout.publication(halted) == {
        "version": "1.2.3",
        "rollout_fraction": 0.0,
        "listed": False,
        "kits_allowed": False,
    }
    with pytest.raises(ValueError):
        rollout.resume(halted, 100, " ")
    health = ops.RingHealth(1000, 0, 1000, 20, 0, 1, 3, False, True)
    ring = ops.advance_ring(ops.Ring("1.2.3", "R2", NOW), NOW, health)
    assert ring.halted and not ops.kits_allowed(ring)


def ops15_kit_from_stable_only():
    c = candidate()
    for ring in ("R0", "R1", "R2"):
        assert ops.kit_errors(c, ops.Ring(c.version, ring, NOW), "school", {"installers"})
    parts = set(ops.FULL_KIT_PARTS)
    assert not ops.kit_errors(c, ops.Ring(c.version, "R3", NOW), "school", parts)
    assert ops.kit_errors(replace(c, channel="pilot"), ops.Ring(c.version, "R3", NOW), "school", parts)
    assert not ops.kit_errors(
        replace(c, channel="pilot", version="1.2.3-rc.1"), ops.Ring("1.2.3-rc.1", "R1", NOW), "candidate", parts
    )


def test_policy_ops15_physical_kit_verified():
    cfg = Settings()
    samples = ops.required_usb_samples(200, cfg)
    assert samples >= cfg.ops_usb_min_samples
    checks = [ops.USBCheck(f"media-{i}", HASH, "low", True, True, "operator", NOW) for i in range(samples)]
    assert not ops.usb_batch_errors(200, HASH, checks, cfg)
    assert ops.usb_batch_errors(200, HASH, checks[:-1], cfg)
    assert ops.usb_batch_errors(200, HASH, [replace(c, sha256="b" * 64) for c in checks], cfg)


def ops16_budget_check():
    cfg = Settings()
    amounts = {key: value for key, value in ops.bandwidth_limits(cfg).items()}
    assert not ops.budget_errors(amounts, {}, model_selected=True, metered_authorised=True)
    amounts["app_patch"] += 1
    assert ops.budget_errors(amounts, {})
    assert not ops.budget_errors(
        amounts, {"app_patch": "approved exception: ticket-ops"}, model_selected=True, metered_authorised=True
    )
    assert ops.budget_errors({"model_download": 1}, {}, model_selected=False, metered_authorised=False)


def test_policy_ops17_slo_alerting():
    cfg = Settings()
    measures = [ops.ServiceSample("cloud_gateway", 10000, 100, (0.1,), cfg.ops_alert_delay_s + 1)]
    report = ops.slo_report(measures, cfg)
    assert report["alerts"] and report["pause_feature_work"]
    assert any("late" in e for e in report["errors"])
    assert ops.slo_report([], cfg)["errors"]


def test_policy_ops17_cloud_first_words_budget():
    cfg = Settings()
    samples = {"reference_low": (1.0, 1.1, 1.2, 1.3), "s4_web": (1.0, 1.1, 1.2, 1.3)}
    assert not ops.first_words_errors(samples, cfg)
    assert ops.first_words_errors({"reference_low": (9.0,)}, cfg)


def test_policy_ops18_load_test_at_twice_peak():
    cfg = Settings()
    peak = ops.peak_concurrency(1000, cfg)
    assert ops.load_errors(1000, peak, peak, False, False, "", cfg)
    assert not ops.load_errors(
        1000, peak * cfg.ops_load_multiple, peak * cfg.ops_capacity_multiple, True, True, HASH, cfg
    )


def ops19_cost_spike_alert():
    cfg = Settings()
    history = [1.0] * cfg.ops_cost_history_days
    alerts = ops.cost_alerts(3.0, history, 2.0, 1.0, price_changed=True, cfg=cfg)
    assert set(alerts) == {"daily_spike", "price_floor", "price_change"}
    assert ops.cost_alerts(0.1, history[:-1], 0.1, 1.0, cfg=cfg) == ["missing_cost_history"]


def test_ops_parent_notes_need_data_section_first():
    notes = ops.ReleaseNotes("it", "reviewer", "parent", ("student",), "new-notice")
    assert ops.notes_errors(notes, data_changed=True, previous_notice="old-notice")


def test_ops_budgets_reject_boolean_amounts():
    assert ops.budget_errors({"app_patch": True}, {})


def test_ops_monitor_persists_halt_and_removes_offer(tmp_path: Path):
    import json
    from dataclasses import asdict

    from agent_core.config.operations import atomic_json
    from jana_tools.release.monitor import HealthReport, ReleaseMonitor

    state = tmp_path / "release.json"
    ring = ops.Ring("1.2.3", "R2", NOW)
    atomic_json(state, {"ring": {**asdict(ring), "started": NOW.isoformat()}})
    monitor = ReleaseMonitor(state)
    unhealthy = ops.RingHealth(1000, 100, 1000, 0, 0, 1, 3, False, True)
    report = HealthReport("1.2.3", NOW, HASH, unhealthy)
    result = monitor.tick(report, NOW)
    assert result["publication"]["rollout_fraction"] == 0
    assert not result["publication"]["listed"] and not result["publication"]["kits_allowed"]
    assert json.loads(state.read_text())["ring"]["halted"]
    with pytest.raises(ValueError):
        ReleaseMonitor(state).resume("", NOW)
    ReleaseMonitor(state).resume("replacement prepared", NOW)
    assert not json.loads(state.read_text())["ring"]["halted"]


def test_ops_budget_measurement_counts_verified_reference_bytes(tmp_path: Path):
    import hashlib

    data = tmp_path / "transfer.bin"
    data.write_bytes(b"synthetic wire bytes")
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    transfers = [
        ops.ReferenceTransfer(flow, None, None, 0, "not part of this candidate")
        for flow in ops.bandwidth_limits()
        if flow != "app_patch"
    ]
    transfers.append(ops.ReferenceTransfer("app_patch", data, digest, 2, None))
    amounts = ops.measure_bandwidth(transfers)
    assert amounts["app_patch"] == 2 * len(data.read_bytes())
    assert not ops.budget_errors(amounts, {})
    data.write_bytes(b"changed")
    with pytest.raises(ValueError):
        ops.measure_bandwidth(transfers)
