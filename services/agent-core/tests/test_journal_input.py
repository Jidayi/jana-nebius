"""The browser journal fixture reaches the VER-22 schema/worker as exact decimal entries."""

from __future__ import annotations

import json
from pathlib import Path

from agent_core.contracts import errors
from agent_core.engine.ledger_input import entries
from test_m12d_accounting import call

GOLDEN = json.loads((Path(__file__).resolve().parents[3] / "packages/ui/gallery/journal-entry-golden.json").read_text())


def inp10_journal_serialise() -> None:
    block = GOLDEN["block"]
    assert errors("api/commands#/$defs/content_block", block) == []
    structured = entries([block])
    assert structured == GOLDEN["entries"]
    worker_entries = [
        {
            "ref": f"e{n}",
            "date": entry["date"],
            "lines": [{k: v for k, v in line.items() if k != "label"} for line in entry["lines"]],
        }
        for n, entry in enumerate(structured, 1)
    ]
    value = call("acc_double_entry", {"entries": worker_entries})["result"]["value"]
    assert value["all_balanced"] and value["trial_balance"]["agrees"]
    assert value["trial_balance"]["total_debit"] == "5000.00"
    assert value["trial_balance"]["total_credit"] == "5000.00"
    assert "marking" not in value  # balanced arithmetic does not assert account correctness without a key
    assert [row["account"] for row in value["ledger"]] == ["Equipment", "Cash", "Payables"]


def inp10_text_to_journal() -> None:
    case = json.loads(
        (Path(__file__).resolve().parents[3] / "packages/ui/gallery/journal-text-golden.json").read_text()
    )
    assert errors("api/commands#/$defs/content_block", case["block"]) == []
    grouped = entries([case["block"]])
    assert grouped == case["entries"]
    value = call(
        "acc_double_entry",
        {
            "entries": [
                {
                    "ref": "e1",
                    "lines": [{k: v for k, v in line.items() if k != "label"} for line in grouped[0]["lines"]],
                }
            ]
        },
    )["result"]["value"]
    assert value["all_balanced"] and value["trial_balance"]["total_debit"] == "5000.00"
    assert [row["account"] for row in value["ledger"]] == ["Equipment", "Cash", "Payables"]
