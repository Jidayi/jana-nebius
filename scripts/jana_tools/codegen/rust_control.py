"""The shell's control-channel types, generated from the control contract (ARC-04, ARC-30, D39).

Writes `control.rs` into the shell's generated folder: one serde struct per object definition (the frame's `type`
is the enum tag, not a field), a Rust enum per string enum, and the `ToCore` and `ToShell` enums, internally tagged
by `type`. Secret-bearing strings are `Redacted`, whose `Debug` never prints the value (SEC-17).

The generator covers exactly the schema features the control contract uses. Any other keyword, an object that
admits unknown properties, or a cross-contract reference it does not know fails loudly, so a contract change can
never silently generate a looser type. Value constraints (patterns, lengths, ranges, conditionals) stay with the
contract's validators on the core's side; serde checks shape: names, types, required and unknown fields.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sources import NAMESPACE, Contract, camel

CONTROL_ID = NAMESPACE + "control/control"
VERSIONS = Path(__file__).parent / "versions.toml"
SOURCE = "docs/specification/contracts/control/control.schema.json"

# Value constraints serde does not check; the core validates every frame against the contract (ARC-04).
CONSTRAINTS = frozenset(
    {"pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "maxProperties", "default"}
)
CONDITIONALS = frozenset({"if", "then", "else", "allOf"})
OBJECT_KEYS = frozenset({"type", "additionalProperties", "required", "properties", "title"}) | CONDITIONALS
# Cross-contract targets carried as plain JSON: the shell builds and forwards them without reading their fields.
OPAQUE_REFS = frozenset({NAMESPACE + "api/events#/$defs/ev_egress_notice"})
# Secret-bearing strings (SEC-10, SEC-17, VOC-23): `Redacted`, never printed. Definitions by name, fields by owner.
SECRET_DEFS = frozenset({"KeyValue"})
SECRET_FIELDS = frozenset({"Secret.value", "RuntimeEndpoint.key", "VoiceStart.adapter_token", "VoiceEndpoint.token"})
# A string field whose name suggests a secret must be listed as one (or here, as checked not to be one).
SECRET_NAME = re.compile(r"token|key|secret|password|value")
NOT_SECRET: frozenset[str] = frozenset()
RUST_KEYWORDS = frozenset({"type", "ref", "move", "match", "fn", "impl", "loop", "self", "static", "use", "where"})
FRAMES = ("ToCore", "ToShell")


class Unsupported(ValueError):
    """The control contract uses a schema feature this generator does not translate."""


@dataclass
class Out:
    items: list[str] = field(default_factory=list)
    done: set[str] = field(default_factory=set)


def _fail(where: str, why: str) -> Unsupported:
    return Unsupported(f"rust control codegen: {where}: {why}")


def _ident(name: str) -> str:
    return f"r#{name}" if name in RUST_KEYWORDS else name


def _variant(value: str, where: str) -> str:
    name = camel(value)
    if not name or not name[0].isalpha():
        raise _fail(where, f"enum value {value!r} has no Rust variant name")
    return name


class Generator:
    def __init__(self, control: Contract, contracts: list[Contract]) -> None:
        self.by_id = {c.id: c for c in contracts}
        self.control = control
        self.defs: dict[str, Any] = control.schema.get("$defs", {})
        self.out = Out()

    # -- types -------------------------------------------------------------------------------------------------

    def ref_type(self, ref: str, where: str) -> str:
        if ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            if name not in self.defs:
                raise _fail(where, f"unknown definition {ref}")
            self.definition(name, self.defs[name])
            return camel(name)
        if ref in OPAQUE_REFS:
            return "serde_json::Value"
        doc, _, pointer = ref.partition("#")
        if doc not in self.by_id or not pointer.startswith("/$defs/") or pointer.count("/") != 2:
            raise _fail(where, f"cross-contract reference {ref} is not supported")
        name = pointer.rsplit("/", 1)[-1]
        target = self.by_id[doc].schema.get("$defs", {}).get(name)
        if target is None:
            raise _fail(where, f"unknown definition {ref}")
        if name in self.defs:
            raise _fail(where, f"{ref} clashes with the control contract's own {name}")
        self.definition(name, target)
        return camel(name)

    def type_of(self, schema: dict[str, Any], owner: str, prop: str, where: str) -> tuple[str, bool]:
        """The Rust type of a property schema, and whether null is allowed."""
        if "$ref" in schema:
            extra = set(schema) - {"$ref"}
            if extra:
                raise _fail(where, f"keywords beside $ref: {sorted(extra)}")
            return self.ref_type(schema["$ref"], where), False
        if "anyOf" in schema:
            branches = schema["anyOf"]
            if set(schema) != {"anyOf"} or len(branches) != 2 or {"type": "null"} not in branches:
                raise _fail(where, "anyOf other than [T, null]")
            (inner,) = [b for b in branches if b != {"type": "null"}]
            rust, _ = self.type_of(inner, owner, prop, where)
            return rust, True
        kind = schema.get("type")
        if isinstance(kind, list):
            if len(kind) != 2 or "null" not in kind:
                raise _fail(where, f"type list {kind}")
            (single,) = [k for k in kind if k != "null"]
            rust, _ = self.type_of({**schema, "type": single}, owner, prop, where)
            return rust, True
        if "enum" in schema:
            return self.string_enum(owner + camel(prop), schema, where), False
        if "const" in schema:
            raise _fail(where, "const outside a frame's type")
        self.check_keys(schema, {"type"} | CONSTRAINTS, where)
        if kind == "string":
            return "String", False
        if kind == "boolean":
            return "bool", False
        if kind == "integer":
            low, high = schema.get("minimum"), schema.get("maximum")
            if low is not None and low >= 0:
                return ("u16" if high is not None and high <= 0xFFFF else "u64"), False
            return "i64", False
        if kind == "array":
            raise _fail(where, "array handled by the object path")
        raise _fail(where, f"type {kind!r}")

    def field_type(self, schema: dict[str, Any], owner: str, prop: str, where: str) -> tuple[str, bool]:
        if schema.get("type") == "array":
            self.check_keys(schema, {"type", "items"} | CONSTRAINTS, where)
            items = schema.get("items")
            if not isinstance(items, dict):
                raise _fail(where, "array without one items schema")
            name = owner + camel(prop) + "Item"
            inner = self.object(name, items, where) if _is_object(items) else self.field_type(items, name, "", where)[0]
            return f"Vec<{inner}>", False
        if _is_object(schema):
            if "properties" not in schema and isinstance(schema.get("additionalProperties"), dict):
                self.check_keys(schema, {"type", "additionalProperties"} | CONSTRAINTS, where)
                value, nullable = self.type_of(schema["additionalProperties"], owner + camel(prop), "value", where)
                if nullable:
                    raise _fail(where, "nullable map values")
                return f"BTreeMap<String, {value}>", False
            return self.object(owner + camel(prop), schema, where), False
        return self.type_of(schema, owner, prop, where)

    def check_keys(self, schema: dict[str, Any], allowed: frozenset[str] | set[str], where: str) -> None:
        extra = set(schema) - set(allowed) - {"title"}
        if extra:
            raise _fail(where, f"unsupported keywords {sorted(extra)}")

    # -- items -------------------------------------------------------------------------------------------------

    def definition(self, name: str, schema: dict[str, Any]) -> None:
        rust = camel(name)
        if rust in self.out.done:
            return
        where = f"$defs/{name}"
        if name in FRAMES:
            return
        if _is_object(schema):
            self.object(rust, schema, where)
        elif "enum" in schema:
            self.string_enum(rust, schema, where)
        elif schema.get("type") == "string":
            self.check_keys(schema, {"type"} | CONSTRAINTS, where)
            self.out.done.add(rust)
            target = "Redacted" if name in SECRET_DEFS else "String"
            self.out.items.append(f"/// `{where}`\npub type {rust} = {target};\n")
        else:
            raise _fail(where, "a definition that is neither an object, a string enum nor a string")

    def string_enum(self, rust: str, schema: dict[str, Any], where: str) -> str:
        self.check_keys(schema, {"enum", "type"}, where)
        values = schema["enum"]
        if not all(isinstance(v, str) for v in values) or schema.get("type", "string") != "string":
            raise _fail(where, "enum of non-strings")
        if rust in self.out.done:
            return rust
        self.out.done.add(rust)
        variants = [(_variant(v, where), v) for v in values]
        body = "".join(f'    #[serde(rename = "{v}")]\n    {n},\n' for n, v in variants)
        arms = "".join(f'            {rust}::{n} => "{v}",\n' for n, v in variants)
        parse = "".join(f'            "{v}" => Ok({rust}::{n}),\n' for n, v in variants)
        self.out.items.append(
            f"/// `{where}`\n"
            "#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]\n"
            f"pub enum {rust} {{\n{body}}}\n\n"
            f"impl {rust} {{\n"
            "    /// The value on the wire.\n"
            "    pub fn as_str(self) -> &'static str {\n"
            f"        match self {{\n{arms}        }}\n    }}\n}}\n\n"
            f"impl std::str::FromStr for {rust} {{\n"
            "    type Err = UnknownValue;\n\n"
            "    fn from_str(value: &str) -> Result<Self, UnknownValue> {\n"
            f"        match value {{\n{parse}            _ => Err(UnknownValue),\n        }}\n    }}\n}}\n"
        )
        return rust

    def object(self, rust: str, schema: dict[str, Any], where: str, frame: str | None = None) -> str:
        if rust in self.out.done:
            return rust
        self.out.done.add(rust)
        self.check_keys(schema, OBJECT_KEYS, where)
        if schema.get("additionalProperties") is not False:
            raise _fail(where, "an object that admits unknown properties")
        props: dict[str, Any] = schema.get("properties", {})
        required = set(schema.get("required", []))
        if required - set(props):
            raise _fail(where, f"required names without a property: {sorted(required - set(props))}")
        fields = []
        for prop, sub in props.items():
            at = f"{where}/properties/{prop}"
            if prop == "type" and frame is not None:
                if sub != {"const": frame}:
                    raise _fail(at, "a frame's type must be its const")
                continue
            if prop == "type":
                raise _fail(at, "a `type` property outside a frame")
            rust_type, nullable = self.field_type(sub, rust, prop, at)
            secret = f"{rust}.{prop}" in SECRET_FIELDS
            if secret:
                if rust_type != "String":
                    raise _fail(at, "a secret field that is not a string")
                rust_type = "Redacted"
            elif rust_type == "String" and SECRET_NAME.search(prop) and f"{rust}.{prop}" not in NOT_SECRET:
                raise _fail(at, "a string named like a secret: list it in SECRET_FIELDS or NOT_SECRET")
            attrs = []
            if prop in required and nullable:
                rust_type = f"Option<{rust_type}>"
                attrs.append('#[serde(deserialize_with = "present")]')
            elif prop in required:
                pass
            elif nullable:
                rust_type = f"Option<{rust_type}>"
                attrs.append("#[serde(default)]")
            else:
                rust_type = f"Option<{rust_type}>"
                attrs.append('#[serde(default, skip_serializing_if = "Option::is_none")]')
            fields.append("".join(f"    {a}\n" for a in attrs) + f"    pub {_ident(prop)}: {rust_type},\n")
        if frame is not None and props.get("type") != {"const": frame}:
            raise _fail(where, "a frame without its type const")
        body = f"{{\n{''.join(fields)}}}" if fields else "{}"
        self.out.items.append(
            f"/// `{where}`\n"
            "#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]\n"
            "#[serde(deny_unknown_fields)]\n"
            f"pub struct {rust} {body}\n"
        )
        return rust

    def frames(self, name: str) -> tuple[str, list[str]]:
        where = f"$defs/{name}"
        schema = self.defs.get(name)
        if not schema or set(schema) - {"oneOf", "title"}:
            raise _fail(where, "frame unions must be a oneOf of references")
        variants, tags = [], []
        for branch in schema["oneOf"]:
            ref = branch.get("$ref", "")
            if set(branch) != {"$ref"} or not ref.startswith("#/$defs/"):
                raise _fail(where, "frame unions must be a oneOf of local references")
            frame_name = ref.removeprefix("#/$defs/")
            frame = self.defs[frame_name]
            tag = frame.get("properties", {}).get("type", {}).get("const")
            if not isinstance(tag, str):
                raise _fail(f"$defs/{frame_name}", "a frame without a type const")
            rust = self.object(camel(frame_name), frame, f"$defs/{frame_name}", frame=tag)
            variants.append(f'    #[serde(rename = "{tag}")]\n    {rust}({rust}),\n')
            tags.append((rust, tag))
        arms = "".join(f'            {name}::{rust}(_) => "{tag}",\n' for rust, tag in tags)
        names = "".join(f'    "{tag}",\n' for _, tag in tags)
        const = "TO_CORE_TYPES" if name == "ToCore" else "TO_SHELL_TYPES"
        text = (
            f"/// `{where}`: every frame, tagged by `type`.\n"
            "#[allow(clippy::large_enum_variant)]\n"
            "#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]\n"
            '#[serde(tag = "type")]\n'
            f"pub enum {name} {{\n{''.join(variants)}}}\n\n"
            f"impl {name} {{\n"
            "    /// The frame's `type`.\n"
            "    pub fn type_name(&self) -> &'static str {\n"
            f"        match self {{\n{arms}        }}\n    }}\n}}\n\n"
            f"/// Every `type` of `{where}`, in the contract's order.\n"
            f"pub const {const}: &[&str] = &[\n{names}];\n"
        )
        return text, [t for _, t in tags]


def _is_object(node: dict[str, Any]) -> bool:
    return "$ref" not in node and (node.get("type") == "object" or "properties" in node)


PRELUDE = """\
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeMap;
use std::fmt;

