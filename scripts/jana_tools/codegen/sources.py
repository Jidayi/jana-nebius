"""Load the contracts and prepare the forms the generators need."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NAMESPACE = "https://jana.dev/contracts/"
# Prose stays in the private specification; generated code carries names, types and constraints only.
PROSE = frozenset({"description", "$comment", "examples"})
SOURCE_PREFIX = "docs/specification/contracts/"


@dataclass(frozen=True)
class Contract:
    rel: str  # path inside contracts/, for example "api/events.schema.json"
    id: str  # canonical $id
    sha256: str  # of the source file bytes
    schema: dict[str, Any]  # prose stripped, $id kept, refs canonical
    open_enums: frozenset[str] = frozenset()  # $defs marked `x-open-enum` (API-35), kept for the tolerant reader

    @property
    def stem(self) -> str:  # "api/events"
        return self.rel.removesuffix(".schema.json")

    @property
    def module(self) -> str:  # "api/events", hyphens made identifier-safe
        return self.stem.replace("-", "_")

    @property
    def source(self) -> str:
        return SOURCE_PREFIX + self.rel

    @property
    def has_root(self) -> bool:
        """False for definition catalogues (only $defs), which are validated per definition."""
        return any(k in self.schema for k in ("type", "oneOf", "anyOf", "allOf", "$ref", "properties"))

    @property
    def definitions(self) -> list[str]:
        return sorted(self.schema.get("$defs", {}))


# Keywords whose value maps names to subschemas, and keywords whose value is instance data.
NAMED_SUBSCHEMAS = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})
INSTANCE_DATA = frozenset({"const", "enum", "default"})


def strip_prose(node: Any) -> Any:
    """Drop annotation prose (and `x-` extensions) from schema positions only; property names and
    instance data (`const`, `enum`, `default`) are left untouched."""
    if isinstance(node, list):
        return [strip_prose(x) for x in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in PROSE or key.startswith("x-"):
            continue
        if key in NAMED_SUBSCHEMAS and isinstance(value, dict):
            out[key] = {name: strip_prose(sub) for name, sub in value.items()}
        elif key in INSTANCE_DATA:
            out[key] = value
        else:
            out[key] = strip_prose(value)
    return out


def load_contracts(contracts_dir: Path) -> list[Contract]:
    contracts = []
    for path in sorted(contracts_dir.rglob("*.schema.json")):
        raw = path.read_bytes()
        schema = json.loads(raw)
        contracts.append(
            Contract(
                rel=path.relative_to(contracts_dir).as_posix(),
                id=schema["$id"],
                sha256=hashlib.sha256(raw).hexdigest(),
                schema=strip_prose(schema),
                open_enums=frozenset(n for n, d in schema.get("$defs", {}).items() if d.get("x-open-enum") is True),
            )
        )
    return contracts


def _absolute(ref: str, base_id: str) -> str:
    """A $ref resolved against its schema's $id (refs are identifiers, never fetched)."""
    if ref.startswith("#"):
        return base_id + ref
    if ref.startswith(NAMESPACE):
        return ref
    return base_id.rsplit("/", 1)[0] + "/" + ref


def with_file_refs(contract: Contract, out_rel: str) -> dict[str, Any]:
    """The schema with every cross-contract $ref rewritten to a relative file path and $id removed,
    for generators that resolve references through the file system."""

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str) and not value.startswith("#"):
                    doc, _, fragment = _absolute(value, contract.id).partition("#")
                    target = doc.removeprefix(NAMESPACE) + ".schema.json"
                    rel = os.path.relpath(target, os.path.dirname(out_rel) or ".")
                    value = Path(rel).as_posix() + (f"#{fragment}" if fragment else "")
                out[key] = fix(value)
            return out
        if isinstance(node, list):
            return [fix(x) for x in node]
        return node

    schema = fix(contract.schema)
    schema.pop("$id", None)
    return schema


def _prefix(doc_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in doc_id.removeprefix(NAMESPACE))


