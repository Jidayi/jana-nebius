"""Contract fixture corpus (evals/contracts/): at least one valid and one invalid instance per contract, and per
definition of a definition catalogue, validated in Python and TypeScript (the cross-language parity check).

Valid fixtures are the contracts' own examples where they exist, plus a minimal instance synthesised from the
schema and checked against it; invalid fixtures are derived from a valid one by one targeted mutation. All are
synthetic (no real student data). Regenerate with `python -m jana_tools fixtures --write`.
"""

from __future__ import annotations

import copy
import json
import re
import re._constants as sre_constants  # the stdlib regex parser (sre_parse is deprecated)
import re._parser as sre_parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from . import REPO_ROOT
from .codegen import CONTRACTS
from .codegen.sources import NAMESPACE, Contract, load_contracts

CORPUS = REPO_ROOT / "evals" / "contracts"
INDEX = CORPUS / "index.json"
# YAML examples in the contract folders and the contract each one instantiates.
YAML_EXAMPLES: dict[str, str] = {
    "agents/router.example.yaml": "agents/router-config",
    "evals/scenario.example.yaml": "evals/scenario",
    "learning/rules.example.yaml": "learning/rule",
}
# "No constraint here": distinct from an explicit null, which a conditional branch may require.
NOTHING: Any = type("Nothing", (), {"__repr__": lambda self: "NOTHING"})()
FORMATS = {"date": "2026-01-15", "date-time": "2026-01-15T09:30:00Z", "uri": "https://example.invalid/x"}


# --- regex -> a short matching string, deterministically --------------------------------------------------


def _sample_class(items: list[Any]) -> str:
    negate = any(op == sre_constants.NEGATE for op, _ in items)
    candidates: list[str] = []
    for op, av in items:
        if op == sre_constants.LITERAL:
            candidates.append(chr(av))
        elif op == sre_constants.RANGE:
            candidates.append(chr(av[0]))
        elif op == sre_constants.CATEGORY:
            candidates.append({sre_constants.CATEGORY_DIGIT: "0", sre_constants.CATEGORY_WORD: "a",
                               sre_constants.CATEGORY_SPACE: " "}.get(av, "a"))  # fmt: skip
    if negate:
        return next(c for c in "aA0_-x" if c not in candidates)
    return candidates[0] if candidates else "a"


def _emit(parsed: Any, extra: int) -> str:
    out = []
    for op, av in parsed:
        if op == sre_constants.LITERAL:
            out.append(chr(av))
        elif op == sre_constants.NOT_LITERAL:
            out.append("a" if chr(av) != "a" else "b")
        elif op == sre_constants.ANY:
            out.append("a")
        elif op == sre_constants.IN:
            out.append(_sample_class(av))
        elif op in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT):
            low, high, sub = av
            count = low if high == low else min(high, low + extra)
            out.append("".join(_emit(sub, extra) for _ in range(count)))
        elif op == sre_constants.SUBPATTERN:
            out.append(_emit(av[-1], extra))
        elif op == sre_constants.BRANCH:
            out.append(_emit(av[1][0], extra))
        elif op == sre_constants.CATEGORY:
            out.append(_sample_class([(op, av)]))
        elif op in (sre_constants.AT, sre_constants.ASSERT, sre_constants.ASSERT_NOT):
            continue
        else:
            raise ValueError(f"unsupported regex construct {op}")
    return "".join(out)


def string_for(pattern: str | None, min_length: int = 0, max_length: int | None = None) -> str:
    if pattern is None:
        return "x" * max(min_length, 1)
    parsed = sre_parse.parse(pattern)
    for extra in range(0, 64):
        value = _emit(parsed, extra)
        if len(value) < min_length and not pattern.endswith("$"):
            value += "x" * (min_length - len(value))  # an open-ended pattern: pad after the match
        if len(value) >= min_length and re.search(pattern, value):
            if max_length is None or len(value) <= max_length:
                return value
    raise ValueError(f"cannot synthesise a string for {pattern!r} with length >= {min_length}")


# --- schema -> a minimal valid instance ----------------------------------------------------------------------


