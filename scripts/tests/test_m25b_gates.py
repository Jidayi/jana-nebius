"""Every gate of the decisions register is enforced: its undecided decisions and its own evidence (PRD-11 (c), PRV-07,
PRV-08, PRD-22, D13, VOC-21, EVL-27, TABLE PRD-17a). Every record here is synthetic and approves nothing: the
signatures come from the published test root, which pilot and production builds refuse."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from jana_tools.release import dpia, gates, package_cli, stage
from jana_tools.spec import DOCS
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from test_m23_governance import evidence as m23_evidence

CANDIDATE = "a" * 40
TODAY = date(2026, 10, 16)
SIGNED_AT = "2026-10-10T00:00:00.000Z"


def dpia_record(gate: str, features: list[str], tmp_path: Path, number: int = 1) -> dict[str, Any]:
    document = tmp_path / f"dpia-{gate}-{number}.txt"
    document.write_text(f"synthetic assessment {gate} {number}\n")
    return {
        "id": f"DPIA-XX-{number:02d}",
        "gate": gate,
        "features": features,
        "country": "XX",
        "assessment_ref": document.name,
        "assessment_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
        "completed_at": "2026-10-08",
        "signed_at": "2026-10-09",
        "signed_by": {"role": "safety_lead", "reference": "synthetic-safety-lead"},
        "residual_risk_accepted": True,
    }


def signed_list(records: list[dict[str, Any]]) -> dict[str, Any]:
    return dev_signer(Purpose.CONTENT).sign("dpia_list", dpia.build_list(records, created_at=SIGNED_AT), now=SIGNED_AT)


def country_record() -> dict[str, Any]:
    from agent_core.config.pilot import COUNTRY_FIELDS

    value = {
        "country": "XX",
        "locale": "en-XX",
        "currency_code": "XXX",
        "currency_symbol": "X",
        "issued_at": SIGNED_AT,
        "items": {name: "synthetic-ref" for name in COUNTRY_FIELDS},
        "pilot_clearance": {
            "protocol_id": "synthetic-pilot",
            "registered_at": "2026-10-01T00:00:00Z",
            "baseline_at": "2026-10-02T00:00:00Z",
            "starts_at": "2026-10-03T00:00:00Z",
            "analysis_sha256": "a" * 64,
            "approval_ref": "synthetic-owner-approval",
        },
    }
    return dev_signer(Purpose.CONTENT).sign("pilot_country", value, now=SIGNED_AT)


def protocol(tmp_path: Path) -> dict[str, Any]:
    from test_m23_programme import protocol as synthetic_protocol

    return synthetic_protocol(tmp_path)


def dossier(gate: str, tmp_path: Path) -> dict[str, Any]:
    value: dict[str, Any] = {"gate": gate, "candidate": CANDIDATE}
    if gate in ("pilot_start", "cloud_tier"):
        release = m23_evidence()
        release["gate"] = gate
        release["tabletop"]["gate"] = gate
        value["release"] = release
        records = [dpia_record(gate, dpia.required(gate), tmp_path)]
        value["dpias"] = records
        value["dpia_list"] = signed_list(records)
    if gate == "pilot_start":
        value["country"] = country_record()
        value["protocol"] = protocol(tmp_path)
    if gate == "cloud_tier":
        value["counsel_pass"] = {
            "pass": 2,
            "gate": "cloud_tier",
            "counsel": copy.deepcopy(value["release"]["counsel"]),
            "providers": [
                {
                    "provider_ref": "synthetic-provider",
                    "processing_region": "synthetic-region",
                    "contract_ref": "synthetic-contract",
                    "retention_days": 0,
                    "used_for_training": False,
                }
            ],
        }
    if gate == "paid_launch":
        value["payment"] = {
            "country": "XX",
            "partner_ref": "synthetic-partner",
            "contract_ref": "synthetic-contract",
            "contract_signed_at": "2026-10-01",
            "data_processing_agreement_ref": "synthetic-dpa",
            "checkout_test_ref": "synthetic-checkout",
            "currency_code": "XXX",
        }
        installer = {"installer_sha256": "b" * 64, "signature_audit_ref": "synthetic", "antivirus_ref": "synthetic"}
        value["installers"] = {"candidate": CANDIDATE, "platforms": {"windows": installer, "macos": installer}}
        value["wtp"] = {
            "decision": "D10",
            "report_ref": "synthetic-report",
            "country": "XX",
            "parents": Settings().wtp_parent_min,
            "school_owners": Settings().wtp_school_owner_min,
            "methods": ["van_westendorp", "gabor_granger"],
            "comparisons": ["lesson_teachers", "exam_books", "elearning"],
        }
        value["pilot_exit"] = pilot_exit()
    if gate == "voice_launch":
        value["voice"] = {
            "candidate": CANDIDATE,
            "speech_pack": {"pack_id": "synthetic-speech", "version": "0.0.0", "sha256": "c" * 64},
            "sets": {"synthetic-voice-set": {"version": "1", "lock_sha256": "d" * 64}},
            "consented_adult_speech_only": True,
            "accents": ["synthetic-accent"],
            "languages": ["en"],
            "wer_subject_vocabulary": {"en": {"errors": 5, "words": 100}},
            "false_cutoffs": {"passed": 2, "total": 100},
            "raw_latex_spoken": 0,
            "spoken_number_mismatches": 0,
            "turn_latency": {"p50_s": 3.0, "p90_s": 6.0, "n": 50},
            "read_aloud_latency": {"p50_s": 0.8, "p90_s": 1.5, "n": 50},
            "intelligibility": {"synthetic-voice": 4.2},
            "device_lab_ref": "synthetic-lab-run",
        }
    if gate in ("web_launch", "mobile_launch"):
        client = "web" if gate == "web_launch" else "android"
        journeys = {f"JRN-{n:02d}": "passed" for n in range(3, 12)}
        journeys["JRN-11"] = "not_applicable"
        value["client_journeys"] = {"candidate": CANDIDATE, "client": client, "report_ref": "synthetic",
                                    "journeys": journeys}  # fmt: skip
        if gate == "web_launch":
            records = [dpia_record("web_launch", ["web_client"], tmp_path)]
            value["dpias"], value["dpia_list"] = records, signed_list(records)
    if gate == "fine_tune":
        value["tuned_model"] = {
            "candidate": CANDIDATE,
            "model_id": "synthetic-tuned",
            "base_model_id": "synthetic-base",
            "gate_report_ref": "synthetic-report",
            "gates_failed": [],
            "regressions_against_base": [],
            "contamination_check": {"status": "pass", "evidence_ref": "synthetic"},
        }
    return value


def pilot_exit() -> dict[str, Any]:
    return {
        "stage": "S2",
        "window": {"from": "2026-11-01", "to": "2027-01-31"},
        "crash_free_sessions": {"passed": 9990, "total": 10000},
        "weekly_active": {"passed": 70, "total": 100},
        "active_days_per_week": [3, 4, 3, 5, 2, 3],
        "learning_gain": {
            "effect_sd": 0.25,
            "interval": [0.05, 0.45],
            "registered_at": "2026-10-01T00:00:00Z",
            "first_data_at": "2026-11-01T00:00:00Z",
            "analysis_sha256": "e" * 64,
            "weeks": 10,
        },
        "core_journey_task_success": {"passed": 17, "total": 20},
    }


@pytest.fixture
def repository_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the owner's repository pins (hosts, TLS pins, the release root, reviewer keys, helplines), which
    are placeholders in this checkout: the dossier logic is tested here, the placeholders in their own test."""
    monkeypatch.setattr(gates, "service_errors", lambda *a: [])
    monkeypatch.setattr(gates, "trust_root_errors", lambda: [])
    monkeypatch.setattr(gates, "reviewer_errors", lambda: [])
    monkeypatch.setattr(gates, "helpline_errors", lambda country: [])
    monkeypatch.setattr(package_cli, "owner_pins", lambda release: [])
    monkeypatch.setattr(gates, "GATE_FIELD_EVIDENCE", {})


