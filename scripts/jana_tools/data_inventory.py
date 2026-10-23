"""PRV-03: the data inventory names a purpose, a retention row (TABLE DAT-08a) and the egress rows (TABLE DAT-18a)
for every column of the storage contract, and lists nothing the storage contract does not hold.

The inventory is scripts/governance/data-inventory.toml: one TOML table per `<database>.<table>`, one key per column,
each an inline table `{ purpose = "...", retention = "<DAT-08a row>", egress = "none" | ["<DAT-18a row>", ...] }`.
A row is named by its first cell with backticks and parenthesised asides removed."""

from __future__ import annotations

import re
import sqlite3
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .spec import DOCS, table_rows

INVENTORY = Path(__file__).resolve().parents[1] / "governance" / "data-inventory.toml"
DATA_MODEL = Path("specification") / "data-model.md"
RETENTION_TABLE = "TABLE DAT-08a"
EGRESS_TABLE = "TABLE DAT-18a"
NO_EGRESS = "none"
FIELDS = {"purpose", "retention", "egress"}

Column = tuple[str, str, str]  # (database kind, table, column)


def schema_columns(databases: Mapping[str, str]) -> list[Column]:
    """Every column of every table the storage contract creates, read by applying each database's SQL to an empty
    in-memory database. Internal tables (sqlite_*) and the shadow tables of full-text indexes are not part of the
    contract's columns; the full-text table itself is."""
    found: list[Column] = []
    for kind, sql in databases.items():
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(sql)
            types = dict(conn.execute("SELECT name, type FROM pragma_table_list WHERE schema = 'main'").fetchall())
            created = [name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            tables = [t for t in created if types.get(t) in ("table", "virtual") and not t.startswith("sqlite_")]
            for table in tables:  # in contract order
                # hidden = 1 marks a virtual table's hidden columns (an FTS5 table's own name and `rank`).
                for _, column, *_, hidden in conn.execute("SELECT * FROM pragma_table_xinfo(?)", (table,)):
                    if hidden != 1:
                        found.append((kind, table, column))
        finally:
            conn.close()
    return found


def row_name(cell: str) -> str:
    """The name of a specification table row: its first cell without backticks or parenthesised asides."""
    return " ".join(re.sub(r"\s*\([^()]*\)", "", cell.replace("`", "")).split())


def spec_rows(docs: Path = DOCS) -> tuple[set[str], set[str]]:
    """The row names of TABLE DAT-08a (retention) and TABLE DAT-18a (egress data classes)."""
    text = (docs / DATA_MODEL).read_text()
    return ({row_name(r[0]) for r in table_rows(text, RETENTION_TABLE)},
            {row_name(r[0]) for r in table_rows(text, EGRESS_TABLE)})  # fmt: skip


def load_inventory(path: Path = INVENTORY) -> dict[Column, dict[str, Any]]:
    data = tomllib.loads(path.read_text())
    entries: dict[Column, dict[str, Any]] = {}
    for kind, tables in data.items():
        for table, columns in tables.items():
            for column, entry in columns.items():
                entries[(kind, table, column)] = entry if isinstance(entry, dict) else {}
    return entries


def inventory_errors(
    databases: Mapping[str, str], path: Path = INVENTORY, rows: tuple[set[str], set[str]] | None = None
) -> list[str]:
    """Differences between the inventory and the storage contract, both ways, and incomplete entries. `rows` are
    the known (retention, egress) row names; by default they are read from the specification checkout."""
    retention_rows, egress_rows = rows if rows is not None else spec_rows()
    inventory = load_inventory(path)
    columns = schema_columns(databases)
    known = set(columns)
    errors = [f"{'.'.join(c)}: column has no data inventory entry (PRV-03)" for c in columns if c not in inventory]
    errors += [f"{'.'.join(c)}: inventory entry for a column the storage contract does not hold" for c in inventory
               if c not in known]  # fmt: skip
    for column in columns:
        entry = inventory.get(column)
        if entry is None:
            continue
        name = ".".join(column)
        errors += [f"{name}: unknown inventory field {key!r}" for key in sorted(set(entry) - FIELDS)]
        purpose = entry.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            errors.append(f"{name}: empty purpose")
        retention = entry.get("retention")
        if retention not in retention_rows:
            errors.append(f"{name}: retention {retention!r} is not a row of {RETENTION_TABLE}")
        egress = entry.get("egress")
        if egress == NO_EGRESS:
            continue
        if not isinstance(egress, list) or not egress or not all(isinstance(e, str) for e in egress):
            errors.append(f"{name}: egress must be {NO_EGRESS!r} or a non-empty list of {EGRESS_TABLE} rows")
            continue
        errors += [f"{name}: egress {e!r} is not a row of {EGRESS_TABLE}" for e in egress if e not in egress_rows]
    return errors
