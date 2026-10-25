"""JRN-16: the studio journey's failure branches, driven through the studio's own commands (`handle`) on a throwaway
content repository with an invented author: F1 a key the tools cannot verify keeps an item in draft, F2 a forbidden
source licence blocks it with the offending record named, F3 a later change that fails a gate returns a published
record to draft with the failing check named."""

from __future__ import annotations

import copy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pack_builder import source
from pack_builder.accounts import Accounts
from pack_builder.studio import Workspace, handle

REPO = Path(__file__).resolve().parents[3]
PACK = "pack.phy.o"
ITEM = "itm.phy.o.motion.0001"
KEY_CHECK = "chk_build_phy_k_0001_a"


@pytest.fixture
def studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    root = tmp_path / "repo"
    pack = root / "content/curriculum/phy/o"
    original = REPO / "content/curriculum/phy/o"
    pack.mkdir(parents=True)
    for name in ("pack.yaml", "map.yaml"):
        shutil.copy(original / name, pack / name)
    shutil.copytree(original / "kcs", pack / "kcs")
    shutil.copytree(source.ref_dir(original), source.ref_dir(pack))
    for table, identity in (("items", ITEM), ("worked_examples", "wex.phy.o.motion.0001")):
        directory = source.PER_RECORD[table]
        (pack / directory).mkdir()
        shutil.copy(original / directory / f"{identity}.yaml", pack / directory)
    (pack / "misconceptions").mkdir()
    shutil.copy(original / "misconceptions/mc.phy.o.time_over_distance.yaml", pack / "misconceptions")
    home = tmp_path / "authors"
    monkeypatch.setenv("JANA_AUTHORING_HOME", str(home))
    Accounts(home).create("lead", "Synthetic Lead", "lead@example.test", ["curriculum_lead"])
    monkeypatch.setenv("JANA_AUTHOR", "lead")
    return Workspace(root)


def _record(w: Workspace, identity: str = ITEM) -> dict[str, Any]:
    return dict(w.open_record(PACK, "items", identity))


def _edit(w: Workspace, identity: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    opened = _record(w, identity)
    record = copy.deepcopy(opened["record"])
    change(record)
    reply = handle(w, {"op": "save", **opened, "record": record, "id": identity})
    assert "error" not in reply, reply
    return reply


def _promote(w: Workspace, identity: str) -> dict[str, Any]:
    reply = handle(w, {"op": "promote", "pack": PACK, "id": identity})
    assert "error" not in reply, reply
    return dict(reply["result"])


def _status(w: Workspace, identity: str) -> str:
    return str(_record(w, identity)["record"]["review"]["status"])


def _wrong_key(record: dict[str, Any]) -> None:
    record["parts"][0]["answer"]["value"] = "9.0"  # the tools compute 8.0


def _new_draft(w: Workspace) -> dict[str, Any]:
    new = handle(w, {"op": "duplicate", "pack": PACK, "table": "items", "id": ITEM, "title": "Copy"})["result"]
    assert new["record"]["review"]["status"] == "drafted"
    return dict(new)


def _save_new(w: Workspace, new: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> str:
    record = copy.deepcopy(new["record"])
    change(record)
    reply = handle(w, {"op": "save", **new, "record": record, "id": record["id"]})
    assert "error" not in reply, reply
    return str(record["id"])


def _forbidden_source(record: dict[str, Any]) -> None:
    record["provenance"] = {**record["provenance"], "origin": "adapted", "sources": [{
        "title": "Synthetic worksheet", "url": "https://example.org/worksheet", "licence": "CC-BY-NC-4.0",
        "attribution": "Synthetic Test Source", "modifications": "Reworded", "retrieved": "2026-10-01"}]}  # fmt: skip


def jrn16_failure_branches(studio: Workspace) -> None:
    # F3: the copied item is published; a change that breaks its key returns it to draft, and the gate names the check.
    assert _status(studio, ITEM) == "published"
    _edit(studio, ITEM, _wrong_key)
    assert _status(studio, ITEM) == "drafted"
    assert _record(studio)["record"]["authoring"]["history"][-1] == "drafted"
    held = _promote(studio, ITEM)
    assert held["ok"] is False and [h["record"] for h in held["held"]] == [ITEM]
    assert any(KEY_CHECK in p for p in held["held"][0]["problems"])

    # F1: a new draft whose key the tools cannot verify cannot leave draft.
    draft = _save_new(studio, _new_draft(studio), _wrong_key)
    held = _promote(studio, draft)
    assert held["ok"] is False and held["verified"] == [] and [h["record"] for h in held["held"]] == [draft]
    assert any("does not match math_evaluate result 8.0" in p for p in held["held"][0]["problems"])
    assert _status(studio, draft) == "drafted"

    # F2: a draft drawing on a source under a forbidden (non-commercial) licence is blocked, the record named.
    licensed = _save_new(studio, _new_draft(studio), _forbidden_source)
    held = _promote(studio, licensed)
    assert held["ok"] is False and [h["record"] for h in held["held"]] == [licensed]
    assert any(licensed in p and "CC-BY-NC-4.0" in p for p in held["held"][0]["problems"]), held["held"][0]["problems"]
    assert _status(studio, licensed) == "drafted"