def check(gate: str, value: dict[str, Any], tmp_path: Path, **kw: Any) -> list[str]:
    docs = kw.pop("docs", DOCS)
    if gate == "voice_launch" and docs is DOCS:
        docs = tmp_path / "docs"
        shutil.copytree(DOCS / "specification" / "registers", docs / "specification" / "registers",
                        dirs_exist_ok=True)  # fmt: skip
        (docs / "implementation").mkdir(parents=True, exist_ok=True)
        (docs / "implementation" / "m25-acceptance.md").write_text("synthetic acceptance record\n")
    return gates.gate_errors(gate, value, candidate=CANDIDATE, today=TODAY, docs=docs, environment=Environment.DEV,
                             trust=dev_trust(), **kw)  # fmt: skip


def open_decision(tmp_path: Path, gate: str) -> Path:
    docs = tmp_path / "open-docs"
    shutil.copytree(DOCS / "specification" / "registers", docs / "specification" / "registers")
    register = docs / "specification" / "registers" / "decisions.json"
    data = json.loads(register.read_text())
    data["decisions"].append({"id": "D999", "title": "Synthetic open decision", "status": "open", "blocks": [gate]})
    register.write_text(json.dumps(data))
    (docs / "implementation").mkdir()
    (docs / "implementation" / "m25-acceptance.md").write_text("synthetic acceptance record\n")
    return docs


