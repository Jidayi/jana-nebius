"""Synthetic pilot registers and aggregate reports (EVL-22, BIZ-12..16)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from agent_core.config import Settings


def protocol(tmp_path):
    from jana_tools.m23.programme import PILOT_FIELDS

    script = tmp_path / "analysis.py"
    script.write_text("# synthetic frozen script\n")
    import hashlib

    return {
        "id": "synthetic-pilot",
        "country": "XX",
        "registered_at": "2026-10-01T00:00:00Z",
        "baseline_at": "2026-10-02T00:00:00Z",
        "starts_at": "2026-10-03T00:00:00Z",
        "analysis_script": {"path": str(script), "sha256": hashlib.sha256(script.read_bytes()).hexdigest()},
        "design": {name: "synthetic evidence" for name in PILOT_FIELDS},
        "weeks": 8,
        "minimum_effect_sd": 0.2,
        "classes": 10,
        "cluster": "class",
        "comparison_access_after": True,
        "school_approval": True,
        "guardian_research_consent": True,
        "student_assent": True,
    }


def evl22_protocol_registered(tmp_path):
    from jana_tools.m23.programme import protocol_errors

    value = protocol(tmp_path)
    assert protocol_errors(value) == []
    for field in ("registered_at", "analysis_script", "classes"):
        bad = copy.deepcopy(value)
        bad.pop(field)
        assert protocol_errors(bad)
    value["registered_at"] = value["baseline_at"]
    assert protocol_errors(value)
    value = protocol(tmp_path)
    Path(value["analysis_script"]["path"]).write_text("# changed\n")
    assert protocol_errors(value)


def biz15_pilot_protocol_complete(tmp_path):
    from jana_tools.m23.programme import PILOT_FIELDS, protocol_errors

    value = protocol(tmp_path)
    for name in PILOT_FIELDS:
        bad = copy.deepcopy(value)
        bad["design"].pop(name)
        assert name in " ".join(protocol_errors(bad))


def subjects():
    return [
        {
            "guardian_consent": True,
            "student_assent": True,
            "school_approval": True,
            "research_use": True,
            "withdrawn": False,
            "events": [],
            "kc_mastery": [],
            "display_name": "PRIVATE-CANARY",
            "roster_label": "PRIVATE-CANARY",
            "transcript": "PRIVATE-CANARY",
        }
        for _ in range(10)
    ]


def evl22_dataset_deidentified():
    from jana_tools.m23.programme import study_dataset

    value = study_dataset(subjects())
    assert "PRIVATE-CANARY" not in json.dumps(value)
    assert all(set(row) == {"study_id", "events", "kc_mastery"} for row in value)
    assert {r["study_id"] for r in value}.isdisjoint({r["study_id"] for r in study_dataset(subjects())})


def biz16_non_consented_excluded():
    from jana_tools.m23.programme import study_dataset

    value = subjects()
    for flag, bad in (
        ("guardian_consent", False),
        ("student_assent", False),
        ("school_approval", False),
        ("research_use", False),
        ("withdrawn", True),
    ):
        changed = copy.deepcopy(value)
        changed[-1][flag] = bad
        assert len(study_dataset(changed)) == 9


def biz13_wtp_evidence_linked():
    from jana_tools.m23.programme import wtp_errors

    value = {
        "decision": "D10",
        "report_ref": "synthetic-report",
        "country": "XX",
        "parents": Settings().wtp_parent_min,
        "school_owners": Settings().wtp_school_owner_min,
        "methods": ["van_westendorp", "gabor_granger"],
        "comparisons": ["lesson_teachers", "exam_books", "elearning"],
    }
    assert wtp_errors(value) == []
    for field in ("report_ref", "parents", "school_owners", "methods", "comparisons"):
        bad = copy.deepcopy(value)
        bad.pop(field)
        assert wtp_errors(bad)


def biz14_experiments_registered():
    from jana_tools.m23.programme import experiment_errors

    value = {
        "audience": "adults",
        "country": "XX",
        "currency_code": "XXX",
        "currency_symbol": "X",
        "tax_inclusive": True,
        "uses_student_data": False,
        "auto_renew_opt_in": True,
        "starts_at": "2026-10-01",
        "ends_at": "2026-10-08",
        "results_ref": "synthetic",
        "arms": [
            {"id": "a", "price": 1, "learning_build": "a" * 40},
            {"id": "b", "price": 2, "learning_build": "a" * 40},
        ],
    }
    assert experiment_errors([value]) == []
    for changes in ({"audience": "students"}, {"uses_student_data": True}, {"tax_inclusive": False}):
        bad = {**value, **changes}
        assert experiment_errors([bad])
    bad = copy.deepcopy(value)
    bad["arms"][1]["learning_build"] = "b" * 40
    assert experiment_errors([bad])


def weekly_input():
    return {
        "window": {"from": "2026-10-01", "to": "2026-10-08"},
        "participants": 10,
        "active_students": 10,
        "newly_mastered_kcs": 20,
        "guided_items": 20,
        "answer_leaks": 0,
        "unchecked_numbers": 0,
        "critical_safety_failures": 0,
        "completed_items": 20,
        "bottom_out_hints": 2,
        "activities_blocked": 0,
        "build": "a" * 40,
        "source": "research_export",
        "activity_scenarios_passed": True,
    }


def prd18_north_star_with_guardrails():
    from jana_tools.m23.programme import product_report

    value = weekly_input()
    result = product_report(value, Settings(product_bottom_out_share_max=0.2))
    assert result["north_star"]["value"] == 2
    assert len(result["guardrails"]) == 5
    assert all(r["window"] == value["window"] for r in [result["north_star"], *result["guardrails"]])
    assert result["release_allowed"]
    for metric in ("unchecked_numbers", "critical_safety_failures", "activities_blocked"):
        assert not product_report({**value, metric: 1})["release_allowed"]
    with pytest.raises(ValueError):
        product_report({**value, "source": "telemetry"})


def biz12_metrics_report_complete():
    from jana_tools.m23.programme import BUSINESS_METRICS, business_report

    values = {metric: {"numerator": 10, "denominator": 20, "sample_size": 20} for metric in BUSINESS_METRICS}
    report = business_report(values, window={"from": "2026-10-01", "to": "2026-11-01"})
    assert set(report["metrics"]) == set(BUSINESS_METRICS)
    assert all(r["sample_size"] == 20 and r["window"] == report["window"] for r in report["metrics"].values())
    assert report["telemetry_schema_valid"]
    missing = business_report({}, window=report["window"])
    assert all(r["value"] is None and r["status"] == "missing" for r in missing["metrics"].values())


def test_developer_dashboard_has_only_technical_metrics():
    from agent_core.config.telemetry_schema import report
    from jana_tools.m23.dashboard import dashboard

    value = report(
        {}, app_version="0.1.0", channel="pilot", hardware_class="low", os_family="linux", router_tier="local", days=1
    )
    result = dashboard([{"source": "telemetry", "payload": value}])
    assert result["reports"] == 1
    with pytest.raises(ValueError):
        dashboard([{"source": "school_analytics", "payload": value}])
    with pytest.raises(ValueError):
        dashboard([{"source": "telemetry", "payload": {**value, "notes": "PRIVATE-CANARY"}}])


def test_product_release_requires_guardrail_policy_and_evidence():
    from jana_tools.m23.programme import product_report

    raw = weekly_input()
    assert not product_report(raw)["release_allowed"]
    policy = Settings(product_bottom_out_share_max=0.2)
    assert product_report(raw, policy)["release_allowed"]
    assert not product_report({**raw, "bottom_out_hints": 10}, policy)["release_allowed"]
    assert not product_report({**raw, "participants": 0, "active_students": 0}, policy)["release_allowed"]


def test_dashboard_tracks_evaluation_fingerprints():
    from agent_core.config.telemetry_schema import report
    from jana_tools.m23.dashboard import dashboard

    value = report(
        {}, app_version="0.1.0", channel="pilot", hardware_class="low", os_family="linux", router_tier="local", days=1
    )
    result = dashboard(
        [
            {
                "source": "evaluation",
                "payload": value,
                "commit": "a" * 40,
                "model": "synthetic-model",
                "fingerprints": {"prompts": "a" * 64},
                "previous_fingerprints": {"prompts": "b" * 64},
            }
        ]
    )
    assert result["changes"][0]["fingerprints_changed"] == ["prompts"]
    assert "synthetic-model" not in json.dumps(result)
