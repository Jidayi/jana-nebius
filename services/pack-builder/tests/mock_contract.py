"""The content-pack contract with the mock-paper record (ASM-15, CUR-31), for tests until the contract has it.

`ADDITIONS` is the contract addition proposed under D72, as a JSON Patch (RFC 6902) on
`contracts/content/content-pack.schema.json`: a `MockPaper` record, its id, the `mock_papers` table of the pack and
its name in the manifest's table list. `installed()` applies it to the bundled contract for the duration of a test,
so the pack builder's mock-paper support runs against the shape the contract will have. Once the contract has the
record and the bindings are regenerated, the bundled contract already validates mock papers and the patch is not
applied again.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from agent_core.contracts import _validation
from agent_core.store import packs
from pack_builder import source as tree

CONTRACT_ID = "https://jana.dev/contracts/content/content-pack"

MOCK_PAPER_ID = {
    "type": "string",
    "pattern": "^mck\\.(mth|phy|chm|bio|acc)\\.(o|a)\\.[0-9]{4}$",
    "$comment": "mck.<subj>.<lvl>.<nnnn>; within the paper_id pattern of the mock-exam contract.",
}

MOCK_PAPER = {
    "type": "object",
    "additionalProperties": False,
    "$comment": "ASM-15, CUR-31. A mock paper assembled from this pack's own items by a board-neutral blueprint. "
    "On the device it becomes the `paper` of a MockExam (contracts/learning/mock-exam.schema.json): paper_id is the "
    "id, the subject and level slugs map to that contract's names, and each question's criteria come from its item's "
    "mark points. The items a paper names form the mock-reserved pool and are never served in practice (ASM-22).",
    "required": ["id", "version", "subject", "level", "paper_kind", "title", "duration_minutes", "total_marks",
                 "calculator", "blueprint", "sections", "provenance", "review"],
    "properties": {
        "id": {"$ref": "#/$defs/MockPaperId"},
        "version": {"$ref": "#/$defs/SemVer"},
        "subject": {"$ref": "#/$defs/SubjectSlug"},
        "level": {"$ref": "#/$defs/LevelSlug"},
        "paper_kind": {"type": "string",
                       "enum": ["paper_1_objective", "paper_2_structured", "paper_3_structured", "section_mock"]},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "duration_minutes": {"type": "integer", "minimum": 10, "maximum": 240},
        "total_marks": {"type": "integer", "minimum": 1},
        "calculator": {"type": "boolean"},
        "blueprint": {
            "type": "object",
            "additionalProperties": False,
            "required": ["topic_weights"],
            "properties": {
                "topic_weights": {
                    "type": "object",
                    "minProperties": 1,
                    "propertyNames": {"$ref": "#/$defs/NodeId"},
                    "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
                    "$comment": "Share of the paper's marks per topic node; the weights sum to 1.",
                },
                "seed": {"type": "integer", "$comment": "The generator's seed when the paper was generated."},
            },
        },
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section_id", "title", "item_types", "marks", "questions"],
                "properties": {
                    "section_id": {"type": "string", "pattern": "^[A-Za-z0-9_]{1,16}$"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 80},
                    "item_types": {"type": "array", "minItems": 1, "uniqueItems": True,
                                   "items": {"$ref": "#/$defs/Item/properties/type"}},
                    "marks": {"type": "integer", "minimum": 1},
                    "choose": {"type": ["integer", "null"], "minimum": 1,
                               "description": "Answer any N questions in this section, if set."},
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["question_id", "item_id", "marks", "kc_ids"],
                            "properties": {
                                "question_id": {"type": "string", "pattern": "^[A-Za-z0-9_.]{1,16}$"},
                                "item_id": {"$ref": "#/$defs/ItemId"},
                                "marks": {"type": "integer", "minimum": 1},
                                "kc_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                           "items": {"$ref": "#/$defs/KcId"}},
                            },
                        },
                    },
                },
            },
        },
        "provenance": {"$ref": "#/$defs/Provenance"},
        "review": {"$ref": "#/$defs/Review"},
    },
}  # fmt: skip

ADDITIONS: list[dict[str, Any]] = [
    {"op": "add", "path": "/properties/mock_papers",
     "value": {"type": "array", "items": {"$ref": "#/$defs/MockPaper"}}},
    {"op": "add", "path": "/$defs/Manifest/properties/tables/items/properties/name/enum/-", "value": "mock_papers"},
    {"op": "add", "path": "/$defs/MockPaperId", "value": MOCK_PAPER_ID},
    {"op": "add", "path": "/$defs/MockPaper", "value": MOCK_PAPER},
]  # fmt: skip


def _pointer(path: str) -> list[str]:
    return [p.replace("~1", "/").replace("~0", "~") for p in path.lstrip("/").split("/")]


def apply(document: dict[str, Any], patch: list[dict[str, Any]]) -> dict[str, Any]:
    """The `add` operations of a JSON Patch, applied to a copy."""
    out = copy.deepcopy(document)
    for op in patch:
        assert op["op"] == "add", op
        *parents, last = _pointer(op["path"])
        node: Any = out
        for part in parents:
            node = node[int(part)] if isinstance(node, list) else node[part]
        if isinstance(node, list):
            node.append(copy.deepcopy(op["value"])) if last == "-" else node.insert(int(last), op["value"])
        else:
            assert last not in node, f"{op['path']} exists already"
            node[last] = copy.deepcopy(op["value"])
    return out


def patched(document: dict[str, Any]) -> dict[str, Any]:
    return apply(document, ADDITIONS)


def _clear_caches() -> None:
    _validation._registry.cache_clear()
    _validation.validator.cache_clear()
    tree._schema.cache_clear()


@contextmanager
def installed() -> Iterator[None]:
    """The bundled contract with the mock-paper addition, and the pack tables it brings, for the block's duration."""
    documents = dict(_validation._documents())
    if "MockPaper" not in documents[CONTRACT_ID]["$defs"]:
        documents[CONTRACT_ID] = patched(documents[CONTRACT_ID])
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(_validation, "_documents", lambda: documents)
            _clear_caches()
            patch.setattr(packs, "TABLES", packs.contract_tables())
            yield
    finally:
        _clear_caches()


def additions_json() -> str:
    """The addition as the file handed to the specification owner (JSON Patch on the content-pack contract)."""
    return json.dumps(ADDITIONS, indent=2, ensure_ascii=False) + "\n"
