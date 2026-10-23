"""The evaluation item bank (EVL-24): metadata for every item, and the held-out leakage check.

Scenario files hold behaviour only; each suite file has a sidecar `<file>.meta.yaml` with `defaults` and per-item
`items` overrides giving every item its author, source, licence, creation date, tool verification and teacher
reviewers. The bank build fails on an item without them. Items are synthetic unless they came from a pilot under
`research_use` consent, de-identified. Answer-oracle items are pack items; their provenance and licence are enforced
by the pack build (CUR-23), so the bank reads them from there.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pack_builder.heldout import item_hashes, text_hashes

from .. import REPO_ROOT

EVALS = REPO_ROOT / "evals"
SUITE_DIRS = ("scenarios", "safety")
META_FIELDS = ("author", "source", "licence", "created", "verification", "reviewers")
LICENCES = frozenset({"LicenseRef-Own", "CC0-1.0", "LicenseRef-PublicDomain", "CC-BY-3.0", "CC-BY-4.0"})
VERIFICATION = frozenset({"tool_checked", "not_applicable", "pending"})


@dataclass(frozen=True)
class BankItem:
    suite_file: str
    item_id: str
    split: str
    meta: dict[str, Any]
    item: dict[str, Any]


def suite_files(root: Path = EVALS) -> list[Path]:
    return [p for d in SUITE_DIRS for p in sorted((root / d).glob("*.yaml")) if not p.name.endswith(".meta.yaml")]


def build_bank(root: Path = EVALS) -> tuple[list[BankItem], list[str]]:
    """Every scenario item with its merged metadata, and why the bank build fails (empty when it passes)."""
    items: list[BankItem] = []
    errors: list[str] = []
    for path in suite_files(root):
        rel = str(path.relative_to(root.parent))
        suite = yaml.safe_load(path.read_text())
        sidecar = path.with_name(path.stem + ".meta.yaml")
        meta = yaml.safe_load(sidecar.read_text()) if sidecar.is_file() else {}
        defaults, overrides = meta.get("defaults", {}), meta.get("items", {}) or {}
        for unknown in sorted(set(overrides) - {s["id"] for s in suite["scenarios"]}):
            errors.append(f"{rel}: metadata for {unknown}, which is not in the suite")
        for scenario in suite["scenarios"]:
            merged = {**defaults, **overrides.get(scenario["id"], {})}
            errors += [f"{rel}: {scenario['id']}: {e}" for e in item_errors(merged, scenario)]
            items.append(BankItem(rel, scenario["id"], scenario["split"], merged, scenario))
    return items, errors


def item_errors(meta: dict[str, Any], item: dict[str, Any]) -> list[str]:
    errors = [f"no {name} metadata (EVL-24)" for name in META_FIELDS if meta.get(name) in (None, "")]
    if meta.get("licence") and meta["licence"] not in LICENCES:
        errors.append(f"licence {meta['licence']} is not on the approved list (EVL-24)")
    if meta.get("verification") and meta["verification"] not in VERIFICATION:
        errors.append(f"verification {meta['verification']} is not one of {sorted(VERIFICATION)}")
    if "reviewers" in meta and not isinstance(meta["reviewers"], list):
        errors.append("reviewers must be a list of reviewer ids")
    if not item.get("synthetic", False):
        consent = meta.get("consent") == "research_use" and meta.get("deidentified") is True
        if not consent:
            errors.append("a non-synthetic item needs research_use consent and de-identification (EVL-24)")
    if item.get("split") == "regression" and not meta.get("regression_of"):
        errors.append("a regression item links its source (regression_of: INC-…, RPT-…, EVL-…) (EVL-20)")
    return errors


# --- held-out leakage ---------------------------------------------------------------------------------------------


def shipped_hashes(
    curriculum: Path = REPO_ROOT / "content" / "curriculum", packs: list[Path] | None = None
) -> set[str]:
    """Item content of every student pack: the sources each pack is built from, plus any built pack documents."""
    found: set[str] = set()
    for path in sorted(curriculum.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else [data]
        found |= item_hashes(r for r in records if isinstance(r, dict))
    for pack in packs or []:
        found |= text_hashes(json.loads(pack.read_text(encoding="utf-8")).get("tables", {}))
    return found


def training_hashes(root: Path = REPO_ROOT / "training") -> set[str]:
    """Item content of every training manifest's shards (dataset cards, TRN; JSON lines)."""
    found: set[str] = set()
    for card_path in sorted(root.rglob("*dataset-card*.json")) if root.is_dir() else []:
        card = json.loads(card_path.read_text())
        for shard in card.get("manifest", {}).get("shards", []):
            shard_path = card_path.parent / shard["path"]
            for line in shard_path.read_text().splitlines() if shard_path.is_file() else []:
                if line.strip():
                    found |= text_hashes(json.loads(line))
    return found


def leakage_errors(held_out: set[str], shipped: set[str], training: set[str]) -> list[str]:
    errors = []
    if leaked := held_out & shipped:
        errors.append(f"held-out item content appears in a shipped pack ({len(leaked)} matching hashes; EVL-24)")
    if leaked := held_out & training:
        errors.append(f"held-out item content appears in a training manifest ({len(leaked)} matching hashes; EVL-24)")
    return errors


# --- no eval-only code paths (EVL-01) -----------------------------------------------------------------------------

PRODUCT_CODE = ("services/agent-core/agent_core", "services/tool-worker/tool_worker", "packages/client-core/src",
                "packages/ui/src", "apps/desktop/src", "apps/desktop/src-tauri/src")  # fmt: skip
EVAL_ONLY = re.compile(
    r"\b(eval_only|EVAL_MODE|JANA_EVAL\w*|is_eval(uation)?_run|under_harness)\b|^\s*(from|import)\s+jana_tools\b"
)


def eval_only_paths(root: Path = REPO_ROOT) -> list[str]:
    """Product source lines that branch on, or import, the harness (none is allowed)."""
    hits = []
    for base in PRODUCT_CODE:
        for path in sorted((root / base).rglob("*")) if (root / base).is_dir() else []:
            if path.suffix not in (".py", ".ts", ".tsx", ".rs") or "generated" in path.parts:
                continue
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if EVAL_ONLY.search(line):
                    hits.append(f"{path.relative_to(root)}:{n}")
    return hits
