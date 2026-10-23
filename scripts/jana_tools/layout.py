"""ARC-16 layout check: every top-level directory, and every directory under apps/,
packages/, services/, content/ and skills/, must be one the layout table allows."""

from __future__ import annotations

TOP_LEVEL = frozenset({"apps", "packages", "services", "content", "skills", "evals", "docs", "scripts", "assets"})
# Hidden directories that are repository infrastructure rather than product code.
HIDDEN_TOP_LEVEL = frozenset({".github"})

SECOND_LEVEL: dict[str, frozenset[str]] = {
    "apps": frozenset({"desktop", "prototype-s0", "web", "android", "studio"}),
    "packages": frozenset({"ui", "client-core", "renderers", "contracts-ts", "i18n"}),
    "services": frozenset(
        {
            "agent-core",
            "tool-worker",
            "pack-builder",
            # D41 (proposed); listed in plan section 3 and ARC-18, missing from ARC-16 (see gaps.md).
            "perception-worker",
            "study-worker",
            "cloud-gateway",
            "school-server",
            "licensing",
            "update-index",
            "ingest",
            "backup",
            "multi-device",
            "parent-view",
            "voice-gateway",
            "signing-service",
        }
    ),
    "content": frozenset({"agent", "curriculum"}),
    "skills": frozenset({"pedagogy", "teaching", "agent"}),
}


def layout_errors(paths: list[str]) -> list[str]:
    """Return one message per directory the layout does not allow."""
    errors: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) < 2:
            continue  # a file at the root
        top = parts[0]
        if top not in TOP_LEVEL and top not in HIDDEN_TOP_LEVEL:
            errors.add(f"unknown top-level directory: {top}/")
            continue
        allowed = SECOND_LEVEL.get(top)
        if allowed is not None and len(parts) >= 3 and parts[1] not in allowed:
            errors.add(f"unknown directory: {top}/{parts[1]}/")
    return sorted(errors)
