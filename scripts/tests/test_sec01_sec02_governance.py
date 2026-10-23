"""SEC-01 threat model and SEC-02 boundary owners."""

import re
import shutil
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.governance import codeowners_errors, missing_approvals, owners_for, threat_model_errors
from jana_tools.spec import DOCS


def _docs_copy(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    for rel in ("specification/security.md", "specification/architecture.md", "implementation/threat-model.md"):
        (docs / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DOCS / rel, docs / rel)
    for rel in ("specification", "product"):
        (docs / rel).mkdir(parents=True, exist_ok=True)
        for path in (DOCS / rel).glob("*.md"):
            if not (docs / rel / path.name).exists():
                shutil.copy2(path, docs / rel / path.name)
    return docs


def sec01_threat_model_complete_and_current(tmp_path: Path):
    assert threat_model_errors() == []

    docs = _docs_copy(tmp_path)
    model = docs / "implementation" / "threat-model.md"
    text = model.read_text()
    row = re.search(r"^\| 13 \|.*$", text, re.MULTILINE)
    assert row
    cells = row[0].split(" | ")
    cells[4] = "ZZZ-99"  # a requirement that does not exist
    broken = text.replace(row[0], " | ".join(cells))
    broken = re.sub(r"^\| 18 \|.*\n", "", broken, flags=re.MULTILINE)
    broken = re.sub(r"^\| TB7 \|.*\n", "", broken, flags=re.MULTILINE)
    model.write_text(broken)
    assert threat_model_errors(docs) == [
        "threat 13 drops mitigations ['SEC-08']",
        "threat 18 of TABLE SEC-01a is missing from the threat model",
        "threat 13 has no existing mitigating requirement",
        "boundary TB7 has no owning role in the threat model",
    ]

    # A stage gate passed after the last review makes the model stale.
    model.write_text(text)
    (docs / "implementation" / "m9-acceptance.md").write_text(
        "# M9\n\nMilestone: M9 · Stage: S1 · Date: 2099-01-01 · Commit: x\nResult: accepted\n"
    )
    reviewed = re.search(r"Last reviewed: (\d{4}-\d{2}-\d{2})", text)  # as governance.threat_model_errors reads it
    assert reviewed, "the threat model states when it was last reviewed"
    assert threat_model_errors(docs) == [
        f"the threat model was last reviewed {reviewed[1]}, before the latest stage gate 2099-01-01"
    ]


def sec02_boundary_changes_need_owner_review(tmp_path: Path):
    assert codeowners_errors() == []
    codeowners = (REPO_ROOT / ".github" / "CODEOWNERS").read_text()

    tagged = "services/tool-worker/tool_worker/__init__.py"
    assert owners_for(tagged, codeowners) == ["@Jidayi"]
    assert missing_approvals([tagged], set(), codeowners) == [f"{tagged}: needs approval from @Jidayi"]
    assert missing_approvals([tagged], {"@someone-else"}, codeowners) != []
    assert missing_approvals([tagged], {"@Jidayi"}, codeowners) == []
    assert missing_approvals(["README.md"], set(), codeowners) == []  # untagged

    # Every boundary in ARC-03 tags files, and a hand edit to CODEOWNERS is detected.
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts" / "governance", root / "scripts" / "governance")
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(codeowners.replace("/services/tool-worker/ @Jidayi\n", ""))
    assert codeowners_errors(root) == [
        ".github/CODEOWNERS is stale; run: uv run python -m jana_tools codeowners --write"
    ]
    manifest = root / "scripts" / "governance" / "boundaries.toml"
    manifest.write_text(re.sub(r'\[\[boundary\]\]\nid = "TB6"\n[^\[]*', "", manifest.read_text()))
    assert codeowners_errors(root) == ["boundary TB6 tags no files"]

    workflow = (REPO_ROOT / ".github" / "workflows" / "boundary-review.yml").read_text()
    assert "jana_tools boundary-review" in workflow