def _pointer(node: Any, pointer: str) -> Any:
    for part in [p for p in pointer.split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def bundled(contract: Contract, all_contracts: list[Contract]) -> dict[str, Any]:
    """A self-contained copy of the contract: every definition it reaches in another contract is copied into
    its own `$defs` under a prefixed name (`<area>_<name>__<def>`, or `<area>_<name>` for a whole contract),
    and every `$ref` points inside the document. Cycles between contracts are followed once."""
    by_id = {c.id: c for c in all_contracts}
    defs: dict[str, Any] = {}
    pending: list[tuple[str, str, str]] = []  # (local name, doc id, pointer)
    named: dict[tuple[str, str], str] = {}

    def local(doc_id: str, pointer: str) -> str:
        if doc_id == contract.id:
            return "#" + pointer
        key = (doc_id, pointer)
        if key not in named:
            if not pointer:
                named[key] = _prefix(doc_id)
            elif pointer.startswith("/$defs/") and pointer.count("/") == 2:
                named[key] = f"{_prefix(doc_id)}__{pointer.rsplit('/', 1)[-1]}"
            else:
                named[key] = f"{_prefix(doc_id)}__{'_'.join(p for p in pointer.split('/') if p and p != '$defs')}"
            pending.append((named[key], doc_id, pointer))
        return f"#/$defs/{named[key]}"

    def rewrite(node: Any, base_id: str) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    doc, _, fragment = _absolute(value, base_id).partition("#")
                    value = local(doc, fragment)
                out[key] = value if key in INSTANCE_DATA else rewrite(value, base_id)
            return out
        if isinstance(node, list):
            return [rewrite(x, base_id) for x in node]
        return node

    root = rewrite(contract.schema, contract.id)
    root["title"] = root_name(contract)
    while pending:
        name, doc_id, pointer = pending.pop()
        target = _pointer(by_id[doc_id].schema, pointer)
        if not pointer:  # a whole contract: its root, without identity or its own definitions
            target = {k: v for k, v in target.items() if k not in ("$id", "$schema", "$defs")}
        defs[name] = rewrite(target, doc_id)
    if defs:
        root.setdefault("$defs", {}).update(defs)
    root.pop("$id", None)
    return named_schemas(root)


def camel(name: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", name) if w)


def root_name(contract: Contract) -> str:
    """Class name of a contract's root: its title, else its file name ("Event envelope" -> EventEnvelope)."""
    return camel(contract.schema.get("title") or contract.stem.rsplit("/", 1)[-1])


def named_schemas(root: dict[str, Any]) -> dict[str, Any]:
    """Title every definition and every inline object so generated class names are deterministic: a definition's
    class is its name in CamelCase (`#/$defs/ev_board_step` -> EvBoardStep), an inline object's class is its
    parent's name plus the property (`CardAnswer.answer` -> CardAnswerAnswer)."""

    def name_inline(node: Any, owner: str) -> None:
        if not isinstance(node, dict):
            return
        for prop, sub in (node.get("properties") or {}).items():
            if isinstance(sub, dict):
                title = owner + camel(prop)
                if _is_object(sub):
                    sub["title"] = title
                name_inline(sub, title)
        items = node.get("items")
        if isinstance(items, dict):
            if _is_object(items):
                items["title"] = owner + "Item"
            name_inline(items, owner + "Item")
        for key in ("oneOf", "anyOf", "allOf"):
            for i, branch in enumerate(node.get(key) or []):
                if isinstance(branch, dict) and _is_object(branch):
                    branch["title"] = f"{owner}{camel(key)}{i + 1}"
                    name_inline(branch, branch["title"])
                elif isinstance(branch, dict):
                    name_inline(branch, owner)
        for key in ("then", "else", "additionalProperties"):
            if isinstance(node.get(key), dict):
                name_inline(node[key], owner)

    for name, definition in (root.get("$defs") or {}).items():
        if isinstance(definition, dict):
            definition["title"] = camel(name)
            name_inline(definition, camel(name))
    name_inline(root, root["title"])
    return root


def _is_object(node: dict[str, Any]) -> bool:
    return "$ref" not in node and (node.get("type") == "object" or "properties" in node)


def referenced_ids(contract: Contract) -> set[str]:
    """Canonical $ids of the other contracts this one references."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                found.add(_absolute(ref, contract.id).partition("#")[0])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(contract.schema)
    found.discard(contract.id)
    return found


def closure(selected: list[Contract], all_contracts: list[Contract]) -> list[Contract]:
    """`selected` plus every contract they reference, transitively."""
    by_id = {c.id: c for c in all_contracts}
    out = {c.id: c for c in selected}
    stack = list(selected)
    while stack:
        for ref in referenced_ids(stack.pop()):
            if ref in by_id and ref not in out:
                out[ref] = by_id[ref]
                stack.append(by_id[ref])
    return sorted(out.values(), key=lambda c: c.rel)


def header(contract: Contract, comment: str) -> str:
    return (
        f"{comment} GENERATED by `python -m jana_tools codegen` from {contract.source}\n"
        f"{comment} source sha256: {contract.sha256}\n"
        f"{comment} Do not edit: change the schema in the specification and regenerate (ARC-30).\n"
    )
