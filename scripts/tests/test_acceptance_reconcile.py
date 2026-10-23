"""Reconciliation distinguishes executed software checks, stale runs, absent definitions and external evidence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from jana_tools import acceptance_reconcile as report

PREFIX = "zzz" + "01_"


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "spec.lock").write_text("0" * 40)
    (root / "test_fixture.py").write_text(f"def {PREFIX}case():\n    assert 1 + 1 == 2\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Synthetic", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture"],
        cwd=root,
        check=True,
    )
    monkeypatch.setattr(report, "primary_requirements", lambda *a, **k: [("M0.a", "ZZZ-01")])
    monkeypatch.setattr(report, "acceptance_tests", lambda *a, **k: [PREFIX + "case", PREFIX + "absent"])
    return root, report.prepare(root)


def result(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        f'<testsuite><testcase name="{PREFIX}case">{body}</testcase><testcase name="{PREFIX}absent"/></testsuite>'
    )
    return path


def test_executed_check_is_bound_but_missing_definition_and_external_review_stay_open(candidate, tmp_path):
    root, manifest = candidate
    value = report.reconcile(
        manifest, ["M0"], [result(tmp_path)], {PREFIX + "case": {"external": ["Independent device observation"]}}, root
    )
    assert value["results_bound"] and value["counts"] == {"pass": 1, "missing": 1}
    assert value["rows"][0]["acceptance"] == "external evidence required"
    assert not value["candidate_acceptance"]
    assert value["artifacts"][0]["sha256"]


@pytest.mark.parametrize("body,outcome", [("<failure/>", "fail"), ("<error/>", "fail"), ("<skipped/>", "skipped")])
def test_nonpassing_results_never_turn_into_pass(candidate, tmp_path, body, outcome):
    root, manifest = candidate
    value = report.reconcile(manifest, ["M0"], [result(tmp_path, body)], {}, root)
    assert value["rows"][0]["result"] == outcome


def test_changed_candidate_refuses_inherited_results(candidate, tmp_path):
    root, manifest = candidate
    evidence = result(tmp_path)
    (root / "test_fixture.py").write_text((root / "test_fixture.py").read_text() + "\n# Changed source\n")
    value = report.reconcile(manifest, ["M0"], [evidence], {}, root)
    assert not value["candidate_current"] and not value["results_bound"]
    assert value["rows"][0]["result"] == "not run"


def test_old_results_and_unexecuted_definitions_are_not_passes(candidate, tmp_path):
    root, manifest = candidate
    evidence = result(tmp_path)
    os.utime(evidence, (1, 1))
    value = report.reconcile(manifest, ["M0"], [evidence], {}, root)
    assert not value["results_bound"] and value["rows"][0]["result"] == "not run"
    assert report.reconcile(manifest, ["M0"], [], {}, root)["rows"][0]["result"] == "not run"


def test_private_specification_working_files_are_bound_even_when_ignored(candidate, tmp_path):
    root, _ = candidate
    (root / ".gitignore").write_text("docs/\n")
    directory = root / "docs/specification"
    directory.mkdir(parents=True)
    schema = directory / "fixture.schema.json"
    schema.write_text('{"type":"string"}')
    manifest = report.prepare(root)
    schema.write_text('{"type":"number"}')
    value = report.reconcile(manifest, ["M0"], [result(tmp_path)], {}, root)
    assert not value["candidate_current"] and not value["results_bound"]


def test_palette_proposal_input_is_bound_even_though_reports_are_excluded(candidate, tmp_path):
    root, _ = candidate
    directory = root / "scripts/governance"
    directory.mkdir(parents=True)
    proposal = directory / "app-completion-palette-proposal.json"
    proposal.write_text('{"fixture":"before"}')
    manifest = report.prepare(root)
    proposal.write_text('{"fixture":"after"}')
    value = report.reconcile(manifest, ["M0"], [result(tmp_path)], {}, root)
    assert not value["candidate_current"] and not value["results_bound"]


def test_acceptance_with_multiple_source_cases_requires_every_case(candidate, tmp_path):
    root, _ = candidate
    (root / "other").mkdir()
    (root / "other/test_fixture.py").write_text(f"def {PREFIX}case():\n    assert True\n")
    manifest = report.prepare(root)
    first = tmp_path / "first.xml"
    first.write_text(f'<testsuite><testcase classname="test_fixture" name="{PREFIX}case"/></testsuite>')
    partial = report.reconcile(manifest, ["M0"], [first], {}, root)
    assert partial["rows"][0]["result"] == "not run"
    assert partial["rows"][0]["unrun_definitions"] == ["other/test_fixture.py"]
    second = tmp_path / "second.xml"
    second.write_text(f'<testsuite><testcase classname="other.test_fixture" name="{PREFIX}case"/></testsuite>')
    assert report.reconcile(manifest, ["M0"], [first, second], {}, root)["rows"][0]["result"] == "pass"
