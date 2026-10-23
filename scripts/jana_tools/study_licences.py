"""Version/platform-bound native wheel audit. Unknown or changed files require a fresh review.

The native policy exception is limited to this exact reviewed wheel and the owner's recorded approval.
It never adds licence families to SEC-23's global whitelist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import REPO_ROOT

REVIEW = "scripts/governance/m42-pdfium-native-review.json"


def record(root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / REVIEW
    return dict(json.loads(path.read_text())) if path.is_file() else {}


def audit(site: Path | None, root: Path = REPO_ROOT) -> list[str]:
    reviewed = record(root)
    if not reviewed or site is None:
        return ["M42 PDFium native review or installed wheel is missing"]
    owner_path = root / "scripts/governance" / reviewed["owner_approval"]
    owner = json.loads(owner_path.read_text()) if owner_path.is_file() else {}
    if owner.get("statement") != "approved now" or "Native dependency licence review" not in owner.get(
        "question_scope", []
    ):
        return ["M42 PDFium review has no recorded owner approval"]
    dist = site / f"{reviewed['name']}-{reviewed['version']}.dist-info"
    actual = {str(p.relative_to(dist)) for p in (dist / "licenses").rglob("*") if p.is_file()}
    platform = next((p for p in reviewed.get("platforms", [reviewed]) if set(p["files"]) == actual), None)
    if platform is None:
        return ["M42 PDFium native audit: installed licence inventory differs from reviewed platforms"]
    reviewed = {**reviewed, **platform}
    expected = {"METADATA": reviewed["metadata_sha256"], **reviewed["files"]}
    errors = []
    for relative, digest in expected.items():
        path = dist / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"M42 PDFium native audit: missing or changed {relative}")
    binary = site / reviewed["native_binary"]["path"]
    if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest() != reviewed["native_binary"]["sha256"]:
        errors.append("M42 PDFium native audit: binary differs from the reviewed platform wheel")
    return errors


def metadata_licence(name: str, site: Path, root: Path = REPO_ROOT) -> str | None:
    reviewed = record(root)
    if name == reviewed.get("name") and not audit(site, root):
        return str(reviewed["wrapper_licence"])
    return None


def native_component(root: Path = REPO_ROOT) -> dict[str, str]:
    return dict(record(root).get("native_component", {}))
