"""The owner's launch-evidence kit. Templates and dry runs must never pass a gate; checklists must write exactly the
format the gates read. All answers here are synthetic and live in a temporary folder: none of this is evidence."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jana_tools import REPO_ROOT
from jana_tools.evidence.drills import DRILLS
from jana_tools.evidence.placeholders import placeholder_paths
from jana_tools.evidence.records import assemble, record_errors
from jana_tools.evidence.runner import ZERO, Interactive, Rehearsal, Scripted, check, current_spec, run
from jana_tools.evidence.templates import GOVERNANCE, M24_TEMPLATES, TEMPLATES, governance_template, stale_templates
from jana_tools.release.field_evidence import SOURCES, FieldEvidence, ProbeRecord, field_errors, read_evidence

CANDIDATE = "a" * 40
NOW = datetime.now(UTC).replace(microsecond=0)


def at(**delta: float) -> str:
    return (NOW - timedelta(**delta)).isoformat()


# ------------------------------------------------------------------------------------------- M23 templates
@pytest.mark.parametrize("name", GOVERNANCE)
def test_untouched_governance_template_fails_its_gate(name: str):
    template = governance_template(name)
    assert placeholder_paths(template), f"{name}: every value must start as a FILL-IN placeholder"
    assert record_errors(GOVERNANCE[name][0], template, candidate=CANDIDATE)


def synthetic_release() -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("m23gov", REPO_ROOT / "scripts" / "tests" / "test_m23_governance.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value: dict[str, Any] = module.evidence()
    return value


def test_a_placeholder_left_in_a_free_text_field_is_refused():
    """A non-empty string satisfies the contract, so the gate must refuse the marker itself."""
    from jana_tools.m23.gates import release_errors

    today = datetime(2026, 10, 16).date()
    value = synthetic_release()
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=today) == []
    assert record_errors("counsel", value["counsel"], candidate=CANDIDATE, today=today) == []
    for section, field_path in (
        ("counsel", ("topics", "lawful_basis", "finding")),
        ("tabletop", ("review_ref",)),
        ("redteam", ("privacy_audit_ref",)),
        ("security", ("tests", "fuzzing", "evidence")),
    ):
        bad = copy.deepcopy(value)
        target = bad[section]
        for step in field_path[:-1]:
            target = target[step]
        target[field_path[-1]] = "FILL-IN: counsel's conclusion"
        assert record_errors(section, bad[section], candidate=CANDIDATE, today=today)
        assert release_errors(bad, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=today)


def test_assembled_untouched_templates_fail_release_and_pilot_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    from jana_tools.m23.cli import main as m23

    for name in GOVERNANCE:
        shutil.copyfile(TEMPLATES / f"{name}.json", tmp_path / f"{name}.json")
    result = assemble(tmp_path, candidate=CANDIDATE, stage="S2", gate="pilot_start")
    assert result["release_errors"]
    assert (
        m23(
            [
                "release-check",
                "--evidence",
                str(tmp_path / "release.json"),
                "--candidate",
                CANDIDATE,
                "--stage",
                "S2",
                "--gate",
                "pilot_start",
            ]
        )
        == 1
    )
    assert m23(["pilot-start-check", "--evidence", str(tmp_path / "programme.json"), "--candidate", CANDIDATE]) == 1
    capsys.readouterr()


def test_security_release_refuses_template_contacts(tmp_path: Path):
    from jana_tools.m23.gates import security_release

    pack = tmp_path / "update.janaupdate"
    pack.write_bytes(b"synthetic")
    with pytest.raises(ValueError):
        security_release(pack, tmp_path / "out", version="1.0.1", contacts=governance_template("contacts")["contacts"])


# ------------------------------------------------------------------------------------------- M24 templates
def test_every_field_check_has_a_checklist():
    covered = [test for drill in DRILLS.values() for test in drill.tests]
    assert sorted(covered) == sorted(SOURCES)


def test_m24_templates_are_current():
    assert stale_templates() == []


@pytest.mark.parametrize("name", SOURCES)
def test_untouched_m24_template_fails_its_gate(name: str, tmp_path: Path):
    template = json.loads((M24_TEMPLATES / f"{name}.json").read_text())
    assert placeholder_paths(template["data"])
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(template))
    index = json.loads((M24_TEMPLATES / "evidence.json").read_text())
    (tmp_path / "evidence.json").write_text(json.dumps(index))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "evidence.json", name, CANDIDATE, current_spec(), NOW)
    record = ProbeRecord(
        format="jana.ops.probe.1",
        test_name=name,
        candidate_commit=CANDIDATE,
        spec_revision=current_spec(),
        source=SOURCES[name],
        started_at=NOW,
        completed_at=NOW,
        data=template["data"],
    )
    assert field_errors(name, FieldEvidence(record, {}), NOW)


# ------------------------------------------------------------------------------------------- dry runs
@pytest.mark.parametrize("drill_id", DRILLS)
def test_dry_run_exercises_the_checklist_and_never_passes(drill_id: str, tmp_path: Path):
    drill = DRILLS[drill_id]
    result = run(drill, tmp_path, Rehearsal(), candidate=CANDIDATE, spec_revision=current_spec())
    index = json.loads((tmp_path / "evidence.json").read_text())
    assert index["candidate_commit"] == ZERO
    for name in drill.tests:
        assert result["verdict"][name]
        # Even read against its own all-zero identity, the rehearsal markers alone refuse it.
        with pytest.raises(ValueError, match="placeholder or rehearsal"):
            read_evidence(tmp_path / "evidence.json", name, ZERO, ZERO, NOW)


def test_real_evidence_is_never_written_inside_the_repository():
    with pytest.raises(ValueError, match="inside the repository"):
        run(DRILLS["ops21"], REPO_ROOT / "evidence-test", Scripted({}), candidate=CANDIDATE, spec_revision=ZERO)
    assert not (REPO_ROOT / "evidence-test").exists()


# ------------------------------------------------------------------------------------------- checklist output
def proof(tmp_path: Path, name: str, body: str | None = None) -> str:
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else f"synthetic proof file {name}")
    return str(path)


def synthetic_answers(drill_id: str, raw: Path) -> list[dict[str, Any]]:
    common = {"device": "synthetic test device", "reviewer": "synthetic reviewer"}
    lagos = {"timezone": "Africa/Lagos", "holidays": ""}
    if drill_id == "ops07":
        runs = [
            {
                "passed": "y",
                "zero_egress": "y",
                "replay_before": "b" * 64,
                "replay_after": "b" * 64,
                "steps": "all",
                "evidence": proof(raw, f"run-{n}.log"),
            }
            for n in range(9)
        ]
        return [
            {
                **common,
                "candidate_version": "1.1.0",
                "platforms": "windows",
                "supported_apps": "1.0.0",
                "os_network_blocked": "y",
                "runs": runs,
            }
        ]
    if drill_id == "ops11":
        targets = [{"as_expected": "y", "note": ""} for _ in range(11)]
        return [{**common, "targets": targets, "unverified_numbers_shown": "0", "recording": proof(raw, "rec.mp4")}]
    if drill_id == "ops12":
        return [
            {
                **common,
                "switched_at": at(minutes=10),
                "all_local_at": at(minutes=7),
                "turns": "10",
                "failed_turns": "0",
                "local_turns": "10",
                "max_refusal_s": "0.2",
                "report": proof(raw, "load.txt"),
            }
        ]
    if drill_id == "ops15":
        checks = [
            {
                "media_id": f"stick-{n}",
                "sha256": "c" * 64,
                "hardware": "low",
                "offline_install": "y",
                "hash_verified": "y",
                "operator": "synthetic operator",
                "at": at(hours=1),
                "evidence": proof(raw, f"s{n}.jpg"),
            }
            for n in range(3)
        ]
        return [{**common, "batch_size": "50", "kit_sha256": "c" * 64, "checks": checks}]
    if drill_id == "ops17-slo":
        services = [
            {"injected": "y", "requests": "100", "failures": "50", "latencies_s": "0.1,0.1,0.1", "alert_delay_s": "60"}
            for _ in range(6)
        ]
        return [{**common, "services": services, "receipts": proof(raw, "alerts.txt")}]
    if drill_id == "ops17-words":
        return [
            {
                **common,
                "accepted_text": "y",
                "all_gates_enabled": "y",
                "reference_low": "1.0,1.2,1.5",
                "s4_web": "",
                "probe_log": proof(raw, "probe.txt"),
            }
        ]
    if drill_id == "ops18":
        return [
            {
                **common,
                "active_students": "1000",
                "tested_concurrency": "300",
                "contracted_concurrency": "300",
                "objectives_passed": "y",
                "school_quotas_enforced": "y",
                "report": proof(raw, "load.txt"),
            }
        ]
    if drill_id == "ops20":
        return [
            {
                **common,
                "outage_at": at(minutes=60),
                "fallback_at": at(minutes=58),
                "primary_healthy_since": at(minutes=50),
                "primary_restored_at": at(minutes=30),
                "failed_turns": "0",
                "fallback_turns": "5",
                "log": proof(raw, "gw.log"),
            }
        ]
    if drill_id == "ops21":
        # A Sunday night in the pilot time zone: outside school hours.
        return [
            {
                **common,
                **lagos,
                "sev1": "y",
                "sent_at": "2026-10-11T02:00:00+01:00",
                "acknowledged_at": "2026-10-11T02:20:00+01:00",
                "operator": "synthetic on-call",
                "receipt": proof(raw, "pager.txt"),
            }
        ]
    if drill_id == "ops25":
        guides = [
            {"pdf": proof(raw, f"guide{n}.pdf", f"%PDF-1.7 synthetic guide {n}"), "reader_checked": "y"}
            for n in range(6)
        ]
        return [{**common, "app_version": "1.0.0", "docs_version": "1.0", "guides": guides}]
    if drill_id == "uxs46":
        from agent_core.config import Settings
        from agent_core.config.support import settings_sections

        sections = [{"renders": "y"} for _ in settings_sections(Settings().build_stage)]
        return [
            {
                **common,
                "order_matches": "y",
                "sections": sections,
                "pin_prompts": "0",
                "removed_keys": "",
                "os_network_blocked": "y",
                "nonloopback_attempts": "0",
                "recording": proof(raw, "ui.mp4"),
            }
        ]
    if drill_id == "wrong-key":
        return [
            {
                **common,
                **lagos,
                "reported_at": "2026-10-12T09:00:00+01:00",
                "triaged_at": "2026-10-12T10:00:00+01:00",
                "confirmed_at": "2026-10-12T11:00:00+01:00",
                "withdrawn_at": "2026-10-12T12:00:00+01:00",
                "notified_at": "2026-10-12T13:00:00+01:00",
                "corrected_at": "2026-10-14T12:00:00+01:00",
                "old_item_id": "synthetic-old",
                "new_item_id": "synthetic-new",
                "old_item_served": "n",
                "affected_attempts": "3",
                "remarked_attempts": "3",
                "original_attempts_sha256": "d" * 64,
                "retained_attempts_sha256": "d" * 64,
                "projections_equal_full_replay": "y",
                "affected_licences": "lic-synthetic",
                "notified_licences": "lic-synthetic",
                "log": proof(raw, "staging.log"),
            }
        ]
    if drill_id == "tabletop":
        return [
            {
                **common,
                "stage": "S2",
                "gate": "pilot_start",
                "incident_id": "synthetic-tabletop",
                "commander": "synthetic commander",
                "communications_lead": "synthetic comms",
                "safety_lead": "synthetic safety lead",
                "hold_group": "synthetic safety lead, synthetic deputy",
                "declared_at": at(hours=5),
                "severity": "SEV1",
                "acknowledged_at": at(hours=4.9),
                "triaged_at": at(hours=4.8),
                "handed_off_at": at(hours=4.7),
                "contained_at": at(hours=3),
                "notified_at": at(hours=2),
                "mitigated_at": at(hours=1),
                "channels": "online,usb",
                "no_student_contact": "y",
                "category_only": "y",
                "session_confirmation_checked": "y",
                "deletion_verified": "y",
                "notification_deadline_hours": "72",
                "regression_ref": "synthetic-regression",
                "review_date": NOW.date().isoformat(),
                "review_ref": "synthetic-review",
                "notes": proof(raw, "notes.txt"),
            }
        ]
    if drill_id == "ops32":
        receipt = {
            "recipient_kind": "registered_contact",
            "route": "phone",
            "first_contact_at": at(hours=2),
            "email_at": at(hours=1.5),
            "kit_id": "synthetic-kit",
            "instructions": "synthetic instructions",
            "receipt": proof(raw, "call.txt"),
        }
        return [
            {
                **common,
                "incident_id": "synthetic-sev2",
                "severity": "SEV2",
                "category": "wrong_content",
                "commander": "synthetic commander",
                "communications_lead": "synthetic comms",
                "declared_at": at(hours=5),
                "acknowledged_at": at(hours=4.5),
                "contained_at": at(hours=3),
                "affected_licences": "lic-synthetic",
                "offline_licences": "lic-synthetic",
                "receipts": [receipt],
            }
        ]
    if drill_id == "ops34":
        from agent_core.config import Settings
        from jana_tools.release.incidents import required_drills

        return [
            {
                **common,
                "term_start": at(days=30),
                "release_at": at(days=2),
                "name": name,
                "owner": "synthetic owner",
                "at": at(days=1),
                "passed": "y",
                "trigger": "synthetic trigger",
                "steps": "a,b",
                "verification": "synthetic check",
                "rollback": "synthetic rollback",
                "offline_copy": "synthetic copy",
                "evidence": proof(raw, f"{name}.txt"),
                "actions": [],
            }
            for name in required_drills(Settings().build_stage)
        ]
    raise KeyError(drill_id)


@pytest.mark.parametrize("drill_id", DRILLS)
def test_checklist_writes_exactly_what_the_gate_reads(drill_id: str, tmp_path: Path):
    folder = tmp_path / "evidence"
    for answers in synthetic_answers(drill_id, tmp_path):
        result = run(DRILLS[drill_id], folder, Scripted(answers), candidate=CANDIDATE, spec_revision=current_spec())
    for name in DRILLS[drill_id].tests:
        assert result["verdict"][name] == [], (name, result["verdict"][name])
        assert check(folder / "evidence.json", name) == []
    if drill_id == "tabletop":
        governance = json.loads((folder / "tabletop-pilot_start.json").read_text())
        assert record_errors("tabletop", governance, candidate=CANDIDATE) == []


def test_ops07_checklist_for_the_very_first_release(tmp_path: Path):
    """D96: the first release lists only its own version; the checklist then asks for the fresh runs alone, and the
    gate accepts them. The same three runs with the candidate listed beside an older version are refused."""
    answers = synthetic_answers("ops07", tmp_path)[0]
    first = {**answers, "candidate_version": "1.0.0", "supported_apps": "1.0.0", "runs": answers["runs"][:3]}
    folder = tmp_path / "evidence"
    result = run(DRILLS["ops07"], folder, Scripted(first), candidate=CANDIDATE, spec_revision=current_spec())
    assert result["verdict"] == {name: [] for name in DRILLS["ops07"].tests}
    record = json.loads((folder / "ops07" / "ops07_skip_version_upgrades.probe.json").read_text())
    assert {r["previous"] for r in record["data"]["runs"]} == {"fresh"}
    later = {**answers, "candidate_version": "1.0.0", "supported_apps": "0.9.0,1.0.0"}
    result = run(DRILLS["ops07"], tmp_path / "later", Scripted(later), candidate=CANDIDATE,
                 spec_revision=current_spec())  # fmt: skip
    assert all(result["verdict"].values())


def test_each_stage_gate_assembles_its_own_tabletop(tmp_path: Path):
    """PRV-21: the drill keeps one record per gate, and assembling a gate takes that gate's exercise only."""
    answers = synthetic_answers("tabletop", tmp_path)[0]
    folder = tmp_path / "evidence"
    run(DRILLS["tabletop"], folder, Scripted(answers), candidate=CANDIDATE, spec_revision=current_spec())
    held = json.loads((folder / "tabletop-pilot_start.json").read_text())
    assert held["gate"] == "pilot_start"
    assert record_errors("tabletop", held, candidate=CANDIDATE, gate="pilot_start") == []
    assert record_errors("tabletop", held, candidate=CANDIDATE, gate="s2_launch") == [
        "PRV-21: no tabletop recorded for the s2_launch gate"
    ]

    def assembled(gate: str) -> Any:
        assemble(folder, candidate=CANDIDATE, stage="S2", gate=gate)
        return json.loads((folder / "release.json").read_text()).get("tabletop")

    assert assembled("pilot_start") == held
    assert assembled("s2_launch") is None  # the pilot's exercise is not carried over to the launch gate
    run(DRILLS["tabletop"], folder, Scripted({**answers, "gate": "s2_launch"}), candidate=CANDIDATE,
        spec_revision=current_spec())  # fmt: skip
    launch = assembled("s2_launch")
    assert launch["gate"] == "s2_launch"
    assert record_errors("tabletop", launch, candidate=CANDIDATE, gate="s2_launch") == []
    assert assembled("pilot_start") == held


