"""Lint of the generated storage schema against the DAT-03 conventions.

Every table is STRICT with declared column types and snake_case names; every JSON column is TEXT guarded by
`json_valid` (a free TEXT column named like a JSON column elsewhere is JSON too, and a JSON-looking default needs the
guard); timestamp columns (`*_at`) and checked booleans are INTEGER; and the store opens with the contract's pragmas.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping

TYPES = {"INTEGER", "TEXT", "BLOB", "REAL"}
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
PRAGMAS = {"journal_mode": "wal", "synchronous": 2, "foreign_keys": 1, "secure_delete": 1, "recursive_triggers": 1}
CONSTRAINTS = ("PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY", "CONSTRAINT")


def split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on the commas that are not inside parentheses or string literals."""
    out: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for i, ch in enumerate(body):
        if ch == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(body[start:i].strip())
            start = i + 1
    out.append(body[start:].strip())
    return [part for part in out if part]


def columns(create: str) -> dict[str, str]:
    """Column name → its full definition text, from one CREATE TABLE statement."""
    body = create[create.index("(") + 1 : create.rindex(")")]
    defs: dict[str, str] = {}
    for part in split_top_level(body):
        if part.upper().startswith(CONSTRAINTS):
            continue
        defs[part.split()[0]] = part
    return defs


def tables(sql: str) -> dict[str, tuple[bool, str]]:
    """Apply `sql` to an empty database; table name → (STRICT, CREATE statement)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(sql)
        # Ordinary tables only: a full-text index is a virtual table whose shadow tables SQLite owns.
        strict = {row[1]: bool(row[5]) for row in conn.execute("PRAGMA table_list") if row[2] == "table"}
        return {
            name: (strict[name], create)
            for name, create in conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'table'")
            if name in strict and not name.startswith("sqlite_")
        }
    finally:
        conn.close()


def is_json(definition: str, name: str) -> bool:
    return f"json_valid({name})" in definition.replace(" ", "")


def schema_errors(databases: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    found: dict[str, dict[str, dict[str, str]]] = {}
    for kind, sql in databases.items():
        for table, (strict, create) in tables(sql).items():
            where = f"{kind}.{table}"
            if not strict:
                errors.append(f"{where}: not STRICT")
            if not NAME.match(table):
                errors.append(f"{where}: table name is not snake_case")
            found.setdefault(kind, {})[table] = columns(create)
    json_names = {
        name for defs in found.values() for cols in defs.values() for name, d in cols.items() if is_json(d, name)
    }
    for kind, defs in found.items():
        for table, cols in defs.items():
            for name, definition in cols.items():
                where = f"{kind}.{table}.{name}"
                parts = definition.split()
                declared = parts[1].upper() if len(parts) > 1 else ""
                if declared not in TYPES:
                    errors.append(f"{where}: column type {declared or 'missing'} (STRICT types only, never ANY)")
                if not NAME.match(name):
                    errors.append(f"{where}: column name is not snake_case")
                json_default = re.search(r"DEFAULT\s+'[\[{]", definition, re.IGNORECASE)
                enum = re.search(rf"\b{name}\s+IN\s*\(", definition) is not None
                plain_text = declared == "TEXT" and not enum
                if ((name in json_names and plain_text) or json_default) and not is_json(definition, name):
                    errors.append(f"{where}: JSON column without CHECK (json_valid({name}))")
                if is_json(definition, name) and declared != "TEXT":
                    errors.append(f"{where}: JSON column must be TEXT")
                if name.endswith("_at") and declared != "INTEGER":
                    errors.append(f"{where}: timestamp must be INTEGER UTC milliseconds")
                if re.search(rf"\b{name}\s+IN\s*\(\s*0\s*,\s*1\s*\)", definition) and declared != "INTEGER":
                    errors.append(f"{where}: boolean must be INTEGER")
    return errors


def pragma_errors(conn: sqlite3.Connection, expected: Iterable[tuple[str, object]] = PRAGMAS.items()) -> list[str]:
    errors = []
    for name, value in expected:
        actual = conn.execute(f"PRAGMA {name}").fetchone()[0]
        if (actual.lower() if isinstance(actual, str) else actual) != value:
            errors.append(f"pragma {name} is {actual!r}, expected {value!r}")
    return errors


def lint(databases: Mapping[str, str], conn: sqlite3.Connection) -> list[str]:
    return schema_errors(databases) + pragma_errors(conn)
