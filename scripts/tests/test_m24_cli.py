"""Release operations CLI refuses incomplete evidence (OPS-06, OPS-16, OPS-38)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jana_tools import REPO_ROOT


def command(*args):
    return subprocess.run(
        [str(REPO_ROOT / ".venv/bin/python"), "-m", "jana_tools", "release", "ops", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_ops_cli_refuses_missing_gate(tmp_path: Path):
    dossier = tmp_path / "release.json"
    dossier.write_text(
        json.dumps(
            {"candidate": {"kind": "app", "version": "1.0.0", "sha256": "a" * 64, "channel": "stable"}, "gates": {}}
        )
    )
    promoted = tmp_path / "promoted.json"
    result = command("promote", "--input", str(dossier), "--out", str(promoted))
    assert result.returncode != 0 and not promoted.exists()
    assert "OPS-06" in result.stdout


def test_ops_cli_budget_and_policy_export(tmp_path: Path):
    evidence = tmp_path / "budget.json"
    evidence.write_text(json.dumps({"amounts": {"app_patch": 999999999}, "exceptions": {}}))
    result = command("validate", "--kind", "bandwidth", "--input", str(evidence))
    assert result.returncode == 1 and "OPS-16" in result.stdout
    result = command("gateway-config")
    assert result.returncode == 0 and json.loads(result.stdout)["probe_interval_s"] > 0


def test_ops_cli_does_not_overwrite_promotion_on_failure(tmp_path: Path):
    promoted = tmp_path / "promoted.json"
    promoted.write_text("existing record")
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert command("promote", "--input", str(bad), "--out", str(promoted)).returncode != 0
    assert promoted.read_text() == "existing record"


def test_ops_promotion_rejects_truthy_string_in_gate_report(tmp_path: Path):
    import hashlib
    from datetime import UTC, datetime

    from jana_tools.release.operations import required_gates

    gates = {}
    now = datetime.now(UTC).isoformat()
    for index, name in enumerate(sorted(required_gates("app"))):
        path = tmp_path / f"gate-{index}.json"
        path.write_text(json.dumps({"gate": name, "candidate_sha256": "a" * 64, "passed": True, "measured_at": now}))
        gates[name] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "reviewer": "staff"}
    dossier = tmp_path / "candidate.json"
    dossier.write_text(
        json.dumps(
            {
                "candidate": {"kind": "app", "version": "1.0.0", "sha256": "a" * 64, "channel": "stable"},
                "gates": gates,
                "signoffs": {
                    "manager": "manager",
                    "evaluation": "eval",
                    "safety": "safety",
                    "security": "security",
                    "decision": "go",
                },
                "freezes": [],
                "notes": {
                    "it": "it",
                    "reviewers": "review",
                    "parents": "parent",
                    "students": ["change"],
                    "privacy_notice": "n1",
                },
                "previous_notice": "n1",
                "previous_data_policy": {},
                "data_policy": {},
            }
        )
    )
    assert command("promote", "--input", str(dossier), "--out", str(tmp_path / "valid-go.json")).returncode == 0
    invalid = json.loads(path.read_text())
    invalid["passed"] = "yes"
    path.write_text(json.dumps(invalid))
    gates[name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    updated = json.loads(dossier.read_text())
    updated["gates"] = gates
    dossier.write_text(json.dumps(updated))
    assert command("promote", "--input", str(dossier), "--out", str(tmp_path / "go.json")).returncode != 0
