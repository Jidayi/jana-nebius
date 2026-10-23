"""AUT-07: canonical schema reachability and source-file round trips, with synthetic authors only."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from agent_core.contracts import errors
from jsonschema import Draft202012Validator
from pack_builder import api, source
from pack_builder.accounts import Accounts
from pack_builder.form_schema import form_schema
from pack_builder.studio import TABLES, Workspace
from pack_builder.studio_io import Conflict

REPO = Path(__file__).resolve().parents[3]


def aut07_forms_cover_contract(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    shutil.copytree(REPO / "content/curriculum", root / "content/curriculum")
    # One real source per family/pack is sufficient for file IO; retain the full map/KC graph.
    for manifest in (root / "content/curriculum").glob("*/*/pack.yaml"):
        for directory in source.PER_RECORD.values():
            for extra in sorted((manifest.parent / directory).glob("*.yaml"))[1:]:
                extra.unlink()
    home = tmp_path / "authors"
    monkeypatch.setenv("JANA_AUTHORING_HOME", str(home))
    Accounts(home).create("lead", "Synthetic Lead", "lead@example.test", ["curriculum_lead"])
    monkeypatch.setenv("JANA_AUTHOR", "lead")
    w = Workspace(root)
    account = w.ctx().need()
    assert set(TABLES) | {"diagrams", "conventions", "kc_migrations"} == set(source.DEFINITION)
    schema = w.inventory()["schema"]
    observed = set()
    for pack in w.inventory()["packs"]:
        _, found = w.records(pack["id"])
        for table in TABLES:
            if not found[table] or table in observed:
                continue
            record = copy.deepcopy(found[table][0].record)
            # Compare the fully bundled form schema with the canonical contract for real authored fixtures.
            canonical = {k: v for k, v in record.items() if k not in source.SOURCE_ONLY}
            validator = Draft202012Validator({"$ref": f"#/$defs/{source.DEFINITION[table]}", "$defs": schema["$defs"]})
            assert not list(validator.iter_errors(canonical))
            assert not errors(f"content/content-pack#/$defs/{source.DEFINITION[table]}", canonical)
            assert list(validator.iter_errors({**canonical, "unexpected_field": "blocked"}))
            if "review" in record:
                record = api.edited_record(record, account)
            source.save_record(w.pack(pack["id"]), table, record)
            opened = w.open_record(pack["id"], table, record["id"])
            path = root / opened["path"]
            before = path.read_bytes()
            assert w.save({**opened, "id": record["id"]})["record"] == record
            assert path.read_bytes() == before
            edited = copy.deepcopy(record)
            if table == "charts_of_accounts":
                edited["accounts"][0]["account_name"] += " revised"
            else:
                key = next(
                    k for k in ("title", "stem", "statement", "stem_template", "description", "problem") if k in edited
                )
                if isinstance(edited[key], dict):
                    edited[key]["en"] += " revised"
                else:
                    edited[key] += " revised"
            saved = w.save({**opened, "id": record["id"], "record": edited})
            assert saved["record"] == edited
            restored = w.save({**saved, "id": record["id"], "record": record})
            assert restored["record"] == record and path.read_bytes() == before
            observed.add(table)
    # Template creation is covered even though committed content currently has no template source.
    template = {
        "id": "itpl.phy.o.motion.0001",
        "kc_ids": ["kc.phy.o.motion.average_speed"],
        "item_type": "numeric",
        "stem_template": "A runner travels {d} m in 80 s. Find speed.",
        "parameters": [{"name": "d", "kind": "integer", "min": 400, "max": 800, "step": 8}],
        "answer_tool": {"tool": "math_evaluate", "args": {"expression": "{d}/80"}},
        "version": "0.1.0",
        "provenance": {"origin": "original", "licence": "LicenseRef-Own", "drafted_with_ai": False, "sources": []},
        "review": {"status": "drafted", "reviewers": []},
    }
    opened = w.save(
        {
            "pack": "pack.phy.o",
            "table": "item_templates",
            "id": template["id"],
            "record": template,
            "revision": "missing",
        }
    )
    assert opened["record"]["stem_template"] == template["stem_template"]
    assert not w.candidate("pack.phy.o", "item_templates", opened["record"])["schema_problems"]
    observed.add("item_templates")
    assert observed == set(TABLES)
    ref = w.dispatch({"op": "reference_open", "pack": "pack.phy.o", "table": "conventions"})
    ref_path = root / ref["path"]
    before = ref_path.read_bytes()
    rows = copy.deepcopy(ref["rows"])
    assert rows
    rows[0]["value"] = str(rows[0]["value"]) + " revised"
    saved = w.dispatch(
        {
            "op": "reference_save",
            "pack": "pack.phy.o",
            "table": "conventions",
            "rows": rows,
            "revision": ref["revision"],
        }
    )
    assert saved["rows"] == rows
    with pytest.raises(Conflict):
        w.dispatch(
            {
                "op": "reference_save",
                "pack": "pack.phy.o",
                "table": "conventions",
                "rows": ref["rows"],
                "revision": ref["revision"],
            }
        )
    restored = w.dispatch(
        {
            "op": "reference_save",
            "pack": "pack.phy.o",
            "table": "conventions",
            "rows": ref["rows"],
            "revision": saved["revision"],
        }
    )
    assert restored["rows"] == ref["rows"]
    assert ref_path.read_text() == source.canonical(yaml.safe_load(before), "conventions")
    assert "Convention" in ref["schema"]["$defs"] and "KcMigration" in schema["$defs"]
    # Copies cannot mutate the cached contract, and all cross-document refs are now local.
    schema["$defs"].clear()
    assert form_schema("content/content-pack")["$defs"]
