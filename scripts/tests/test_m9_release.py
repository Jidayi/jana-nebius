"""M9.c and M9.d: version schemes and immutable versions (OPS-01), releases from tags only (OPS-05), the per-release
compliance record (OPS-36), the release gates (EVL-17), the stage release rule (PRD-11) and the exit metrics (PRD-17).
Repositories, reports and timings here are synthetic test data."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from fixture_sources import GOVERNANCE_DOCS as DOCS
from jana_tools import REPO_ROOT
from jana_tools.coverage import acceptance_tests
from jana_tools.harness import report as rep
from jana_tools.release import compliance, provenance, stage, versions
from jana_tools.spec import requirements

# --- OPS-01 ---------------------------------------------------------------------------------------------------------


def ops01_immutable_versions(tmp_path: Path) -> None:
    ledger = versions.Ledger(tmp_path)
    assert ledger.publish("content_pack", "pack.phy.o", "0.1.0", "a" * 64) is True
    assert ledger.publish("content_pack", "pack.phy.o", "0.1.0", "a" * 64) is False, "the same bytes again is fine"
    with pytest.raises(versions.ImmutableVersionError, match="different bytes"):
        ledger.publish("content_pack", "pack.phy.o", "0.1.0", "b" * 64)
    assert ledger.publish("content_pack", "pack.phy.o", "0.1.1", "b" * 64) is True
    with pytest.raises(ValueError, match="TABLE OPS-01a"):
        ledger.publish("app", "app", "1.0", "c" * 64)
    for kind, good, bad in (("app", "0.1.0-rc.2", "0.1.0-beta"), ("usb_kit", "kit-2026.3.1", "kit-2026.4.1"),
                            ("contract", "1.2", "1.2.0"), ("model_pack", "gemma-4-12b-q4@3", "gemma-4-12b-q4"),
                            ("learner_database", "2", "2.0")):  # fmt: skip
        assert versions.form_errors(kind, good) == [] and versions.form_errors(kind, bad), kind


def ops01_patch_has_no_migration() -> None:
    current = versions.current_migrations()
    assert current and all(":" in m for m in current)
    added = [*current, "learner:2:0123456789ab"]
    assert versions.patch_migration_errors("0.1.0", "0.1.1", current, added), "a patch with a migration fails"
    assert versions.patch_migration_errors("0.1.0", "0.1.1", current, current) == []
    assert versions.patch_migration_errors("0.1.3", "0.2.0", current, added) == [], "a minor may migrate"
    changed = [current[0].rsplit(":", 1)[0] + ":ffffffffffff", *current[1:]]
    assert versions.patch_migration_errors("0.1.0", "0.1.1", current, changed), "an edited migration counts too"


# --- OPS-05 ---------------------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.test")
    _git(repo, "config", "user.name", "CI")
    (repo / "app.txt").write_text("1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    return repo


def ops05_release_from_tag_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "release/0.1")
    (repo / "app.txt").write_text("2\n")
    _git(repo, "commit", "-q", "-am", "release fix")
    _git(repo, "tag", "v0.1.0-rc.1")
    good = provenance.attestation(repo, "app", "0.1.0-rc.1", "f" * 64, "v0.1.0-rc.1", "release/0.1")
    assert provenance.provenance_errors(good, repo) == []
    _git(repo, "checkout", "-q", "main")
    (repo / "app.txt").write_text("3\n")
    _git(repo, "commit", "-q", "-am", "trunk work")
    _git(repo, "tag", "v0.1.0-rc.2")  # a tag on main, not on the release branch
    on_main = provenance.attestation(repo, "app", "0.1.0-rc.2", "f" * 64, "v0.1.0-rc.2", "release/0.1")
    assert any("is not on release/0.1" in e for e in provenance.provenance_errors(on_main, repo))
    untagged = {**good, "tag": ""}
    assert "no release tag" in provenance.provenance_errors(untagged, repo)[0]
    nightly = {**good, "branch": "main"}
    assert any("not a release/<major>.<minor> branch" in e for e in provenance.provenance_errors(nightly, repo))
    moved = {**good, "commit": _git(repo, "rev-parse", "main")}
    assert any("points at" in e for e in provenance.provenance_errors(moved, repo))
    wrong_version = {**good, "version": "0.1.1"}
    assert any("does not match tag" in e for e in provenance.provenance_errors(wrong_version, repo))


# --- OPS-36 ---------------------------------------------------------------------------------------------------------

FONT = {"ecosystem": "npm", "name": "@fontsource/noto-sans", "version": "5.3.0", "licence": "OFL-1.1"}
LIB = {"ecosystem": "npm", "name": "left-pad", "version": "1.3.0", "licence": "MIT"}
REGISTER = {"@fontsource/noto-sans": {"name": "@fontsource/noto-sans", "licence": "OFL-1.1", "restrictions": "none"},
            "gemma-4-12b": {"name": "gemma-4-12b", "licence": "Apache-2.0", "restrictions": "none"}}  # fmt: skip
PACK = {"pack_id": "pack.phy.o", "version": "0.1.0", "credits": [{"record_id": "itm.1", "licence": "LicenseRef-Own"}]}


def ops36_missing_licence_blocks() -> None:
    clean = compliance.record([FONT, LIB], [FONT, LIB], [PACK], ["gemma-4-12b"], True, REGISTER, {})
    assert clean["blocking"] == [] and {a["kind"] for a in clean["assets"]} == {"font", "model"}
    model = compliance.record([FONT], [FONT], [PACK], ["qwen3-vl-30b"], True, REGISTER, {})
    assert model["blocking"] == ["model qwen3-vl-30b: no licence entry (OPS-36)"]
    font = compliance.record([FONT], [FONT], [PACK], [], True, {}, {})
    assert font["blocking"] == ["font @fontsource/noto-sans: no licence entry (OPS-36)"]
    restricted = {**REGISTER, "gemma-4-12b": {**REGISTER["gemma-4-12b"], "restrictions": "no use by minors"}}
    assert "not reviewed" in compliance.record([], [], [], ["gemma-4-12b"], True, restricted, {})["blocking"][0]
    added = compliance.record([FONT, LIB], [FONT], [PACK], [], True, REGISTER, {})
    assert added["blocking"] == [
        "left-pad@1.3.0: added or licence changed since the previous release, with no reviewer"
    ]
    assert compliance.record([FONT, LIB], [FONT], [PACK], [], True, REGISTER, {"left-pad@1.3.0": "rev_sec"})[
        "blocking"] == []  # fmt: skip
    unlicensed = {**PACK, "credits": [{"record_id": "itm.2", "licence": None}]}
    assert "CUR-23" in compliance.record([], [], [unlicensed], [], True, {}, {})["blocking"][0]
    assert "THIRD_PARTY_NOTICES" in compliance.record([], [], [], [], False, {}, {})["blocking"][0]
    # This checkout's S1 release record ships no model pack and blocks on nothing.
    components, _, packs, notices = compliance.current_inputs()
    assert compliance.record(components, None, packs, [], notices)["blocking"] == []


# --- EVL-17 ---------------------------------------------------------------------------------------------------------


def _report() -> dict[str, Any]:
    """A synthetic harness report that passes every S1 gate the harness measures."""
    ok = rep.result(10, 10)
    return {"valid": True, "network": {"state": "disabled", "egress_attempts": 0}, "cases": [
        {"suite": "marking", "case_id": "g1", "status": "passed", "critical": False, "trace_ids": ["r"]}],
        "suites": {"marking": {"result": ok, "criteria": {"step_first_wrong": ok, "step_category": ok}},
                   "scenarios": {"result": ok, "criteria": {"critical": ok, "board_numbers_traced": ok,
                                                            "no_answer_leak": ok}},
                   "safety": {"result": ok, "criteria": {"critical": ok}}}}  # fmt: skip


EVIDENCE = {"gallery": rep.result(40, 40), "model_oracles": {"final_answer": rep.result(95, 100)},
            "bakeoff": {"structured_first_pass": rep.result(995, 1000)}, "decisions": {"D6": "decided"}}  # fmt: skip


def evl17_release_pipeline_blocks() -> None:
    gates = stage.s1_gates(_report(), **EVIDENCE)
    assert all(g.passed for g in gates), [g for g in gates if not g.passed]

    def failing(report: dict[str, Any], **changes: Any) -> set[str]:
        return {g.metric for g in stage.s1_gates(report, **{**EVIDENCE, **changes}) if not g.passed}

    leaky = copy.deepcopy(_report())
    leaky["suites"]["scenarios"]["criteria"]["no_answer_leak"] = rep.result(9, 10)
    assert failing(leaky) == {"Detected answer leaks in guided mode"}
    online = copy.deepcopy(_report())
    online["network"]["egress_attempts"] = 1
    assert failing(online) == {"Zero egress during offline gate runs"}
    assert failing(_report(), model_oracles={"final_answer": rep.result(89, 100)}) == {
        "Final answer correct, tool-checkable items (one topic)"
    }
    assert failing(_report(), decisions={"D6": "open"}) == {
        "Local model per tier and class chosen by the bake-off (D6)"
    }
    assert failing(_report(), gallery=None) == {"Gallery states render without console errors"}, "missing = failing"
    unsafe = copy.deepcopy(_report())
    unsafe["suites"]["safety"]["criteria"]["critical"] = rep.result(119, 120)
    assert failing(unsafe) == {"Critical safety items"}
    # A held-out metric that drops more than the configured points with separated intervals fails the release.
    before = {"suites": {"safety": {"criteria": {"held_out": rep.result(100, 100)}}}}
    after = {"suites": {"safety": {"criteria": {"held_out": rep.result(80, 100)}}}}
    assert stage.held_out_drop_failures(after, before, Settings().gate_held_out_max_drop_points)
    assert stage.held_out_drop_failures(before, before, 2.0) == []


# --- PRD-11 and PRD-17 ----------------------------------------------------------------------------------------------


def _s1_tests() -> list[str]:
    return [t for rid, req in requirements(DOCS).items() if not req.retired and req.priority == "must"
            and req.stage == "S1" for t in acceptance_tests(rid, DOCS)]  # fmt: skip


def prd11_release_gate_enforced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    met = [{"metric": "m", "target": "t", "measured": 1, "status": "met"}]
    every = dict.fromkeys(_s1_tests(), "pass")
    clean = stage.release_rule_failures("S1", every, met, docs=DOCS)
    assert clean == {"requirements": [], "exit_metrics": [], "decisions": []}
    one = _s1_tests()[0]
    broken = stage.release_rule_failures("S1", {**every, one: "fail"}, met, docs=DOCS)
    assert len(broken["requirements"]) == 1 and f"{one} → fail" in broken["requirements"][0]
    unmet = stage.release_rule_failures("S1", every, [{**met[0], "status": "missing", "measured": None}], docs=DOCS)
    assert unmet["exit_metrics"] == ["m: missing (None; target t)"]
    docs = tmp_path / "docs"
    shutil.copytree(DOCS / "specification" / "registers", docs / "specification" / "registers")
    register = docs / "specification" / "registers" / "decisions.json"
    data = json.loads(register.read_text())
    next(d for d in data["decisions"] if "s1_foundation" in d.get("blocks", []))["status"] = "open"
    register.write_text(json.dumps(data))
    assert len(stage.undecided("S1", docs)) == 1
    # A closed pilot (PRD-11) ships before the pilot-measured rows are met, never before the release-gate rows, and
    # every decision blocking pilot_start must be decided too.
    rows = [{**met[0], "metric": "gate row", "kind": stage.RELEASE_GATE},
            {**met[0], "metric": "pilot row", "status": "missing", "measured": None, "kind": stage.PILOT}]  # fmt: skip
    assert stage.release_rule_failures("S1", every, rows, docs=DOCS)["exit_metrics"] == [
        "pilot row: missing (None; target t)"
    ]
    assert stage.release_rule_failures("S1", every, rows, closed_pilot=True, docs=DOCS)["exit_metrics"] == []
    assert stage.pilot_pending(rows) == ["pilot row: missing"]
    rows[0]["status"] = "unmet"
    assert stage.release_rule_failures("S1", every, rows, closed_pilot=True, docs=DOCS)["exit_metrics"]
    next(d for d in data["decisions"] if "pilot_start" in d.get("blocks", []))["status"] = "proposed"
    register.write_text(json.dumps(data))
    assert len(stage.release_rule_failures("S1", every, met, docs, closed_pilot=True)["decisions"]) == 2
    assert len(stage.release_rule_failures("S1", every, met, docs)["decisions"]) == 1
    # The release script prints the failing items and refuses to tag.
    from jana_tools.__main__ import main

    tags_before = subprocess.run(["git", "tag"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert main(["release", "stage", "S1", "--tag", "v0.0.0-test-must-not-exist"]) == 1
    assert "gates:" in capsys.readouterr().err
    assert subprocess.run(["git", "tag"], cwd=REPO_ROOT, capture_output=True, text=True).stdout == tags_before


def prd17_exit_metrics_reported() -> None:
    report = _report()
    rows = stage.exit_metrics("S1", report, {"first_text_median_s": 2.4, "restatement_median_s": 0.6}, (40, 40))
    assert [r["status"] for r in rows] == ["met", "met", "met", "met"]
    strict = Settings(exit_s1_first_text_median_s=2.0)
    rows = stage.exit_metrics("S1", report, {"first_text_median_s": 2.4, "restatement_median_s": 0.6}, (39, 40),
                              settings=strict)  # fmt: skip
    by_metric = {r["metric"]: r for r in rows}
    assert by_metric["First accepted text, mid-class laptop (median)"]["target"] == "≤ 2.0 s"
    assert by_metric["First accepted text, mid-class laptop (median)"]["status"] == "unmet"
    assert by_metric["Contracts generate types with zero drift"]["status"] == "unmet"
    missing = stage.exit_metrics("S1", None, None, None)
    assert {r["status"] for r in missing} == {"missing"}
    # S2 (TABLE PRD-17a): three release-gate rows and five pilot rows, every target from configuration.
    s2 = stage.exit_metrics("S2", None, None, None, settings=Settings(exit_s2_final_answer_correct=0.97))
    assert [r["kind"] for r in s2] == [stage.RELEASE_GATE] * 3 + [stage.PILOT] * 5
    assert {r["status"] for r in s2} == {"missing"}
    assert s2[0]["target"].startswith("≥ 97%")
    from test_m25b_gates import pilot_exit

    pilot = stage.exit_metrics("S2", None, None, None, pilot=pilot_exit())
    assert [r["status"] for r in pilot if r["kind"] == stage.PILOT] == ["met"] * 5
    late = pilot_exit()
    late["learning_gain"]["registered_at"] = "2026-12-01T00:00:00Z"  # registered after the first pilot data
    rows = {r["metric"]: r for r in stage.exit_metrics("S2", None, None, None, pilot=late)}
    assert rows["Learning gain versus comparison classes, 8 to 12 weeks"]["status"] == "unmet"
    assert "not pre-registered" in rows["Learning gain versus comparison classes, 8 to 12 weeks"]["measured"]