# --- PRD-11 (c) for every gate --------------------------------------------------------------------------------------


def test_every_register_gate_is_enforced(tmp_path: Path) -> None:
    """Each gate of the register is checked by the stage rule or the gate check, and an undecided decision blocking
    it is named among the refusals; no gate passes on missing evidence."""
    register = stage.register_gates()
    assert set(register) == gates.STAGE_GATES | set(gates.OTHER_GATES)
    for gate in register:
        docs = open_decision(tmp_path / gate, gate)
        refused = gates.gate_errors(gate, {}, candidate=CANDIDATE, today=TODAY, docs=docs)
        assert any("D999" in e for e in refused), gate
        assert len(refused) >= 2, gate  # the decision and the missing evidence or the stage rule
        assert gates.gate_errors(gate, {}, candidate=CANDIDATE, today=TODAY), gate
    assert gates.gate_errors("no_such_gate", {}, candidate=CANDIDATE) == [
        "decision no_such_gate: not a gate of the decisions register"
    ]


@pytest.mark.parametrize("gate", gates.OTHER_GATES)
def test_each_gate_passes_only_on_its_own_evidence(gate: str, tmp_path: Path, repository_ready: None) -> None:
    value = dossier(gate, tmp_path)
    expected = [e for e in check(gate, {}, tmp_path) if e.startswith("decision")]
    refusals = check(gate, value, tmp_path)
    assert refusals == expected, refusals  # only the register's own undecided decisions remain (D16, D21, D28)
    assert check(gate, {**value, "candidate": "b" * 40}, tmp_path)
    assert check(gate, {**value, "gate": "s2_launch"}, tmp_path)
    for section in [k for k in value if k not in ("gate", "candidate")]:
        smaller = {k: v for k, v in value.items() if k != section}
        assert len(check(gate, smaller, tmp_path)) > len(expected), (gate, section)


def test_gate_evidence_reasons_name_the_failing_item(tmp_path: Path, repository_ready: None) -> None:
    pilot = dossier("pilot_start", tmp_path)
    pilot["country"]["items"]["safety_resources"] = ""
    assert any("PRD-22: missing safety_resources" in e for e in check("pilot_start", pilot, tmp_path))
    pilot = dossier("pilot_start", tmp_path)
    pilot["release"]["counsel"]["country"] = "YY"
    assert "PRV-07: counsel's country differs from the pilot country" in check("pilot_start", pilot, tmp_path)
    cloud = dossier("cloud_tier", tmp_path)
    cloud["counsel_pass"]["pass"] = 1
    assert "D13: counsel's second pass (the cloud tier) is missing" in check("cloud_tier", cloud, tmp_path)
    cloud = dossier("cloud_tier", tmp_path)
    cloud["counsel_pass"]["counsel"]["topics"]["international_transfer"]["reviewed"] = False
    assert any("international_transfer" in e for e in check("cloud_tier", cloud, tmp_path))
    paid = dossier("paid_launch", tmp_path)
    paid["pilot_exit"]["crash_free_sessions"] = {"passed": 9000, "total": 10000}
    assert any(e.startswith("PRD-17: Crash-free sessions in pilot: unmet") for e in check("paid_launch", paid,
                                                                                         tmp_path))  # fmt: skip
    voice = dossier("voice_launch", tmp_path)
    voice["voice"]["wer_subject_vocabulary"]["en"] = {"errors": 20, "words": 100}
    voice["voice"]["raw_latex_spoken"] = 1
    found = check("voice_launch", voice, tmp_path)
    assert any("word error rate 20.0% in en" in e for e in found) and any("raw latex spoken 1" in e for e in found)
    web = dossier("web_launch", tmp_path)
    web["client_journeys"]["journeys"]["JRN-05"] = "failed"
    assert any("web fails JRN-05" in e for e in check("web_launch", web, tmp_path))
    tuned = dossier("fine_tune", tmp_path)
    tuned["tuned_model"]["contamination_check"]["status"] = "fail"
    assert any("contamination" in e for e in check("fine_tune", tuned, tmp_path))