/// A value that is not one of an enum's wire values.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UnknownValue;

/// A secret on the channel: serialised as-is, never shown by `Debug` (SEC-10, SEC-17).
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Redacted(String);

impl Redacted {
    pub fn new(value: impl Into<String>) -> Redacted {
        Redacted(value.into())
    }

    /// The secret itself, for the one place that hands it on.
    pub fn reveal(&self) -> &str {
        &self.0
    }
}

impl From<String> for Redacted {
    fn from(value: String) -> Redacted {
        Redacted(value)
    }
}

impl fmt::Debug for Redacted {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("<redacted>")
    }
}

/// A required property that may be null: present on the wire, `None` for null.
fn present<'de, D: Deserializer<'de>, T: Deserialize<'de>>(
    input: D,
) -> Result<Option<T>, D::Error> {
    Option::<T>::deserialize(input)
}
"""


def render(contracts: list[Contract]) -> str:
    by_id = {c.id: c for c in contracts}
    control = by_id.get(CONTROL_ID)
    if control is None:
        raise Unsupported("rust control codegen: no control contract")
    gen = Generator(control, contracts)
    unions = [gen.frames(name) for name in FRAMES]
    for name, schema in gen.defs.items():  # definitions no frame reaches still get a type
        gen.definition(name, schema)
    version = tomllib.loads(VERSIONS.read_text())["interfaces"]["control"]["version"]
    major, minor = (int(part) for part in version.split("."))
    sections = [
        f"// GENERATED by `python -m jana_tools codegen` from {SOURCE}\n"
        f"// source sha256: {control.sha256}\n"
        "// protocol version from scripts/jana_tools/codegen/versions.toml (interfaces.control)\n"
        "// Do not edit: change the schema in the specification and regenerate (ARC-30, D39).\n",
        PRELUDE,
        "/// This shell's control-channel version (ARC-29).\n"
        f"pub const PROTOCOL: ProtocolVersion = ProtocolVersion {{ major: {major}, minor: {minor} }};\n",
        *(text for text, _ in unions),
        *gen.out.items,
    ]
    return "\n".join(sections)


def generate_rust_control(contracts: list[Contract], out: Path) -> None:
    """`control.rs` beside the generated shell keys, and the module list that declares both."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "control.rs").write_text(render(contracts))
    (out / "mod.rs").write_text(
        "// GENERATED by `python -m jana_tools codegen`. Do not edit.\npub mod control;\npub mod keys;\n"
    )
