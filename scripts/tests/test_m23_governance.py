"""M23 gates validate synthetic evidence, never approve a real pilot or release."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest
from agent_core.config import Settings

CANDIDATE = "a" * 40
TODAY = date(2026, 10, 16)


def evidence():
    from jana_tools.m23.gates import FUZZ_TARGETS, LEGAL_TOPICS, SECURITY_TESTS

    return {
        "candidate": CANDIDATE,
        "stage": "S2",
        "gate": "pilot_start",
        "counsel": {
            "country": "XX",
            "reviewed_at": "2026-10-15",
            "reviewer": "counsel-role",
            "topics": {
                k: {"reference": "synthetic-ref", "finding": "synthetic finding", "reviewed": True}
                for k in LEGAL_TOPICS
            },
        },
        "tabletop": {
            "stage": "S2",
            "gate": "pilot_start",
            "severity": "SEV1",
            "date": "2026-10-15",
            "owner": "Safety lead",
            "timings": {k: 1 for k in ("triage_hours", "notify_hours", "mitigate_hours", "review_workdays")},
            "notification_deadline_hours": 12,
            "regression_ref": "synthetic-case",
            "channels": ["online", "usb"],
            "review_ref": "synthetic-review",
        },
        "redteam": {
            "candidate": CANDIDATE,
            "stage": "S2",
            "date": "2026-10-15",
            "owner": "Safety lead",
            "languages": ["en"],
            "categories": ["safety", "photo_injection"],
            "failures": [],
            "privacy_audit_ref": "synthetic-audit",
        },
        "security": {
            "candidate": CANDIDATE,
            "tests": {k: {"status": "pass", "evidence": "synthetic-ref"} for k in SECURITY_TESTS},
            "fuzz_hours": {k: Settings().security_fuzz_hours_per_target for k in FUZZ_TARGETS},
            "sandbox_os": ["windows", "macos", "linux"],
            "findings": [],
        },
    }


def prv07_counsel_review_recorded():
    from jana_tools.m23.gates import LEGAL_TOPICS, release_errors

    value = evidence()
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY) == []
    for topic in LEGAL_TOPICS:
        bad = copy.deepcopy(value)
        bad["counsel"]["topics"][topic]["reviewed"] = False
        assert any(
            "PRV-07" in e for e in release_errors(bad, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
        )


def prv21_tabletop_recorded():
    from jana_tools.m23.gates import release_errors

    wrong = ({"severity": "SEV3"}, {"stage": "S1"}, {"gate": "s2_launch"}, {"timings": {}}, {"channels": ["online"]})
    for changes in wrong:
        value = evidence()
        value["tabletop"].update(changes)
        assert any(
            "PRV-21" in e
            for e in release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
        )


def test_tabletop_is_held_for_each_stage_gate():
    """PRV-21: one tabletop per stage gate. S2 has two gates, so an exercise held for pilot_start never counts for
    s2_launch; each gate passes only with a record naming it, and a record naming no gate counts for none."""
    from jana_tools.m23.gates import release_errors, section_errors

    value = evidence()
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY) == []
    launch = copy.deepcopy(value)
    launch["gate"] = "s2_launch"
    errors = release_errors(launch, candidate=CANDIDATE, stage="S2", gate="s2_launch", today=TODAY)
    assert errors == ["PRV-21: no tabletop recorded for the s2_launch gate"]
    launch["tabletop"]["gate"] = "s2_launch"
    assert release_errors(launch, candidate=CANDIDATE, stage="S2", gate="s2_launch", today=TODAY) == []
    unnamed = copy.deepcopy(value)
    del unnamed["tabletop"]["gate"]
    assert any(
        "PRV-21" in e for e in release_errors(unnamed, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
    )
    # Checked on its own, a tabletop is judged for the gate asked about, or else for the gate it names.
    record = value["tabletop"]
    assert section_errors("tabletop", record, candidate=CANDIDATE, stage="S2", today=TODAY) == []
    assert section_errors("tabletop", record, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY) == []
    assert section_errors("tabletop", record, candidate=CANDIDATE, stage="S2", gate="s2_launch", today=TODAY)


def test_tabletop_has_no_recency_window():
    """PRV-21 asks for a tabletop per stage gate and states no recency, so the red-team window (PRV-23) does not
    apply: an older exercise for this gate counts, an undated or future-dated one does not."""
    from jana_tools.m23.gates import release_errors

    value = evidence()
    value["tabletop"]["date"] = (TODAY - timedelta(days=Settings().redteam_max_age_days + 30)).isoformat()
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY) == []
    for when in ((TODAY + timedelta(days=1)).isoformat(), "not-a-date"):
        value = evidence()
        value["tabletop"]["date"] = when
        assert any(
            "PRV-21" in e
            for e in release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
        )


def prv23_redteam_before_gate():
    from jana_tools.m23.gates import release_errors

    for delta in (-1, Settings().redteam_max_age_days + 1):
        value = evidence()
        value["redteam"]["date"] = (TODAY - timedelta(days=delta)).isoformat()
        assert any(
            "PRV-23" in e
            for e in release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
        )
    value = evidence()
    value["redteam"]["failures"] = [{"id": "new-case", "regression_ref": ""}]
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)


def sec25_release_blocked_on_security_tests():
    from jana_tools.m23.gates import SECURITY_TESTS, release_errors

    for name in SECURITY_TESTS:
        value = evidence()
        value["security"]["tests"].pop(name)
        assert any(
            "SEC-25" in e
            for e in release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
        )
    for finding in ({"severity": "high", "status": "open"}, {"severity": "critical", "status": "open"}):
        value = evidence()
        value["security"]["findings"] = [finding]
        assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)
    value = evidence()
    value["security"]["candidate"] = "b" * 40
    assert release_errors(value, candidate=CANDIDATE, stage="S2", gate="pilot_start", today=TODAY)


def sec26_security_release_reaches_offline_channels(tmp_path):
    from jana_tools.m23.gates import security_release

    source = tmp_path / "fix.janaupdate"
    source.write_bytes(b"synthetic signed update stand-in")
    output = tmp_path / "runbook"
    result = security_release(source, output, version="0.1.1", contacts=["family-contract", "lab-contract"])
    assert (output / result["offline_pack"]).read_bytes() == source.read_bytes()
    assert json.loads((output / "notifications.json").read_text())["contacts"] == ["family-contract", "lab-contract"]
    assert result["channels"] == ["online", "usb"]
    with pytest.raises(ValueError):
        security_release(source, output, version="0.1.1", contacts=[])


def prd22_pilot_checklist_gate():
    from jana_tools.m23.programme import COUNTRY_FIELDS, country_errors

    value = {
        "country": "XX",
        "locale": "en-XX",
        "currency_code": "XXX",
        "currency_symbol": "X",
        "items": {name: "synthetic-evidence" for name in COUNTRY_FIELDS},
    }
    assert country_errors(value) == []
    for field in COUNTRY_FIELDS:
        bad = copy.deepcopy(value)
        bad["items"].pop(field)
        assert field in " ".join(country_errors(bad))
    # The pilot build's own check (agent_core.config.pilot, used when a pilot profile is created): a complete signed
    # record passes; one with a row missing, empty or still a template is refused and the rows are named, even
    # though the record no longer satisfies its contract; an unsigned or test-root record never passes in a pilot.
    from agent_core.config.environments import Environment
    from agent_core.config.pilot import country_record_errors
    from signing_service.hierarchy import dev_signer, dev_trust
    from signing_service.keys import Purpose
    from test_m25b_gates import country_record

    signed = country_record()
    assert country_record_errors(signed, Environment.DEV, dev_trust()) == []
    for field in COUNTRY_FIELDS:
        for broken in ("", "FILL-IN", None):
            record = copy.deepcopy(signed)
            if broken is None:
                record["items"].pop(field)
            else:
                record["items"][field] = broken
            refused = country_record_errors(record, Environment.DEV, dev_trust())
            assert refused and refused[0] == f"PRD-22: missing {field}", refused
    assert country_record_errors(signed, Environment.PILOT, dev_trust())  # the test root is refused in a pilot
    unsigned = {k: v for k, v in signed.items() if k != "signature"}
    assert country_record_errors(unsigned, Environment.DEV, dev_trust())
    resigned = dev_signer(Purpose.CONTENT).sign("pilot_country", {**unsigned, "country": "YY"})
    assert "PRD-22: missing locale" in country_record_errors(resigned, Environment.DEV, dev_trust())


def test_release_cli_requires_m23_evidence(monkeypatch, capsys):
    from jana_tools.__main__ import main

    assert main(["m23", "release-check", "--candidate", CANDIDATE, "--stage", "S2", "--gate", "pilot_start"]) == 1
    assert "missing" in capsys.readouterr().out
