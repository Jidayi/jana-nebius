"""API-34 conformance and the M1.a cross-language parity check over the contract fixture corpus."""

import importlib
import json
import subprocess
from functools import cache
from typing import Any, get_args

from agent_core import contracts as python_contracts
from jana_tools import REPO_ROOT
from jana_tools.codegen import CONTRACTS
from jana_tools.codegen.sources import camel, load_contracts, root_name
from jana_tools.fixtures import CORPUS, corpus_errors
from jana_tools.parity import TWINS, parity_errors, schema_event_types
from pydantic import TypeAdapter, ValidationError

INDEX: list[dict[str, str]] = json.loads((CORPUS / "index.json").read_text())


def _instance(entry: dict[str, str]) -> Any:
    return json.loads((CORPUS / entry["file"]).read_text())


@cache
def _contracts() -> dict[str, Any]:
    return {c.stem: c for c in load_contracts(CONTRACTS)}


def _model(name: str) -> Any:
    stem, _, definition = name.partition("#/$defs/")
    contract = _contracts()[stem]
    module = importlib.import_module("agent_core.contracts." + contract.module.replace("/", "."))
    return getattr(module, camel(definition) if definition else root_name(contract))


@cache
def _python_verdicts() -> dict[str, str]:
    return {e["file"]: "invalid" if python_contracts.errors(e["contract"], _instance(e)) else "valid" for e in INDEX}


@cache
def _typescript_verdicts() -> dict[str, str]:
    out = subprocess.run(
        ["node", "scripts/codegen/verdicts.mjs"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    verdicts: dict[str, str] = json.loads(out)
    return verdicts


def test_corpus_current_and_complete():
    assert corpus_errors() == []


def test_corpus_check_flags_a_fixture_left_for_a_removed_definition(tmp_path):
    """A fixture whose definition left the contract (D86 removed AdultToken) fails the check until deleted."""
    import shutil

    shutil.copytree(CORPUS, tmp_path / "corpus")
    leftover = tmp_path / "corpus" / "api" / "commands" / "AdultToken" / "valid" / "minimal.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text('{"adult_token": "x", "expires_in_s": 300}\n')
    assert corpus_errors(tmp_path / "corpus") == [
        "evals/contracts/api/commands/AdultToken/valid/minimal.json is not a fixture of the current contracts;"
        " delete it"
    ]


def test_fixtures_have_same_verdict_in_python_and_typescript():
    python, typescript = _python_verdicts(), _typescript_verdicts()
    assert set(python) == set(typescript) == {e["file"] for e in INDEX}
    assert [f for f in python if python[f] != typescript[f]] == []


def test_every_definition_has_a_model_that_accepts_its_valid_fixtures():
    for contract in _contracts().values():
        module = importlib.import_module("agent_core.contracts." + contract.module.replace("/", "."))
        names = ([root_name(contract)] if contract.has_root else []) + [camel(d) for d in contract.definitions]
        assert [n for n in names if not hasattr(module, n)] == [], contract.stem
    rejected = []
    for entry in (e for e in INDEX if e["expect"] == "valid" and e["origin"] != "contract example"):
        try:
            TypeAdapter(_model(entry["contract"])).validate_python(_instance(entry))
        except ValidationError as exc:
            rejected.append(f"{entry['file']}: {exc.errors()[0]['msg']}")
    assert rejected == []


def test_hand_written_twins_match_their_schemas():
    for ts, schema in TWINS:
        assert parity_errors(ts, schema) == [], ts.name


def _literals(annotation: Any) -> set[str]:
    """String literals reachable from a generated type (unions, aliases, Literal)."""
    found: set[str] = set()
    stack = [annotation]
    while stack:
        current = stack.pop()
        value = getattr(current, "__value__", None)  # a `type X = ...` alias
        if value is not None:
            stack.append(value)
            continue
        if isinstance(current, str):
            found.add(current)
        stack.extend(get_args(current))
    return found


def _models_in(annotation: Any) -> list[Any]:
    """Model classes reachable through aliases and unions."""
    found, stack = [], [annotation]
    while stack:
        current = stack.pop()
        if isinstance(current, type) and hasattr(current, "model_fields"):
            found.append(current)
            continue
        value = getattr(current, "__value__", None)
        stack.extend([value] if value is not None else get_args(current))
    return found


def api34_spec_conformance():
    problems: list[str] = []

    # Every fixture and every example in the contract folders validates as labelled, in both languages.
    python, typescript = _python_verdicts(), _typescript_verdicts()
    for entry in INDEX:
        for language, verdicts in (("Python", python), ("TypeScript", typescript)):
            if verdicts[entry["file"]] != entry["expect"]:
                detail = python_contracts.errors(entry["contract"], _instance(entry))[:1]
                problems.append(f"{language}: {entry['file']} ({entry['origin']}) is not {entry['expect']} {detail}")

    # The generated event union carries exactly the schema's event types, and each enum its values.
    events = importlib.import_module("agent_core.contracts.api.events")
    schema = json.loads((CONTRACTS / "api" / "events.schema.json").read_text())
    generated_types = {
        t for union in (events.TutorEvent, events.AppEvent) for member in _models_in(union)
        for t in _literals(member.model_fields["type"].annotation)
    }  # fmt: skip
    schema_types = {
        d["properties"]["type"]["const"]
        for d in schema["$defs"].values()
        if "const" in d.get("properties", {}).get("type", {})
    }
    problems += [f"event type {t} generated but not in the schema" for t in sorted(generated_types - schema_types)]
    problems += [f"event type {t} in the schema but not generated" for t in sorted(schema_types - generated_types)]
    for name, definition in schema["$defs"].items():
        if "enum" in definition:
            generated = _literals(getattr(events, camel(name)))
            if generated != set(definition["enum"]):
                problems.append(f"enum {name}: generated {sorted(generated)} != schema {sorted(definition['enum'])}")
    assert schema_event_types(schema) >= schema_types

    # The hand-written readable twins list the same event types and enum values as their schemas.
    for ts, schema_path in TWINS:
        problems += [f"{ts.name}: {e}" for e in parity_errors(ts, schema_path)]

    assert problems == []
