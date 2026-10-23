import shutil
from pathlib import Path

import pytest
from jana_tools import REPO_ROOT


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A copy of the repository's tracked and untracked (non-ignored) files, without docs/."""
    from jana_tools.repo import repo_paths

    dest = tmp_path / "repo"
    for rel in repo_paths(REPO_ROOT):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)
    return dest
