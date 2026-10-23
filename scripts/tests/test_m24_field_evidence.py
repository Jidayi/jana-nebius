"""M24 field gates. Synthetic policy regressions live separately from device/staff/UI evidence."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jana_tools import REPO_ROOT
from jana_tools.release.field_evidence import field_errors, read_evidence


def accept(name: str) -> None:
    source = os.environ.get("JANA_M24_EVIDENCE")
    if not source:
        pytest.skip(f"{name}: needs candidate-bound device, staging, UI or staff evidence; see M24-STATUS.json")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    evidence = read_evidence(Path(source), name, head, (REPO_ROOT / "spec.lock").read_text().strip(), datetime.now(UTC))
    assert not field_errors(name, evidence, datetime.now(UTC))


def ops07_offline_lifecycle_script():
    accept("ops07_offline_lifecycle_script")


def ops07_skip_version_upgrades():
    accept("ops07_skip_version_upgrades")


def ops15_physical_kit_verified():
    accept("ops15_physical_kit_verified")


def ops17_slo_alerting():
    accept("ops17_slo_alerting")


def ops17_cloud_first_words_budget():
    accept("ops17_cloud_first_words_budget")


def ops18_load_test_at_twice_peak():
    accept("ops18_load_test_at_twice_peak")


def ops11_each_target_kind():
    accept("ops11_each_target_kind")


def ops25_docs_match_version():
    accept("ops25_docs_match_version")


def uxs46_sections_complete():
    accept("uxs46_sections_complete")


def uxs46_no_answers_or_pin_sections():
    accept("uxs46_no_answers_or_pin_sections")


def uxs46_sections_offline():
    accept("uxs46_sections_offline")


def ops21_after_hours_page_drill():
    accept("ops21_after_hours_page_drill")


def ops27_wrong_key_hotfix_flow():
    accept("ops27_wrong_key_hotfix_flow")


def cur36_withdraw_and_remark():
    accept("cur36_withdraw_and_remark")


def ops31_child_safety_tabletop():
    accept("ops31_child_safety_tabletop")


def ops32_schools_notified():
    accept("ops32_schools_notified")


def ops34_drills_current():
    accept("ops34_drills_current")


def ops12_global_cloud_off():
    accept("ops12_global_cloud_off")


def ops20_failover_drill():
    accept("ops20_failover_drill")
