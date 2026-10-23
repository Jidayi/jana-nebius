"""ARC-16: monorepo layout and the private, pinned specification."""

import shutil
import subprocess
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.layout import layout_errors
from jana_tools.repo import repo_paths
from jana_tools.spec_lock import spec_lock_errors
from jana_tools.testing import git

GUARD = REPO_ROOT / "scripts" / "git-hooks" / "check-no-spec.sh"


def arc16_repository_layout_check(repo_copy: Path):
    assert layout_errors(repo_paths(REPO_ROOT)) == []

    (repo_copy / "misc").mkdir()
    (repo_copy / "misc" / "notes.txt").write_text("x")
    (repo_copy / "services" / "chat-bot").mkdir()
    (repo_copy / "services" / "chat-bot" / "main.py").write_text("")
    subprocess.run(["git", "init", "-q"], cwd=repo_copy, check=True)
    assert layout_errors(repo_paths(repo_copy)) == [
        "unknown directory: services/chat-bot/",
        "unknown top-level directory: misc/",
    ]


def test_linked_spec_checkout_reads_as_the_ignored_directory(tmp_path: Path):
    """A worktree links the spec at docs/ (and may link installed node_modules): an untracked link to a directory is
    left out as the ignored directory is, while a tracked file and a link to a file stay listed."""
    repo = tmp_path / "repo"
    (repo / "services").mkdir(parents=True)
    (repo / ".gitignore").write_text("docs/\nnode_modules/\n")
    (repo / "services" / "a.py").write_text("")
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "x.md").write_text("notes\n")
    (repo / "docs").symlink_to(spec, target_is_directory=True)
    (repo / "node_modules").symlink_to(spec, target_is_directory=True)
    (repo / "notes.txt").symlink_to(repo / "services" / "a.py")
    git(repo, "init", "-q")
    assert repo_paths(repo) == [".gitignore", "notes.txt", "services/a.py"]


def _spec_heading() -> str:
    # Built at run time so this file never contains specification text itself.
    return "#" * 3 + " ARC-99 — Example requirement\n"


def _guard_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "guarded"
    (repo / "scripts" / "git-hooks").mkdir(parents=True)
    shutil.copy2(GUARD, repo / "scripts" / "git-hooks" / "check-no-spec.sh")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "guard")
    return repo


def _guard(repo: Path, *mode: str) -> int:
    return subprocess.run(["sh", "scripts/git-hooks/check-no-spec.sh", *mode], cwd=repo, capture_output=True).returncode


def _fake_spec(tmp_path: Path, verify_exit: int) -> tuple[Path, str]:
    docs = tmp_path / "docs"
    (docs / "tools").mkdir(parents=True)
    (docs / "tools" / "verify_spec.py").write_text(f"import sys\nsys.exit({verify_exit})\n")
    git(docs, "init", "-q")
    git(docs, "add", ".")
    git(docs, "commit", "-qm", "spec")
    return docs, git(docs, "rev-parse", "HEAD").stdout.strip()


def arc16_spec_private_and_pinned(tmp_path: Path):
    # 1. The guard rejects a docs/ path and specification text, staged or in the tree.
    repo = _guard_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_text("notes\n")
    git(repo, "add", "-f", "docs/x.md")
    assert _guard(repo, "staged") != 0
    git(repo, "rm", "-q", "--cached", "docs/x.md")
    shutil.rmtree(repo / "docs")
    (repo / "notes.md").write_text(_spec_heading())
    git(repo, "add", "notes.md")
    assert _guard(repo, "staged") != 0
    git(repo, "commit", "-qm", "leak", "--no-verify")
    assert _guard(repo, "tree") != 0
    assert _guard(repo, "range", "HEAD~1..HEAD") != 0
    (repo / "notes.md").write_text("clean\n")
    git(repo, "commit", "-qam", "clean", "--no-verify")
    assert _guard(repo, "staged") == 0

    # 2. CI runs the guard over the whole tree.
    workflows = "\n".join(p.read_text() for p in (REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert "check-no-spec.sh tree" in workflows

    # 3. spec.lock must resolve to a specification checkout that passes verify_spec.py.
    root = tmp_path / "mono"
    root.mkdir()
    docs, head = _fake_spec(tmp_path / "good", verify_exit=0)
    (root / "spec.lock").write_text(head + "\n")
    assert spec_lock_errors(root, docs) == []
    verifier = docs / "tools" / "verify_spec.py"
    original = verifier.read_text()
    verifier.write_text(original + "\n# Unpinned change\n")
    assert "uncommitted changes" in spec_lock_errors(root, docs)[0]
    git(docs, "add", ".")
    assert "uncommitted changes" in spec_lock_errors(root, docs)[0]
    git(docs, "reset", "--hard", "HEAD")
    draft = docs / "new-contract.json"
    draft.write_text("{}")
    assert "uncommitted changes" in spec_lock_errors(root, docs)[0]
    draft.unlink()
    assert spec_lock_errors(root, docs) == []
    (root / "spec.lock").write_text("0" * 40 + "\n")
    assert "pins" in spec_lock_errors(root, docs)[0]
    (root / "spec.lock").write_text("main\n")
    assert spec_lock_errors(root, docs) == ["spec.lock must hold exactly one 40-character commit hash"]
    bad_docs, bad_head = _fake_spec(tmp_path / "bad", verify_exit=1)
    (root / "spec.lock").write_text(bad_head + "\n")
    assert spec_lock_errors(root, bad_docs)[0] == "the pinned specification fails verify_spec.py"
    (root / "spec.lock").unlink()
    assert spec_lock_errors(root, docs) == ["spec.lock is missing"]
