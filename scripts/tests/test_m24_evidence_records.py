"""Synthetic parser regressions, never field acceptance evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jana_tools.release.field_evidence import SOURCES, FieldEvidence, ProbeRecord, field_errors, read_evidence

NOW = datetime(2026, 10, 16, 21, tzinfo=UTC)


def files(tmp_path: Path):
    receipt = tmp_path / "pager.log"
    receipt.write_text("synthetic pager receipt")
    digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
    record = {
        "format": "jana.ops.probe.1",
        "test_name": "ops21_after_hours_page_drill",
        "candidate_commit": "a" * 40,
        "spec_revision": "b" * 40,
        "source": "staff_drill",
        "started_at": "2026-10-16T19:00:00Z",
        "completed_at": NOW.isoformat(),
        "data": {
            "calendar": {"timezone": "Africa/Lagos", "holidays": []},
            "page": {
                "signal": "SEV1",
                "sent_at": "2026-10-16T19:00:00Z",
                "acknowledged_at": "2026-10-16T19:10:00Z",
                "operator": "synthetic-operator",
                "evidence_sha256": digest,
            },
        },
    }
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(record))
    index = tmp_path / "index.json"
    body = {
        "format": "jana.ops.evidence.1",
        "candidate_commit": "a" * 40,
        "spec_revision": "b" * 40,
        "synthetic_data_only": True,
        "records": {
            record["test_name"]: {
                "source": "staff_drill",
                "reviewer": "synthetic-reviewer",
                "proofs": [
                    {"path": probe.name, "sha256": hashlib.sha256(probe.read_bytes()).hexdigest()},
                    {"path": receipt.name, "sha256": digest},
                ],
            }
        },
    }
    index.write_text(json.dumps(body))
    return index, probe, receipt, body


def test_field_evidence_binds_candidate_spec_and_raw_proofs(tmp_path: Path):
    index, _, receipt, _ = files(tmp_path)
    evidence = read_evidence(index, "ops21_after_hours_page_drill", "a" * 40, "b" * 40, NOW)
    assert field_errors("ops21_after_hours_page_drill", evidence, NOW) == []
    for head, spec in (("c" * 40, "b" * 40), ("a" * 40, "c" * 40)):
        with pytest.raises(ValueError):
            read_evidence(index, "ops21_after_hours_page_drill", head, spec, NOW)
    receipt.write_text("changed receipt")
    with pytest.raises(ValueError):
        read_evidence(index, "ops21_after_hours_page_drill", "a" * 40, "b" * 40, NOW)


def test_field_evidence_rejects_prohibited_fields_even_with_new_digest(tmp_path: Path):
    index, probe, _, body = files(tmp_path)
    record = json.loads(probe.read_text())
    record["data"]["student_name"] = "synthetic prohibited field"
    probe.write_text(json.dumps(record))
    body["records"][record["test_name"]]["proofs"][0]["sha256"] = hashlib.sha256(probe.read_bytes()).hexdigest()
    index.write_text(json.dumps(body))
    with pytest.raises(ValueError):
        read_evidence(index, record["test_name"], "a" * 40, "b" * 40, NOW)


def test_field_evidence_does_not_accept_a_numeric_data_flag(tmp_path: Path):
    index, _, _, body = files(tmp_path)
    body["synthetic_data_only"] = 1
    index.write_text(json.dumps(body))
    with pytest.raises(ValueError):
        read_evidence(index, "ops21_after_hours_page_drill", "a" * 40, "b" * 40, NOW)


@pytest.mark.parametrize("name", SOURCES)
def test_field_evidence_rejects_missing_observations(name):
    record = ProbeRecord(
        format="jana.ops.probe.1",
        test_name=name,
        candidate_commit="a" * 40,
        spec_revision="b" * 40,
        source=SOURCES[name],
        started_at=NOW,
        completed_at=NOW,
        data={},
    )
    assert field_errors(name, FieldEvidence(record, {}), NOW)


def test_ops_evidence_files_match_the_contracts(tmp_path: Path):
    from agent_core.contracts import validate

    index, probe, _, _ = files(tmp_path)
    validate("ops/field-evidence", json.loads(index.read_text()))
    validate("ops/probe-record", json.loads(probe.read_text()))


def test_ops_gateway_switch_contract():
    import pytest
    from agent_core.contracts import validate

    switch = {
        "kind": "global",
        "target": "*",
        "disabled": True,
        "actor": "synthetic-operator",
        "reason": "drill",
        "incident_id": "inc_synthetic",
    }
    validate("ops/cloud-switch", switch)
    with pytest.raises(ValueError):
        validate("ops/cloud-switch", {**switch, "target": "provider_a"})