def test_tabletop_answered_later_stays_refused(tmp_path: Path):
    answers = synthetic_answers("tabletop", tmp_path)[0]
    answers.update(review_date="later", review_ref="later")
    run(DRILLS["tabletop"], tmp_path / "evidence", Scripted(answers), candidate=CANDIDATE, spec_revision=current_spec())
    governance = json.loads((tmp_path / "evidence" / "tabletop-pilot_start.json").read_text())
    assert any("placeholder" in e for e in record_errors("tabletop", governance, candidate=CANDIDATE))


def test_interactive_checklist_asks_again_until_an_answer_is_valid(tmp_path: Path):
    answers = synthetic_answers("ops21", tmp_path)[0]
    typed = iter(
        [
            "synthetic device",
            "Not/AZone",
            "Africa/Lagos",
            "",
            "maybe",
            "y",
            "2026-10-11 02:00",
            answers["sent_at"],
            answers["acknowledged_at"],
            "synthetic on-call",
            answers["receipt"],
            "synthetic reviewer",
        ]
    )
    shown: list[str] = []
    source = Interactive(read=lambda prompt: next(typed), write=shown.append)
    result = run(DRILLS["ops21"], tmp_path / "evidence", source, candidate=CANDIDATE, spec_revision=current_spec())
    assert result["verdict"]["ops21_after_hours_page_drill"] == []
    assert sum("->" in line for line in shown) == 3  # bad zone, bad yes/no, time without a zone