@dataclass
class Synth:
    registry: Registry
    documents: dict[str, dict[str, Any]]

    def validator(self, schema: dict[str, Any]) -> Draft202012Validator:
        return Draft202012Validator(schema, registry=self.registry, format_checker=FormatChecker())

    def resolve(self, ref: str, base: str) -> tuple[dict[str, Any], str]:
        if ref.startswith("#"):
            doc_id, fragment = base, ref[1:]
        else:
            absolute = ref if ref.startswith(NAMESPACE) else base.rsplit("/", 1)[0] + "/" + ref
            doc_id, _, fragment = absolute.partition("#")
        node: Any = self.documents[doc_id]
        for part in [p for p in fragment.split("/") if p]:  # a JSON pointer: list steps are indices
            node = node[int(part)] if isinstance(node, list) else node[part.replace("~1", "/").replace("~0", "~")]
        return node, doc_id

    def _check(self, node: dict[str, Any], base: str, value: Any) -> bool:
        wrapper = {"$schema": "https://json-schema.org/draft/2020-12/schema", "allOf": [self._rebased(node, base)]}
        return self.validator(wrapper).is_valid(value)

    def _rebased(self, node: Any, base: str) -> Any:
        """A subschema with relative refs made absolute, so it can be checked on its own."""
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str) and not value.startswith(NAMESPACE):
                    value = base + value if value.startswith("#") else base.rsplit("/", 1)[0] + "/" + value
                out[key] = value if key in ("const", "enum", "default") else self._rebased(value, base)
            return out
        if isinstance(node, list):
            return [self._rebased(x, base) for x in node]
        return node

    def gen(self, node: Any, base: str, depth: int = 0) -> Any:
        if depth > 40:
            raise RecursionError("schema too deep to synthesise")
        if node is True or node == {}:
            return NOTHING
        if "$ref" in node:
            target, doc = self.resolve(node["$ref"], base)
            rest = {k: v for k, v in node.items() if k != "$ref"}
            if not rest:
                return self.gen(target, doc, depth + 1)
            # A $ref with sibling constraints: generate the target, then apply the siblings.
            return self._apply(self._rebased(target, doc), rest, base, depth)
        if "const" in node:
            return copy.deepcopy(node["const"])
        if "enum" in node:
            return copy.deepcopy(node["enum"][0])
        node = self._flatten(node, base)
        for key in ("oneOf", "anyOf"):
            if key in node:
                rest = {k: v for k, v in node.items() if k != key}
                branches = sorted(node[key], key=lambda b: b.get("type") == "null")  # prefer real structure
                for branch in branches:
                    try:
                        value = self.gen(merge_schema(rest, branch), base, depth + 1)
                    except (ValueError, RecursionError, KeyError):
                        continue
                    if self._check(node, base, value):
                        return value
                raise ValueError(f"no {key} branch synthesises a valid instance")
        value = self._typed(node, base, depth)
        # Conditionals: when an `if` holds for the instance, regenerate under the merged `then` (or `else`).
        conditionals = [s for s in node.get("allOf", []) if "if" in s] + ([node] if "if" in node else [])
        applied: set[int] = set()
        for _ in range(len(conditionals) + 1):
            changed = False
            for i, sub in enumerate(conditionals):
                if i in applied:
                    continue
                branch = sub.get("then") if self._check(sub["if"], base, value) else sub.get("else")
                if branch is not None:
                    node = merge_schema(node, branch)
                    applied.add(i)
                    changed = True
            if not changed:
                break
            # A selected conditional may itself introduce a union or reference. Go through the full
            # generator again, without re-entering the conditions this loop already owns.
            selected = {k: v for k, v in node.items() if k not in ("if", "then", "else", "allOf")}
            plain = [part for part in node.get("allOf", []) if "if" not in part]
            if plain:
                selected["allOf"] = plain
            value = self.gen(selected, base, depth + 1)
        return value

    def _apply(self, target: dict[str, Any], rest: dict[str, Any], base: str, depth: int) -> Any:
        return self.gen(merge_schema(target, rest), base, depth + 1)

    def _flatten(self, node: dict[str, Any], base: str) -> dict[str, Any]:
        """Merge unconditional allOf parts (referenced ones resolved) into the node; conditional parts stay."""
        parts = node.get("allOf", [])
        plain = [s for s in parts if "if" not in s]
        if not plain:
            return node
        out = {k: v for k, v in node.items() if k != "allOf"}
        for part in plain:
            if "$ref" in part and len(part) == 1:
                target, doc = self.resolve(part["$ref"], base)
                part = self._flatten(self._rebased(target, doc), base)
            out = merge_schema(out, part)
        rest = [s for s in parts if s not in plain]
        if rest:
            out["allOf"] = rest
        return out

    def _typed(self, node: dict[str, Any], base: str, depth: int) -> Any:
        kind = node.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), "null")
        if kind is None:
            kind = "object" if ("properties" in node or "required" in node) else None
        if kind == "object":
            out = {}
            props = node.get("properties", {})
            for name in node.get("required", []):
                if props.get(name) is False:
                    continue
                value = self.gen(props[name], base, depth + 1) if name in props else NOTHING
                out[name] = {} if value is NOTHING else value
            for name, sub in props.items():
                if len(out) >= node.get("minProperties", 0):
                    break
                if sub is False:
                    continue
                value = self.gen(sub, base, depth + 1)
                out.setdefault(name, {} if value is NOTHING else value)
            if len(out) < node.get("minProperties", 0) and isinstance(node.get("additionalProperties"), dict):
                names = self.gen(node.get("propertyNames", {"type": "string"}), base, depth + 1)
                value = self.gen(node["additionalProperties"], base, depth + 1)
                out[names if isinstance(names, str) else "key"] = {} if value is NOTHING else value
            return out
        if kind == "array":
            items = []
            prefix = node.get("prefixItems", [])
            count = max(node.get("minItems", 0), len(prefix), node.get("minContains", 1) if "contains" in node else 0)
            for i in range(count):
                if i < len(prefix):
                    items.append(self.gen(prefix[i], base, depth + 1))
                elif "contains" in node and i < node.get("minContains", 1):
                    item = self.gen(node.get("items", {}), base, depth + 1)
                    if item is NOTHING or not self._check(node["contains"], base, item):
                        item = self.gen(node["contains"], base, depth + 1)
                    items.append(item)
                else:
                    item = self.gen(node.get("items", {}), base, depth + 1)
                    items.append({} if item is NOTHING else item)
            if node.get("uniqueItems"):
                items = self._unique(items, node.get("items", {}), base)
            return items
        if kind == "string":
            if node.get("format") in FORMATS:
                return FORMATS[node["format"]]
            return string_for(node.get("pattern"), node.get("minLength", 0), node.get("maxLength"))
        if kind in ("integer", "number"):
            low = node.get("minimum", node.get("exclusiveMinimum", -1) + 1 if "exclusiveMinimum" in node else 0)
            if "maximum" in node and low > node["maximum"]:
                low = node["maximum"]
            step = node.get("multipleOf")
            if step:
                low = step * -(-low // step)
            return int(low) if kind == "integer" else low
        if kind == "boolean":
            return True
        if kind == "null":
            return None
        return NOTHING

    def _unique(self, items: list[Any], item_schema: Any, base: str) -> list[Any]:
        """Make items distinct: the next enum value where the items are an enumeration, else a suffix."""
        if isinstance(item_schema, dict) and "$ref" in item_schema:
            item_schema, base = self.resolve(item_schema["$ref"], base)
        choices = item_schema.get("enum") if isinstance(item_schema, dict) else None
        out: list[Any] = []
        for i, item in enumerate(items):
            if item in out and choices:
                item = next(c for c in choices if c not in out)
            while item in out and isinstance(item, str):
                item = item + str(i)
            out.append(item)
        return out


def merge_schema(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Combine two schemas for synthesis: properties merge per name, `required` unions, the rest of `b` wins."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    out = dict(a)
    for key, value in b.items():
        if key in ("properties", "$defs") and isinstance(out.get(key), dict):
            merged = dict(out[key])
            for name, sub in value.items():
                merged[name] = merge_schema(merged[name], sub) if name in merged else sub
            out[key] = merged
        elif key in ("items", "additionalProperties", "contains") and isinstance(out.get(key), dict):
            out[key] = merge_schema(out[key], value)
        elif key == "required" and isinstance(out.get(key), list):
            out[key] = list(dict.fromkeys(out[key] + value))
        elif key == "allOf" and isinstance(out.get(key), list):
            out[key] = out[key] + value
        elif key == "type" and "enum" in out and value != "null":
            continue
        else:
            out[key] = value
    if b.get("type") == "null" or b.get("const", 0) is None:
        for key in ("enum", "const", "minimum", "maximum"):
            if key in out and key not in b:
                del out[key]
    return out


def synth(contracts: list[Contract]) -> Synth:
    documents = {c.id: c.schema for c in contracts}
    resources = [(i, Resource.from_contents(s, default_specification=DRAFT202012)) for i, s in documents.items()]
    return Synth(Registry().with_resources(resources), documents)


# --- invalid instances ---------------------------------------------------------------------------------------


def mutations(valid: Any) -> list[tuple[str, Any]]:
    """Candidate invalid instances derived from a valid one: an unknown property, a missing required property,
    a wrong type."""
    out: list[tuple[str, Any]] = []
    if isinstance(valid, dict):
        out.append(("unknown_property", {**valid, "__unknown_field__": 1}))
        for key in valid:
            out.append((f"missing_{key}", {k: v for k, v in valid.items() if k != key}))
            break
    out.append(("wrong_type", 42 if not isinstance(valid, int) or isinstance(valid, bool) else "42"))
    return out


# --- the corpus -------------------------------------------------------------------------------------------


def targets(contracts: list[Contract]) -> list[str]:
    """Contract names that get fixtures: every root, every definition of a definition catalogue, and every other
    definition an API endpoint names as its request or response body (API-23 tests each endpoint's bodies)."""
    names = []
    for c in contracts:
        if c.has_root:
            names.append(c.stem)
        else:
            names += [f"{c.stem}#/$defs/{d}" for d in c.definitions]
    commands = json.loads((CONTRACTS / "api/commands.schema.json").read_text())
    for endpoint in commands["x-endpoints"]:
        for ref in (endpoint["request"], endpoint["response"]):
            if ref:
                name = (
                    ref.removeprefix(NAMESPACE)
                    if ref.startswith(NAMESPACE)
                    else "api/commands" + ref
                    if ref.startswith("#")
                    else ref
                )
                if name not in names:
                    names.append(name)
    return names


def _node_for(name: str, s: Synth) -> tuple[dict[str, Any], str]:
    doc, _, fragment = (NAMESPACE + name).partition("#")
    return s.resolve("#" + fragment, doc) if fragment else (s.documents[doc], doc)


def build(contracts: list[Contract] | None = None) -> tuple[dict[str, Any], list[str]]:
    """The fixture files (relative path -> instance), with an index, and the names that could not be
    synthesised."""
    contracts = contracts or load_contracts(CONTRACTS)
    s = synth(contracts)
    files: dict[str, Any] = {}
    index: list[dict[str, str]] = []
    failed: list[str] = []

    def add(name: str, kind: str, label: str, instance: Any, origin: str) -> None:
        folder = name.replace("#/$defs/", "/")
        rel = f"{folder}/{kind}/{label}.json"
        files[rel] = instance
        index.append({"file": rel, "contract": name, "expect": kind, "origin": origin})

    # Public source examples and generated corpus are separate, so an edited corpus is still detected.
    for example in json.loads((CONTRACTS / "examples.json").read_text()):
        add(example["contract"], "valid", example["label"], example["value"], "contract example")

    for name in targets(contracts):
        node, base = _node_for(name, s)
        check = s.validator({"$ref": NAMESPACE + name})
        folder = CORPUS / name.replace("#/$defs/", "/")
        hand = sorted((folder / "valid").glob("hand_*.json")) if (folder / "valid").is_dir() else []
        for path in hand:
            add(name, "valid", path.stem, json.loads(path.read_text()), "hand-written")
        try:
            value = s.gen(node, base)
            if not check.is_valid(value):
                first = next(iter(check.iter_errors(value)))
                raise ValueError(f"synthesised instance invalid at {first.json_path}: {first.message}")
            add(name, "valid", "minimal", value, "synthesised")
        except (ValueError, RecursionError, KeyError) as exc:
            if not hand:
                failed.append(f"{name}: {exc}")
                continue
            value = json.loads(hand[0].read_text())
        for label, bad in mutations(value):
            if not check.is_valid(bad):
                add(name, "invalid", label, bad, "derived")
                break
    files["index.json"] = sorted(index, key=lambda e: e["file"])
    files.update(recorded_scripts(s))
    return files, failed


# --- recorded scripts for the fakes ----------------------------------------------------------------------

ULID = "01JZ00000000000000000000"  # 24 chars; two more make a deterministic Crockford ULID


def _ulid(n: int) -> str:
    return f"{ULID}{n:02d}"


def _event(s: Synth, definition: str, **fields: Any) -> dict[str, Any]:
    node, base = _node_for(f"api/events#/$defs/{definition}", s)
    value = s.gen(node, base)
    value.update(fields)
    return value


def recorded_scripts(s: Synth) -> dict[str, Any]:
    """Synthetic, contract-valid scripts: one guided turn on the event stream, a worker session and the model
    replies of a turn. Every item is validated by the fakes when they load it."""
    session, turn, part = f"ses_{_ulid(1)}", f"trn_{_ulid(2)}", f"prt_{_ulid(3)}"
    events = [
        _event(s, "ev_turn_start", turn_id=turn),
        _event(s, "ev_status"),
        _event(s, "ev_part_start", part_id=part, kind="text", index=0),
        _event(s, "ev_text_delta", part_id=part, delta="What do we know about the car's motion? "),
        _event(s, "ev_text_delta", part_id=part, delta="Write down u, v and t."),
        _event(s, "ev_part_end", part_id=part, status="complete", duration_ms=420),
        _event(s, "ev_turn_end", status="complete", stop_reason="completed"),
    ]
    envelopes = [
        {"v": 1, "channel": "session", "seq": i + 1, "epoch": "epoch-0001", "session_id": session, "turn_id": turn,
         "ts": 1791460800000 + 50 * i, "event": event}
        for i, event in enumerate(events)
    ]  # fmt: skip

    def result(definition: str) -> Any:
        node, base = _node_for(f"tools/worker-protocol#/$defs/{definition}", s)
        return s.gen(node, base)

    hello = result("HelloResult")
    exchanges = [
        {"method": "worker.hello", "result": hello},
        {"method": "worker.ping", "result": result("PingResult"), "repeat": True},
        {"method": "fn.call", "match": {"name": "math_solve"}, "result": result("FnCallResult")},
        {"method": "worker.shutdown", "result": result("AckResult")},
    ]

    def reply(contract: str, role: str) -> dict[str, Any]:
        node, base = _node_for(contract, s)
        return {"role": role, "contract": contract, "json": s.gen(node, base)}

    replies = [
        reply("agents/solution-plan", "solver"),
        reply("agents/tutor-turn", "coach"),
        {"role": "reflector", "content": "Session note: worked on reading the question for known quantities."},
    ]
    return {
        "scripts/stream_guided_turn.json": {"description": "One synthetic guided turn on the session channel.",
                                            "envelopes": envelopes},
        "scripts/worker_session.json": {"description": "Synthetic worker handshake, ping, one call and shutdown.",
                                        "exchanges": exchanges},
        "scripts/provider_guided_turn.json": {"description": "Synthetic model replies for one guided turn.",
                                              "replies": replies},
    }  # fmt: skip


def write_corpus(files: dict[str, Any], root: Path = CORPUS) -> None:
    for rel, instance in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n")


def corpus_errors(root: Path = CORPUS) -> list[str]:
    """The committed corpus matches a fresh build, covers every target, has no synthesis failures and holds no file
    the build does not make (a fixture left behind for a definition the contract no longer has)."""
    files, failed = build()
    errors = [f"cannot build a valid fixture for {f}" for f in failed]
    for rel, instance in files.items():
        path = root / rel
        if not path.is_file() or json.loads(path.read_text()) != instance:
            errors.append(f"evals/contracts/{rel} is stale; run: uv run python -m jana_tools fixtures --write")
    made = set(files)
    for path in sorted(p for p in root.rglob("*.json") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in made:
            errors.append(f"evals/contracts/{rel} is not a fixture of the current contracts; delete it")
    index = files["index.json"]
    for name in targets(load_contracts(CONTRACTS)):
        kinds = {e["expect"] for e in index if e["contract"] == name}
        errors += [f"{name}: no {kind} fixture" for kind in ("valid", "invalid") if kind not in kinds]
    return errors
