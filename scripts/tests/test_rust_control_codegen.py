"""D39 and ARC-30: the shell's control-channel types are generated from the control contract, and the generator
refuses any schema feature it does not translate rather than emitting a looser type."""

import copy
import re
from typing import Any

import pytest
from jana_tools import REPO_ROOT
from jana_tools.codegen import CONTRACTS, SHELL_KEYS
from jana_tools.codegen.rust_control import CONTROL_ID, Unsupported, render
from jana_tools.codegen.sources import Contract, load_contracts


def _contracts() -> list[Contract]:
    return load_contracts(CONTRACTS)


def _with_control(change: Any) -> list[Contract]:
    """The contracts with the control contract's schema changed by `change(schema)`."""
    contracts = _contracts()
    out = []
    for contract in contracts:
        if contract.id == CONTROL_ID:
            schema = copy.deepcopy(contract.schema)
            change(schema)
            contract = Contract(contract.rel, contract.id, contract.sha256, schema, contract.open_enums)
        out.append(contract)
    return out


def test_generated_control_types_are_committed_and_cover_every_frame():
    text = render(_contracts())
    assert (REPO_ROOT / SHELL_KEYS / "control.rs").read_text() == text
    mod = (REPO_ROOT / SHELL_KEYS / "mod.rs").read_text()
    assert "pub mod control;" in mod and "pub mod keys;" in mod
    control = next(c for c in _contracts() if c.id == CONTROL_ID)
    assert f"source sha256: {control.sha256}" in text
    defs = control.schema["$defs"]
    for union in ("ToCore", "ToShell"):
        enum = re.search(rf"pub enum {union} \{{(.*?)\n\}}", text, re.S)
        assert enum is not None
        for branch in defs[union]["oneOf"]:
            name = branch["$ref"].rsplit("/", 1)[-1]
            tag = defs[name]["properties"]["type"]["const"]
            assert f'#[serde(rename = "{tag}")]\n    {name}({name}),' in enum.group(1)
    # Every object refuses unknown fields; secrets are never printed.
    assert text.count("pub struct ") - 2 == text.count("#[serde(deny_unknown_fields)]")
    for secret in (
        "pub value: Redacted,",
        "pub key: Redacted,",
        "pub token: Redacted,",
        "pub adapter_token: Redacted,",
    ):
        assert secret in text
    assert "pub type KeyValue = Redacted;" in text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda s: s["$defs"]["NetState"]["properties"].update(latency={"type": "number"}), "type 'number'"),
        (lambda s: s["$defs"]["NetState"].update(additionalProperties=True), "admits unknown properties"),
        (lambda s: s["$defs"]["NetState"]["properties"].update(token={"type": "string"}), "named like a secret"),
        (
            lambda s: s["$defs"]["NetState"]["properties"].update(
                link={"$ref": "https://jana.dev/contracts/nowhere#/$defs/Thing"}
            ),
            "not supported",
        ),
        (lambda s: s["$defs"]["NetState"]["properties"].update(mode={"oneOf": [{"type": "string"}]}), "unsupported"),
        (lambda s: s["$defs"]["NetState"]["properties"].update(n={"anyOf": [{"type": "string"}]}), "anyOf other"),
    ],
)
def test_unsupported_schema_features_fail_loudly(change: Any, message: str):
    with pytest.raises(Unsupported, match=re.escape(message)):
        render(_with_control(change))
