"""Candidate-bound acceptance reconciliation. Definitions and supplementary checks never imply acceptance.

Prepare a manifest before the test run, then report with its JUnit files. An input change, old result or failed case
cannot produce a passing status. External observations and incomplete software checks remain distinct rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import REPO_ROOT
from .coverage import acceptance_tests, defined_test_locations, junit_results, merge, primary_requirements
from .repo import repo_paths

SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".rs",
    ".mjs",
    ".js",
    ".css",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".lock",
    ".html",
    ".svg",
    ".sh",
    ".spec",
    ".txt",
    ".in",
}
EXCLUDED = (
    "scripts/governance/app-completion-acceptance.json",
    "scripts/governance/app-completion-acceptance-map.json",
    "scripts/governance/app-completion-studio.json",
    "scripts/governance/app-completion-software-verification.json",
)


def inputs(root: Path) -> dict[str, str]:
    paths = sorted(p for p in repo_paths(root) if Path(p).suffix in SUFFIXES and not p.startswith(EXCLUDED))
    manifest = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths if (root / p).is_file()}
    # The private specification is ignored by the monorepo's Git inventory. Bind its working files as well as its pin.
    specification = root / "docs/specification"
    if specification.is_dir():
        for path in sorted(specification.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES | {".md"}:
                if path.is_symlink():
                    raise ValueError("Specification inputs must not be symbolic links")
                manifest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def prepare(root: Path = REPO_ROOT) -> dict[str, Any]:
    manifest = inputs(root)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "head": head,
        "spec_pin": (root / "spec.lock").read_text().strip(),
        "input_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "inputs": manifest,
    }


def reconcile(
    candidate: dict[str, Any],
    milestones: list[str],
    junit: list[Path],
    mappings: dict[str, Any],
    root: Path = REPO_ROOT,
    docs: Path | None = None,
) -> dict[str, Any]:
    current = prepare(root)
    same = all(current[k] == candidate[k] for k in ("head", "spec_pin", "input_sha256"))
    created = datetime.fromisoformat(candidate["created_at"]).timestamp()
    artifacts = [
        {
            "path": str(p),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "after_candidate": p.stat().st_mtime >= created,
        }
        for p in junit
    ]
    bound = same and all(a["after_candidate"] for a in artifacts)
    results = merge(*(junit_results(p) for p in junit)) if bound else {}
    definitions = defined_test_locations(root)
    observed: dict[str, set[str]] = {}
    if bound:
        for artifact in junit:
            for case in ET.parse(artifact).getroot().iter("testcase"):  # noqa: S314 - locally generated JUnit
                name = case.get("name", "").split(" > ")[-1].split("[")[0].split(" ")[0].removesuffix(":")
                classname = case.get("classname", "").replace("\\", "/")
                matching = [
                    rel
                    for rel in definitions.get(name, [])
                    if classname in (rel, str(root / rel), rel.removesuffix(".py").replace("/", "."))
                    or ("/" in classname and rel.endswith("/" + classname))
                ]
                if len(matching) == 1:
                    observed.setdefault(name, set()).add(matching[0])
    rows = []
    for milestone in milestones:
        kwargs = {"docs": docs} if docs else {}
        for wp, rid in primary_requirements(milestone, **kwargs):
            for name in acceptance_tests(rid, **kwargs):
                note = mappings.get(name, {})
                external = note.get("external", [])
                raw = results.get(name, "not run") if name in definitions else "missing"
                locations = definitions.get(name, [])
                unrun_definitions = (
                    [p for p in locations if p not in observed.get(name, set())] if len(locations) > 1 else []
                )
                if raw == "pass" and unrun_definitions:
                    raw = "not run"
                rows.append(
                    {
                        "milestone": milestone,
                        "work_package": wp,
                        "requirement": rid,
                        "test": name,
                        "definition": locations[-1] if locations else None,
                        "definitions": locations,
                        "unrun_definitions": unrun_definitions,
                        "result": raw,
                        "software": note.get("software", []),
                        "external": external,
                        "scope": note.get("scope", "Canonical acceptance definition; see governing requirement"),
                        "software_follow_up": (
                            "Add or extend the exact acceptance check; source-area pointers do not establish coverage"
                            if raw == "missing"
                            else "Run this check on the candidate"
                            if raw == "not run"
                            else "Resolve the failed or skipped prerequisite"
                            if raw in ("fail", "skipped")
                            else None
                        ),
                        "acceptance": "external evidence required" if external else "independent review required",
                    }
                )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    return {
        "candidate": candidate,
        "candidate_current": same,
        "results_bound": bound,
        "artifacts": artifacts,
        "counts": counts,
        "candidate_acceptance": False,
        "mapping_sha256": hashlib.sha256(json.dumps(mappings, sort_keys=True).encode()).hexdigest(),
        "rows": rows,
        "meaning": (
            "Pass means an executed canonical software check on these inputs. "
            "Missing, not run and external evidence are separate; no milestone approval is inferred."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "report"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--junit", type=Path, action="append", default=[])
    parser.add_argument("--milestone", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "prepare":
        value = prepare()
    else:
        if not args.candidate or not args.mapping or not args.milestone:
            parser.error("report requires --candidate, --mapping and at least one --milestone")
        value = reconcile(
            json.loads(args.candidate.read_text()),
            args.milestone,
            args.junit,
            json.loads(args.mapping.read_text())["tests"],
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(value, indent=2) + "\n")
    if args.mode == "report" and not value["results_bound"]:
        raise SystemExit("Candidate changed or a result predates it; rerun the affected checks")


if __name__ == "__main__":
    main()
