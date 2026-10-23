"""Version schemes per artefact and immutable versions (OPS-01).

Every shipped artefact carries a version in the form of its row in TABLE OPS-01a. The publish ledger (in the release
store, `JANA_RELEASE_STORE`) records the sha256 of every published artefact id and version: publishing the same id and
version again is allowed only with the same bytes. An app patch release never carries a data migration.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SEMVER = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
FORMS: dict[str, re.Pattern[str]] = {
    "app": re.compile(rf"^{SEMVER}(-rc\.[1-9]\d*)?$"),
    "agent_bundle": re.compile(rf"^{SEMVER}$"),
    "skill": re.compile(rf"^{SEMVER}$"),
    "content_pack": re.compile(rf"^{SEMVER}$"),
    "model_pack": re.compile(r"^[a-z0-9][a-z0-9._-]*@[1-9]\d*$"),  # model_pack_id@manifest_version
    "contract": re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
    "learner_database": re.compile(r"^[1-9]\d*$"),
    "safety_configuration": re.compile(r"^[1-9]\d*$"),
    "compatibility_matrix": re.compile(r"^[1-9]\d*$"),
    "usb_kit": re.compile(r"^kit-20\d\d\.[123]\.[1-9]\d*$"),
}


class ImmutableVersionError(ValueError):
    """The artefact id and version were published before with different bytes."""


def form_errors(kind: str, version: str) -> list[str]:
    pattern = FORMS.get(kind)
    if pattern is None:
        return [f"{kind}: not an artefact kind of TABLE OPS-01a"]
    return [] if pattern.match(version) else [f"{kind} version {version!r} is not in the form of TABLE OPS-01a"]


def store() -> Path:
    return Path(os.environ.get("JANA_RELEASE_STORE") or Path.home() / ".jana" / "releases")


class Ledger:
    def __init__(self, root: Path | None = None) -> None:
        self.path = (root or store()) / "ledger.json"

    def entries(self) -> dict[str, str]:
        return json.loads(self.path.read_text()) if self.path.is_file() else {}

    def publish(self, kind: str, artefact_id: str, version: str, sha256: str) -> bool:
        """Record a publication; True when new, False when the same bytes were published before."""
        if errors := form_errors(kind, version):
            raise ValueError(errors[0])
        entries = self.entries()
        key = f"{kind}:{artefact_id}@{version}"
        if key in entries:
            if entries[key] != sha256:
                raise ImmutableVersionError(f"{key} was published with different bytes ({entries[key][:12]}…); "
                                            "a changed artefact needs a new version (OPS-01)")  # fmt: skip
            return False
        entries[key] = sha256
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, indent=1, sort_keys=True) + "\n")
        return True


def _core(version: str) -> tuple[int, int, int]:
    match = re.match(SEMVER, version)
    if not match:
        raise ValueError(f"{version!r} is not SemVer")
    return int(match[1]), int(match[2]), int(match[3])


def patch_migration_errors(previous: str, candidate: str, previous_migrations: list[str],
                           candidate_migrations: list[str]) -> list[str]:  # fmt: skip
    """An app patch release (same major.minor) must not add or change a data migration (OPS-01, DAT-12)."""
    before, after = _core(previous), _core(candidate)
    if after[:2] != before[:2] or after == before:
        return []
    added = sorted(set(candidate_migrations) - set(previous_migrations))
    if added or len(candidate_migrations) != len(previous_migrations):
        return [f"app {candidate} is a patch of {previous} but carries data migration(s) {', '.join(added) or '?'}; "
                "a migration needs at least a minor version (OPS-01)"]  # fmt: skip
    return []


def current_migrations() -> list[str]:
    """The learner and device database migrations this build carries, by database and step."""
    import hashlib

    from agent_core.store.sqlite import MIGRATIONS

    out = []
    for database, steps in sorted(MIGRATIONS.items()):
        for step in steps:
            out.append(f"{database}:{step.version}:{hashlib.sha256(step.sql.encode()).hexdigest()[:12]}")
    return out
