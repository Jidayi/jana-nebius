"""`python -m jana_tools evidence remark`: the learner replay of the wrong-key drill (OPS-27, CUR-36, ASM-23).

Runs on a staging test device's data folder, with the app closed: every learner database there has the attempts at
the withdrawn item re-marked against the installed correction by the device's own marker, and its learner model
rebuilt from its log (`AppRuntime.remark_withdrawn`). Nothing leaves the device. The printed numbers are what the
`wrong-key` checklist asks for; keep the printed JSON (`--out`) as a proof of the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from .. import REPO_ROOT


async def _remark(data: Path, old: str, new: str, *, release: bool) -> list[dict[str, Any]]:
    from agent_core.api.core import SERVER_VERSION
    from agent_core.config.resolve import app_settings
    from agent_core.engine.assembly import AppRuntime, start_worker_pool

    settings = app_settings("release" if release else "development")
    runtime = AppRuntime(settings, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", data, release=release)
    runtime.supervisor = await start_worker_pool(settings, data / "scratch")
    try:
        runtime.open_stores(SERVER_VERSION)
        return [report.as_dict() for report in await runtime.remark_withdrawn(old, new)]
    finally:
        await runtime.close()


def summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """The device's totals in the checklist's terms: one hash over every learner database's original evidence, in
    the order the databases were re-marked."""

    def joined(key: str) -> str:
        return hashlib.sha256("\n".join(r[key] for r in reports).encode()).hexdigest()

    return {
        "learner_databases": len(reports),
        "affected_attempts": sum(r["affected_attempts"] for r in reports),
        "remarked_attempts": sum(r["remarked_attempts"] for r in reports),
        "appended_verdicts": sum(r["appended"] for r in reports),
        "changed_results": sum(r["changed_results"] for r in reports),
        "original_attempts_sha256": joined("original_sha256"),
        "retained_attempts_sha256": joined("retained_sha256"),
        "projections_equal_full_replay": all(r["projections_equal_full_replay"] for r in reports),
    }


def run(data: Path, old: str, new: str, *, release: bool, out: Path | None = None) -> dict[str, Any]:
    if not (data / "device.db").is_file():
        raise ValueError(f"{data} is not an app data folder (no device.db); close the app and give its data folder")
    reports = asyncio.run(_remark(data, old, new, release=release))
    result = {"old_item_id": old, "new_item_id": new, "device": summary(reports), "learner_databases": reports}
    if out is not None:
        out.write_text(json.dumps(result, indent=2) + "\n")
    return result