# ------------------------------------------------------------------------------------- wrong-key learner replay
def test_wrong_key_remark_runs_on_a_closed_device_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The `wrong-key` drill's learner replay (OPS-27, CUR-36): `evidence remark` re-marks a test device's data
    folder after the withdrawal, prints the checklist's numbers and keeps the run as a proof. Synthetic learner."""
    import asyncio
    import importlib.util

    from agent_core.config import Settings
    from agent_core.engine.assembly import AppRuntime
    from agent_core.engine.assessment.service import AssessmentDesk
    from agent_core.learner.mastery import MasteryParams
    from agent_core.learner.service import Learner
    from jana_tools.__main__ import main

    spec = importlib.util.spec_from_file_location(
        "m24remark", REPO_ROOT / "services" / "agent-core" / "tests" / "test_m24_remark.py"
    )
    assert spec and spec.loader
    m24 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m24)
    content = m24.index(m24.item(m24.OLD, "b"), m24.item(m24.NEW, "a"), m24.item(m24.OTHER, "a"))
    monkeypatch.setattr(AppRuntime, "content", lambda self: content)
    data = tmp_path / "device"
    device = AppRuntime(Settings(), REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", data)
    device.open_stores("1.0.0")
    assert device.stores is not None
    clock = m24.Clock()
    learner = Learner.open(device.stores.learner, profile_id=device.stores.profile_id,
                           device_id=device.stores.device_id, wall_ms=lambda: clock.wall,
                           max_skew_ms=Settings().sync_clock_skew_max_ms,
                           params=MasteryParams.from_settings(Settings()), content=content)  # fmt: skip
    m24.answer_all(AssessmentDesk(learner, content, Settings(), clock_ms=lambda: clock.wall), clock,
                   {m24.OLD: m24.item(m24.OLD, "b"), m24.OTHER: m24.item(m24.OTHER, "a")})  # fmt: skip
    m24.withdraw(device.operation_policy(), m24.OLD)
    asyncio.run(device.close())
    out = tmp_path / "remark.json"
    assert main(["evidence", "remark", "--data", str(data), "--old", m24.OLD, "--new", m24.NEW, "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out.split("\nwrote ")[0])
    assert printed["affected_attempts"] == printed["remarked_attempts"] == 4
    assert printed["original_attempts_sha256"] == printed["retained_attempts_sha256"]
    assert printed["projections_equal_full_replay"] is True
    assert json.loads(out.read_text())["device"] == printed
    assert main(["evidence", "remark", "--data", str(tmp_path / "nothing"), "--old", "a", "--new", "b"]) == 1
