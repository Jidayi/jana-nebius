"""Parity between the hand-written TypeScript twins in the contract folders (api/events.ts, tools/tool-spec.ts)
and their canonical schemas (API-06, API-34, M1.a). The schema wins; any difference is a specification defect."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .codegen import CONTRACTS

_UNION = re.compile(r"^export type (\w+)\s*=\s*([^;]+);", re.MULTILINE)
_LITERAL = re.compile(r'^"([^"]*)"$')


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def ts_literal_unions(text: str) -> dict[str, set[str]]:
    """Named unions made only of string literals: `export type PartKind = "text" | "board";`."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    unions = {}
    for name, body in _UNION.findall(text):
        parts = [p.strip() for p in body.replace("\n", " ").split("|") if p.strip()]
        values = [_LITERAL.match(p) for p in parts]
        if parts and all(values):
            unions[name] = {m[1] for m in values if m}
    return unions


def ts_event_types(text: str) -> set[str]:
    """Event and control-frame types: a single-literal `type` member (`type: "board.step";`)."""
    return set(re.findall(r'\btype:\s*"([a-z_.]+)"\s*;', text))


def schema_enums(schema: dict[str, Any]) -> dict[str, set[str]]:
    """Enums of the schema's named definitions."""
    return {name: set(d["enum"]) for name, d in schema.get("$defs", {}).items() if isinstance(d, dict) and "enum" in d}


def schema_event_types(schema: dict[str, Any]) -> set[str]:
    """Every `type` constant of an object shape anywhere in the schema (events and control frames)."""
    types: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            const = (
                node.get("properties", {}).get("type", {}).get("const")
                if isinstance(node.get("properties"), dict) and isinstance(node["properties"].get("type"), dict)
                else None
            )
            if isinstance(const, str):
                types.add(const)
            for key, value in node.items():
                if key not in ("const", "enum", "default"):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return types


def parity_errors(ts_path: Path, schema_path: Path) -> list[str]:
    """Differences between a hand-written TypeScript twin and its schema: event types, and every literal union
    whose name matches a schema definition (PascalCase to snake_case, or exactly)."""
    text = ts_path.read_text()
    schema = json.loads(schema_path.read_text())
    errors = []
    events_ts, events_schema = ts_event_types(text), schema_event_types(schema)
    if events_schema:
        errors += [f"event type {t} is in {ts_path.name} but not the schema" for t in sorted(events_ts - events_schema)]
        errors += [f"event type {t} is in the schema but not {ts_path.name}" for t in sorted(events_schema - events_ts)]
    enums = schema_enums(schema)
    for name, values in sorted(ts_literal_unions(text).items()):
        key = name if name in enums else _snake(name)
        if key not in enums:
            continue
        for value in sorted(values - enums[key]):
            errors.append(f"{name}: value {value!r} is in {ts_path.name} but not the schema's {key}")
        for value in sorted(enums[key] - values):
            errors.append(f"{name}: value {value!r} is in the schema's {key} but not {ts_path.name}")
    return errors


TWINS = (
    (CONTRACTS / "api" / "events.ts", CONTRACTS / "api" / "events.schema.json"),
    (CONTRACTS / "tools" / "tool-spec.ts", CONTRACTS / "tools" / "tool-result.schema.json"),
)


def matched_unions(ts_path: Path, schema_path: Path) -> list[str]:
    """Names of the TypeScript unions that were compared against a schema enum (for the report)."""
    enums = schema_enums(json.loads(schema_path.read_text()))
    return sorted(n for n in ts_literal_unions(ts_path.read_text()) if n in enums or _snake(n) in enums)
