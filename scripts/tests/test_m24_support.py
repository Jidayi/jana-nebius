"""Offline help, support intake and encrypted bundle lifecycle (OPS-22..25, UXS-46)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.config.support import BundleVault, HelpCatalogue, bundle_payload, intake_fields, settings_sections
from jana_tools import REPO_ROOT

NOW = datetime(2026, 10, 16, tzinfo=UTC)
EN = json.loads((REPO_ROOT / "packages" / "i18n" / "locales" / "en.json").read_text())


def search(query: str, catalogue: dict[str, str] = EN) -> list[str]:
    """The client's search (packages/client-core/src/help.ts): every word of the query in the article's words, in
    the locale's catalogue."""
    words = query.casefold().split()
    found = []
    for article in HelpCatalogue("1.0.0").articles():
        text = " ".join(catalogue[k] for k in (article["title_key"], article["body_key"], *article["step_keys"]))
        if all(word in text.casefold() for word in words):
            found.append(article["id"])
    return found


def payload():
    return {
        "device_id": "dev_synthetic",
        "licence_id": "lic_synthetic",
        "app_version": "1.0.0",
        "channel": "stable",
        "health": {"core": "ok", "worker": "unavailable"},
        "error_codes": ["disk_full"],
    }


def ops22_no_secret_fields():
    assert set(intake_fields()) == {"ticket_id", "licence_id", "device_id", "category", "bundle_id"}
    assert bundle_payload(payload()) == payload()
    for field in ("pin", "recovery_code", "student_name", "token", "messages", "conversation", "remote_access"):
        with pytest.raises(ValueError):
            bundle_payload({**payload(), field: "synthetic-secret"})
    with pytest.raises(ValueError):
        bundle_payload({**payload(), "health": {"core": "student name or secret"}})


def ops23_offline_help_complete():
    """Every listed topic has an article whose words are in the shipped catalogue (keys per LOC-01, D93), and
    searching "slow" with no network finds the slow-tutor article."""
    help = HelpCatalogue("1.0.0")
    assert help.errors(EN) == []
    assert len(help.articles()) >= Settings().ops_min_help_topics
    assert "slow" in search("slow")
    assert search("USB") and search("update failed") and search("licence")
    assert search("definitely no article") == []
    # The core's reply holds keys, never words; a catalogue missing one is incomplete.
    assert all(set(a) == {"id", "title_key", "body_key", "step_keys", "app_major_minor"} for a in help.articles())
    assert help.errors({k: v for k, v in EN.items() if k != "help.article.slow.step_2"})


def ops24_bundle_retention_and_access_log(tmp_path: Path):
    key = bytes(range(32))  # synthetic test key, never stored beside the bundles
    vault = BundleVault(tmp_path, key)
    bundle = vault.put("ticket_1", payload(), {"assigned"}, NOW, deliberately_shared=True)
    assert b"dev_synthetic" not in (tmp_path / f"{bundle}.enc").read_bytes()
    with pytest.raises(PermissionError):
        vault.open(bundle, "other", NOW)
    assert vault.open(bundle, "assigned", NOW) == payload()
    assert [e["allowed"] for e in vault.access_log(bundle)] == [False, True]
    assert vault.purge(NOW + timedelta(days=Settings().ops_bundle_retention_days)) == [bundle]
    with pytest.raises(FileNotFoundError):
        vault.open(bundle, "assigned", NOW)
    held = vault.put("ticket_2", payload(), {"assigned"}, NOW, deliberately_shared=True, incident_hold="inc_1")
    assert not vault.purge(NOW + timedelta(days=100))
    vault.close_ticket("ticket_2", NOW)
    assert vault.open(held, "assigned", NOW)
    vault.close_incident("inc_1", NOW)
    with pytest.raises(FileNotFoundError):
        vault.open(held, "assigned", NOW)
    with pytest.raises(ValueError):
        vault.put("ticket_3", payload(), {"assigned"}, NOW, deliberately_shared=False)
    removed = vault.put("ticket_4", payload(), {"assigned"}, NOW, deliberately_shared=True, incident_hold="inc_2")
    vault.erase(removed)
    assert not (tmp_path / f"{removed}.enc").exists()
    # Reopening cannot resurrect a deleted payload; the access audit remains.
    assert len(BundleVault(tmp_path, key).access_log(bundle)) == 3


def test_policy_ops25_docs_match_version(tmp_path: Path):
    help = HelpCatalogue("1.2.3")
    assert help.docs_errors({"app_major_minor": "1.1", "files": {}})
    files = {}
    for name in help.required_guides:
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(b"%PDF-1.7\nsynthetic guide")
        import hashlib

        files[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert not help.docs_errors({"app_major_minor": "1.2", "files": files})
    next(iter(files.values()))["sha256"] = "a" * 64
    assert help.docs_errors({"app_major_minor": "1.2", "files": files})


def test_policy_uxs46_sections_complete():
    sections = settings_sections("S2")
    assert {s["id"] for s in sections} == {
        "online_features",
        "profiles",
        "tutor_models",
        "content",
        "egress",
        "accessibility_language",
        "study",
        "tutor",
        "data_export",
        "licence",
        "help",
        "about",
    }
    assert len(settings_sections("S3")) == len(sections) + 3
    assert all(s["gate"] == "open" for s in settings_sections("S3"))


def test_policy_uxs46_no_answers_or_pin_sections():
    serialised = json.dumps(settings_sections("S3")).lower()
    assert all(removed not in serialised for removed in ("answers", "pin", "adult", "parent_lock"))


def test_policy_uxs46_sections_offline():
    assert all(s["offline"] and s["states"] for s in settings_sections("S3"))
    assert search("network")


def test_ops_support_rejection_does_not_echo_private_values():
    with pytest.raises(ValueError) as caught:
        bundle_payload({**payload(), "private_key": "synthetic-value-never-echo"})
    assert "synthetic-value-never-echo" not in str(caught.value)
