"""PRV-03: data minimisation. Every column of the storage contract has a data inventory entry naming its purpose,
retention row (TABLE DAT-08a) and egress rows (TABLE DAT-18a), and the inventory lists no column the contract lacks.
The onboarding half (prv03_onboarding_minimal_fields) drives the local API in services/agent-core/tests."""

from pathlib import Path

from agent_core.store.generated.schema import DATABASES
from jana_tools.data_inventory import INVENTORY, inventory_errors, load_inventory, schema_columns, spec_rows


def prv03_inventory_covers_schema(tmp_path: Path):
    rows = spec_rows()
    assert inventory_errors(DATABASES, rows=rows) == []
    entries = load_inventory()
    assert len(entries) == len(schema_columns(DATABASES)) > 300
    assert ("learner", "profile", "display_name") in entries and ("device", "outbox", "payload") in entries
    # The full-text index's own columns count; its internal shadow tables are not contract columns.
    assert ("learner", "notes_fts", "text") in entries
    assert not any(table.startswith("notes_fts_") for _, table, _ in entries)

    # The storage contract gains a column: CI fails and names it.
    grown = dict(DATABASES)
    grown["learner"] = grown["learner"].replace(
        "  display_name     TEXT    NOT NULL CHECK (length(display_name) BETWEEN 1 AND 40),\n",
        "  display_name     TEXT    NOT NULL CHECK (length(display_name) BETWEEN 1 AND 40),\n  surname TEXT,\n",
        1,
    )
    assert grown["learner"] != DATABASES["learner"]
    assert inventory_errors(grown, rows=rows) == [
        "learner.profile.surname: column has no data inventory entry (PRV-03)"
    ]

    # A new table is caught column by column, in the device database too.
    with_table = dict(DATABASES, device=DATABASES["device"] + "\nCREATE TABLE contacts (phone TEXT) STRICT;\n")
    assert inventory_errors(with_table, rows=rows) == [
        "device.contacts.phone: column has no data inventory entry (PRV-03)"
    ]

    # A column leaves the storage contract: its stale inventory entry fails.
    shrunk = dict(DATABASES)
    goals = "  goals            TEXT    CHECK (goals IS NULL OR json_valid(goals)),\n"
    shrunk["learner"] = shrunk["learner"].replace(goals, "", 1)
    assert shrunk["learner"] != DATABASES["learner"]
    assert inventory_errors(shrunk, rows=rows) == [
        "learner.profile.goals: inventory entry for a column the storage contract does not hold"
    ]

    # An entry without a purpose, or naming a retention or egress row the specification lacks, fails.
    text = INVENTORY.read_text()
    broken = tmp_path / "data-inventory.toml"
    avatar = next(line for line in text.splitlines() if line.startswith("avatar = "))
    broken.write_text(
        text.replace(
            avatar, avatar.split("purpose = ")[0] + 'purpose = " ", retention = "Forever", egress = ["Cloud"] }', 1
        )
    )
    assert inventory_errors(DATABASES, broken, rows) == [
        "learner.profile.avatar: empty purpose",
        "learner.profile.avatar: retention 'Forever' is not a row of TABLE DAT-08a",
        "learner.profile.avatar: egress 'Cloud' is not a row of TABLE DAT-18a",
    ]
