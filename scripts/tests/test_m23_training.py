"""M23 tuning gate and isolated dataset builder; no model calls or held-out reads."""

from __future__ import annotations

import copy

import pytest


def record():
    from jana_tools.m23.training import RUNGS, SIGNOFFS

    return {
        "id": "tjr-2026-001",
        "target": "tool_call_format",
        "metric": "parse_rate",
        "threshold": 0.99,
        "direction": "higher",
        "success_margin": 0.02,
        "non_inferiority_margin": 0.01,
        "registered_at": "2026-10-01T00:00:00Z",
        "compute_budget": {"gpu_hours": 1, "max_usd": 1},
        "signoffs": {role: "synthetic-approval" for role in SIGNOFFS},
        "candidates": [
            {
                "candidate": char * 40,
                "value": 0.95,
                "interval95": [0.93, 0.97],
                "split": "held_out",
                "report_ref": "synthetic-report",
                "created_at": f"2026-09-{day}T00:00:00Z",
                "sequence": seq,
            }
            for char, day, seq in (("a", "28", 1), ("b", "29", 2))
        ],
        "ladder": {rung: {"revision_ids": ["synthetic-revision"], "effect": 0.0} for rung in RUNGS},
    }


def trn01_run_requires_approved_record(tmp_path):
    from jana_tools.m23.training import authorize_run

    value = record()
    with pytest.raises(ValueError):
        authorize_run({}, {}, tmp_path, now="2026-10-02T00:00:00Z")
    for role in value["signoffs"]:
        bad = copy.deepcopy(value)
        bad["signoffs"].pop(role)
        with pytest.raises(ValueError):
            authorize_run({"justification_id": value["id"]}, {value["id"]: bad}, tmp_path, now="2026-10-02T00:00:00Z")
    result = authorize_run(
        {"justification_id": value["id"]}, {value["id"]: value}, tmp_path, now="2026-10-02T00:00:00Z"
    )
    assert result["justification_id"] == value["id"]


def trn01_margins_frozen_after_first_run(tmp_path):
    from jana_tools.m23.training import authorize_run

    value = record()
    authorize_run({"justification_id": value["id"]}, {value["id"]: value}, tmp_path, now="2026-10-02T00:00:00Z")
    for field in ("success_margin", "non_inferiority_margin"):
        bad = copy.deepcopy(value)
        bad[field] *= 2
        with pytest.raises(ValueError, match="frozen"):
            authorize_run({"justification_id": value["id"]}, {value["id"]: bad}, tmp_path, now="2026-10-03T00:00:00Z")


def trn02_ladder_evidence_complete():
    from jana_tools.m23.training import RUNGS, justification_errors

    value = record()
    assert justification_errors(value) == []
    for rung in RUNGS:
        bad = copy.deepcopy(value)
        bad["ladder"][rung] = {"skip_reason": "not applicable"}
        assert justification_errors(bad)
        bad["ladder"][rung]["accepted_by"] = "Evaluation lead"
        assert justification_errors(bad) == []
    bad = copy.deepcopy(value)
    bad["candidates"][1]["value"] = 1.0
    assert justification_errors(bad)


def allowed():
    return {
        "source_kind": "synthetic_dialogue",
        "licence": "CC0-1.0",
        "training_permitted": True,
        "split": "development",
        "synthetic": True,
        "text": "an original synthetic explanation",
        "terms_ref": "synthetic-training-terms",
        "origin_ref": "staff-authored-synthetic-record",
    }


def trn07_source_allowlist(tmp_path):
    from jana_tools.m23.training import build_dataset

    for changes in (
        {"source_kind": "student_turn"},
        {"licence": ""},
        {"source_kind": "public_licensed"},
        {"split": "held_out"},
        {"training_permitted": False},
    ):
        with pytest.raises(ValueError):
            build_dataset([{**allowed(), **changes}], tmp_path / "refused")
    result = build_dataset([allowed()], tmp_path / "allowed")
    assert result["student_data"]["included"] is False


def trn08_builder_refuses_student_artefacts(tmp_path):
    from jana_tools.m23.training import build_dataset

    for kind in (
        "debug_bundle",
        "trace_export",
        "research_export",
        "crash_report",
        "learner_export",
        "problem_report",
        "profile_archive",
    ):
        with pytest.raises(ValueError, match="student_data_refused"):
            build_dataset([{**allowed(), "kind": kind}], tmp_path / kind)
    with pytest.raises(ValueError, match="student_data_refused"):
        build_dataset([{**allowed(), "profile_id": "synthetic"}], tmp_path / "forged")


def trn08_canary_absent_from_shards(tmp_path):
    from jana_tools.m23.training import build_dataset

    pilot = tmp_path / "device"
    pilot.mkdir()
    (pilot / "session.txt").write_text("PRIVATE-STUDENT-CANARY")
    output = tmp_path / "training"
    build_dataset([allowed()], output)
    assert "PRIVATE-STUDENT-CANARY" not in "".join(p.read_text() for p in output.iterdir())


def trn08_no_training_egress_path():
    from agent_core.net.policy import load_policy
    from agent_core.store.consents import shipped_features, shipped_scopes

    assert not any("train" in name for name in shipped_scopes() + shipped_features())
    policy = load_policy()
    assert not any("train" in name for name in policy.features)
    assert not any("train" in p for f in policy.features.values() for p in f.payload_classes)


def test_training_source_conditions_fail_closed(tmp_path):
    from jana_tools.m23.training import build_dataset

    for changes in (
        {"terms_ref": ""},
        {"licence": 7},
        {"source_kind": "research_consented"},
        {"source_kind": "teacher_exemplar", "contributor_agreement": ""},
        {"source_kind": "public_licensed", "licence_review": {"reviewer": "Curriculum lead"}},
        {"source_kind": "content_pack", "content_kind": "rubric"},
    ):
        bad = {**allowed(), **changes}
        with pytest.raises(ValueError):
            build_dataset([bad], tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
