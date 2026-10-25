"""Public synthetic parser fixtures. These are never release approvals or production inputs."""

import json
import shutil
import tempfile
from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures/governance"
_TEMP = tempfile.TemporaryDirectory(prefix="jana-synthetic-governance-")
GOVERNANCE_DOCS = Path(_TEMP.name) / "docs"
shutil.copytree(_FIXTURES, GOVERNANCE_DOCS)
_records = json.loads((_FIXTURES / "security-requirements.json").read_text())
_security = "".join(
    f"{'#' * 3} {row['id']} — {row['title']}\nStage: {row['stage']} · Priority: {row['priority']}\n{row['body']}"
    for row in _records
)
(GOVERNANCE_DOCS / "specification/security.md").write_text(_security)
