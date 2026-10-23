"""The per-release licence and dependency compliance record (OPS-36).

The record lists the SBOM diff against the previous release, with a reviewer for every added component or changed
licence; the content licences and attributions of every pack (CUR-23, CUR-24); the fonts, icons, data sets and
models shipped, each with its licence and any use restriction reviewed for use with minors; and whether the
generated third-party notices file is current. A release is blocked when a shipped component or asset has no licence
entry, or a restriction or new component has no review.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .. import REPO_ROOT

ASSETS = REPO_ROOT / "scripts" / "governance" / "shipped-assets.toml"
REVIEWS = REPO_ROOT / "scripts" / "governance" / "release-reviews.toml"
FONT_PREFIXES = ("@fontsource/", "@fontsource-variable/")
FONT_PACKAGES = {"katex"}
ICON_PACKAGES = {"lucide-react"}


def asset_register(path: Path = ASSETS) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {a["name"]: a for a in tomllib.loads(path.read_text()).get("asset", [])}


def shipped_assets(components: list[dict[str, Any]], models: list[str]) -> list[dict[str, str]]:
    """Fonts and icons found in the shipped components, and the models the release ships or recommends."""
    found = []
    for c in components:
        if c["name"].startswith(FONT_PREFIXES) or c["name"] in FONT_PACKAGES:
            found.append({"kind": "font", "name": c["name"]})
        elif c["name"] in ICON_PACKAGES:
            found.append({"kind": "icons", "name": c["name"]})
    found += [{"kind": "model", "name": m} for m in models]
    return found


def sbom_diff(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    before = {(c["ecosystem"], c["name"]): c for c in previous}
    added, changed = [], []
    for c in current:
        old = before.get((c["ecosystem"], c["name"]))
        if old is None:
            added.append(c)
        elif old["licence"] != c["licence"]:
            changed.append({**c, "previous_licence": old["licence"]})
    return {"added": added, "licence_changed": changed}


def review_register(path: Path = REVIEWS) -> dict[str, str]:
    """name@version -> reviewer (a pseudonymous role id) for added components and changed licences."""
    if not path.is_file():
        return {}
    return {f"{r['name']}@{r['version']}": r["reviewer"] for r in tomllib.loads(path.read_text()).get("review", [])}


def record(components: list[dict[str, Any]], previous: list[dict[str, Any]] | None, packs: list[dict[str, Any]],
           models: list[str], notices_current: bool, register: dict[str, dict[str, Any]] | None = None,
           reviews: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    """The compliance record and why it blocks the release (`blocking`, empty when the release may go)."""
    register = asset_register() if register is None else register
    reviews = review_register() if reviews is None else reviews
    blocking: list[str] = []
    diff = sbom_diff(previous or [], components) if previous is not None else {"added": [], "licence_changed": []}
    for c in diff["added"] + diff["licence_changed"]:
        key = f"{c['name']}@{c['version']}"
        c["reviewer"] = reviews.get(key)
        if not c["reviewer"]:
            blocking.append(f"{key}: added or licence changed since the previous release, with no reviewer")
    assets = []
    for asset in shipped_assets(components, models):
        entry = register.get(asset["name"])
        if entry is None or not entry.get("licence"):
            blocking.append(f"{asset['kind']} {asset['name']}: no licence entry (OPS-36)")
            assets.append({**asset, "licence": None})
            continue
        if entry.get("restrictions", "none") not in ("none",) and not entry.get("reviewed_for_minors"):
            blocking.append(f"{asset['kind']} {asset['name']}: restriction not reviewed for use with minors")
        assets.append({**asset, "licence": entry["licence"], "restrictions": entry.get("restrictions", "none"),
                       "reviewed_for_minors": bool(entry.get("reviewed_for_minors"))})  # fmt: skip
    for pack in packs:
        for credit in pack.get("credits", []):
            if not credit.get("licence"):
                blocking.append(f"{pack['pack_id']}: {credit.get('record_id')} has no licence (CUR-23)")
    if not notices_current:
        blocking.append("THIRD_PARTY_NOTICES is not current for this release")
    return {"sbom_diff": diff, "assets": assets, "packs": packs, "notices_current": notices_current,
            "components": len(components), "blocking": blocking}  # fmt: skip


def current_inputs() -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], bool]:
    """The shipped components, recommended models, pack credits and notices state of this checkout."""
    from pack_builder import licence
    from pack_builder.build import load_source
    from pack_builder.source import RECORD_TYPE  # noqa: F401 - the pack builder is installed

    from ..supply_chain import ARTEFACTS, artefact_components, notices_errors

    components = [{"ecosystem": c.ecosystem, "name": c.name, "version": c.version, "licence": c.licence}
                  for a in ARTEFACTS for c in artefact_components(a)]  # fmt: skip
    models_file = REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "recommended_models.json"
    models = [m["model"] for m in json.loads(models_file.read_text())["models"]]
    packs = []
    for pack_yaml in sorted((REPO_ROOT / "content" / "curriculum").glob("*/*/pack.yaml")):
        source = load_source(pack_yaml.parent)
        from agent_core.store.packs import row_id

        packs.append({"pack_id": source.pack["pack_id"], "version": source.pack["version"],
                      "credits": licence.credits(source.tables, row_id)})  # fmt: skip
    return components, models, packs, not notices_errors()