def test_voice_waits_for_the_m25_acceptance_record(tmp_path: Path, repository_ready: None) -> None:
    """D97: S3 voice is accepted only after M25; without the record the voice gate refuses."""
    docs = tmp_path / "no-m25"
    shutil.copytree(DOCS / "specification" / "registers", docs / "specification" / "registers")
    found = check("voice_launch", dossier("voice_launch", tmp_path), tmp_path, docs=docs)
    assert found == ["D97: voice is accepted only after M25 (no M25 acceptance record)"]


def test_repository_placeholders_block_the_pilot_and_cloud_gates() -> None:
    """Until the owner pins them, the placeholder hosts, empty pins, absent release root, empty reviewer list and
    unverified helplines in this checkout refuse pilot_start and cloud_tier."""
    assert any(".invalid" in e for e in gates.service_errors("pilot", gates.GATE_SERVICES["pilot_start"]))
    assert any("TLS pins" in e for e in gates.service_errors("production", ("gateway",)))
    assert gates.trust_root_errors() == ["SEC-12: the build trusts no release root yet (the key ceremony)"]
    assert gates.reviewer_errors()
    assert any("verified" in e for e in gates.helpline_errors("XX"))


def test_release_pins_report_names_every_owner_placeholder() -> None:
    """`release pins --release` lists the .invalid hosts and empty pins of policy.json, the empty reviewer list and the
    safety-resources placeholders, as well as the PLACEHOLDER lines of the pin files."""
    found = package_cli.owner_pins(release=True)
    text = "\n".join(found)
    for expected in ("pilot hosts are placeholders (.invalid)", "production hosts are placeholders (.invalid)",
                     "pilot has no primary and backup TLS pins", "production has no primary and backup TLS pins",
                     "safety_reviewers.json: no content safety reviewer key", "resources.yaml: no pilot country",
                     "resources.yaml: no verified emergency number"):  # fmt: skip
        assert expected in text, expected
    assert not any("policy.json" in line for line in package_cli.owner_pins(release=False))


