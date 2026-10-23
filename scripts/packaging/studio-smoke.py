"""Exercise a frozen authoring backend from another cwd with a disposable, fictional workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pack_builder import source
from pack_builder.accounts import Accounts

ROOT = Path(__file__).resolve().parents[2]
ITEM = "itm.phy.o.motion.0001"


def fixture(root: Path) -> Path:
    pack = root / "content/curriculum/phy/o"
    original = ROOT / "content/curriculum/phy/o"
    pack.mkdir(parents=True)
    for name in ("pack.yaml", "map.yaml"):
        shutil.copy(original / name, pack / name)
    for name in ("kcs", "diagrams"):
        shutil.copytree(original / name, pack / name)
    shutil.copytree(ROOT / "content/curriculum/ref", root / "content/curriculum/ref")
    for table, identity in [
        ("items", ITEM),
        ("worked_examples", "wex.phy.o.motion.0001"),
        ("misconceptions", "mc.phy.o.time_over_distance"),
    ]:
        directory = pack / source.PER_RECORD[table]
        directory.mkdir()
        shutil.copy(original / source.PER_RECORD[table] / (identity + ".yaml"), directory / (identity + ".yaml"))
    shutil.copytree(ROOT / "skills/agent/agent-diagnose-question", root / "skills/agent/agent-diagnose-question")
    return pack


def bundle_hash(root: Path) -> str:
    manifest = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def smoke(backend: Path, out: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="jana-studio-smoke-") as name:
        temporary = Path(name)
        root = temporary / "workspace"
        fixture(root)
        home = temporary / "authors"
        Accounts(home).create("lead", "Synthetic Lead", "lead@example.test", ["curriculum_lead"])
        env = {**os.environ, "JANA_AUTHORING_HOME": str(home), "JANA_AUTHOR": "lead", "PATH": "/usr/bin:/bin"}
        child = subprocess.Popen(
            [str(backend.resolve()), "--workspace", str(root), "--stdio"],
            cwd=temporary,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        def call(**request):
            assert child.stdin and child.stdout
            child.stdin.write(json.dumps(request) + "\n")
            child.stdin.flush()
            line = child.stdout.readline()
            if not line:
                assert child.stderr
                raise AssertionError("Frozen backend stopped: " + child.stderr.read()[-3000:])
            value = json.loads(line)
            assert "error" not in value, value
            return value["result"]

        checks = []
        try:
            inventory = call(op="workspace")
            assert inventory["packs"] and inventory["skills"] and inventory["diagrams"]
            checks.append("workspace-and-bundled-contracts")
            opened = call(op="open", pack="pack.phy.o", table="items", id=ITEM)
            report = call(op="validate", pack="pack.phy.o", table="items", record=opened["record"])
            assert report["ok"] and report["checks"] and report["preview"]["lesson"]
            checks.append("production-verifier-and-preview")
            mark = call(op="mark", pack="pack.phy.o", record=opened["record"], part="a", response="8.0 m/s")
            assert mark["ok"] and mark["verdict"]["outcome"] == "correct"
            checks.append("production-marker")
            skill = call(op="skill_open", name="agent-diagnose-question")
            assert skill["report"]["schema"] and skill["report"]["eval_cases"]
            checks.append("skill-lint-contract-and-eval-assets")
            diagram = call(op="diagram_open", pack="pack.phy.o", id="dgm.phy.plane_mirror_reflection.v1")
            assert diagram["report"]["ok"] and diagram["report"]["preview"]
            checks.append("diagram-validation-and-production-preview")
            assert call(op="job_personas")["personas"]
            checks.append("bundled-personas")
            # The QA stage uses the bundled Node/KaTeX even though PATH has no project Node or node_modules.
            qa = call(op="check", pack="pack.phy.o", category="qa")
            assert qa["ok"], qa
            opened["record"]["solution"]["steps"][0]["latex"] = r"\notARealCommand{"
            call(op="save", **{k: v for k, v in opened.items() if k != "new"}, id=ITEM)
            rejected = call(op="check", pack="pack.phy.o", category="qa")
            assert not rejected["ok"] and any("does not render in KaTeX" in p for p in rejected["problems"]), rejected
            checks.append("bundled-katex-QA")
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        result = {
            "candidate_acceptance": False,
            "signed_installer": False,
            "backend": str(backend),
            "backend_sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
            "backend_bundle_sha256": bundle_hash(backend.parent),
            "tool_worker_bundle_sha256": bundle_hash(backend.parent.parent / "tool-worker"),
            "checks": checks,
            "fixture": "disposable fictional workspace; no learner profile or production account",
            "external": [
                "signed installers",
                "Windows and Linux packages",
                "native webview and assistive-technology matrix",
                "configured local-model and calibrated-judge evidence",
            ],
        }
        if out:
            out.write_text(json.dumps(result, indent=2) + "\n")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.backend, args.out), indent=2))