def test_gate_cli_refuses_with_reasons(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from jana_tools.__main__ import main

    path = tmp_path / "cloud.json"
    path.write_text(json.dumps(dossier("cloud_tier", tmp_path)))
    assert main(["release", "gate", "cloud_tier", "--evidence", str(path), "--candidate", CANDIDATE]) == 1
    err = capsys.readouterr().err
    assert "SEC-31" in err and "ops18_load_test_at_twice_peak" in err
    assert main(["release", "gate", "fine_tune", "--candidate", CANDIDATE]) == 1
    assert "D16" in capsys.readouterr().err


def test_m23_gate_commands_refuse_undecided_decisions(monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    from jana_tools.m23 import cli

    monkeypatch.setattr(stage, "undecided_for_gate", lambda gate, docs=DOCS: ["D999 (open): Synthetic"])
    assert cli.main(["release-check", "--candidate", CANDIDATE, "--stage", "S2", "--gate", "pilot_start"]) == 1
    assert "decision D999" in capsys.readouterr().out


# --- PRV-08: the DPIA record, the signed list and the gate ---------------------------------------------------------


def test_dpia_table_matches_the_specification() -> None:
    assert dpia.dpia_table_errors(DOCS) == []
    assert set(dpia.FEATURE_GATES.values()) == set(dpia.TABLE_GATES)


def test_dpia_records_build_the_list_the_device_reads(tmp_path: Path) -> None:
    """The list is built only from valid signed records, one entry per record with its features, and the device shows
    exactly those features and stores each one's own DPIA id with its consent (consents.dpia_ref)."""
    from agent_core.net.dpia import verify
    from agent_core.net.policy import load_policy

    first = dpia_record("pilot_start", ["telemetry", "crash_reports"], tmp_path, 1)
    second = dpia_record("pilot_start", ["downloads", "update_checks"], tmp_path, 2)
    assert dpia.record_errors(first, tmp_path) == []
    document = signed_list([first, second])
    approved = verify(document, Environment.DEV, dev_trust())
    policy = load_policy()
    assert sorted(approved.visible(policy)) == ["crash_reports", "downloads", "telemetry", "update_checks"]
    assert approved.ref(policy, "telemetry") == "DPIA-XX-01" and approved.ref(policy, "downloads") == "DPIA-XX-02"
    only = verify(signed_list([first]), Environment.DEV, dev_trust())
    assert sorted(only.visible(policy)) == ["crash_reports", "telemetry"]  # a gate-mate without its own DPIA hides
    with pytest.raises(ValueError, match="covered by both"):
        dpia.build_list([first, {**second, "features": ["telemetry"]}], created_at=SIGNED_AT)
    with pytest.raises(ValueError, match="not features of the pilot_start gate"):
        dpia.build_list([{**first, "features": ["cloud_tier"]}], created_at=SIGNED_AT)
    unsigned = {**first, "signed_by": {"role": "product_lead", "reference": "x"}}
    assert dpia.record_errors(unsigned)
    assert dpia.record_errors({**first, "signed_at": "2026-10-01"})  # signed before completed
    (tmp_path / first["assessment_ref"]).write_text("edited after signing\n")
    assert any("differs" in e for e in dpia.record_errors(first, tmp_path))
    template = {**second, "assessment_ref": "FILL-IN"}
    assert dpia.record_errors(template)


def test_dpia_gate_needs_every_feature_on_a_verified_list(tmp_path: Path) -> None:
    records = [dpia_record("pilot_start", dpia.required("pilot_start"), tmp_path)]
    good = signed_list(records)
    assert dpia.gate_errors("pilot_start", good, records, environment=Environment.DEV, trust=dev_trust()) == []
    assert dpia.gate_errors("pilot_start", good, records, environment=Environment.PILOT, trust=dev_trust())
    partial = [dpia_record("pilot_start", ["telemetry"], tmp_path)]
    missing = dpia.gate_errors("pilot_start", signed_list(partial), partial, environment=Environment.DEV,
                               trust=dev_trust())  # fmt: skip
    assert "PRV-08: no approved DPIA for research_data on the signed list" in missing
    assert dpia.gate_errors("pilot_start", good, [], environment=Environment.DEV, trust=dev_trust())
    forged = {**good, "approved": [*good["approved"], {"dpia_id": "DPIA-X", "gate": "cloud_tier",
                                                         "features": ["cloud_tier"]}]}  # fmt: skip
    assert any(
        "does not verify" in e
        for e in dpia.gate_errors("cloud_tier", forged, records, environment=Environment.DEV, trust=dev_trust())
    )
    assert dpia.gate_errors("s2_launch", {}, [], environment=Environment.DEV) == []  # no DPIA row for this gate


def test_dpia_list_cli_writes_the_unsigned_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from jana_tools.__main__ import main

    folder = tmp_path / "records"
    folder.mkdir()
    record = dpia_record("pilot_start", dpia.required("pilot_start"), folder)
    (folder / "dpia-01.json").write_text(json.dumps(record))
    out = tmp_path / "dpia_list.unsigned.json"
    assert main(["release", "dpia-list", "--records", str(folder), "--created-at", SIGNED_AT, "--out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert written["approved"] == [{"dpia_id": record["id"], "gate": "pilot_start",
                                    "features": sorted(record["features"])}]  # fmt: skip
    (folder / record["assessment_ref"]).write_text("changed\n")
    assert main(["release", "dpia-list", "--records", str(folder), "--created-at", SIGNED_AT, "--out", str(out)]) == 1
