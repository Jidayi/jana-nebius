"""Verify mastery lifecycles against installed development packs in isolated learner stores.

Usage: python -m jana_tools.mastery_verification PACK_DIRECTORY OUTPUT_DIRECTORY [--kc KC_ID]

Answers come from the verified pack keys; ordinary marking uses the app's real sandboxed worker.
A controlled clock exercises the 24-hour boundary without changing production defaults or a user's profile.
Insufficient banks are reported separately and must stay waiting, unseen and unlocked. This is software
verification, not curriculum review, model qualification, hardware acceptance or release signing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.engine.assembly import AppRuntime, start_worker_pool
from agent_core.engine.assessment.errors import Refused
from agent_core.engine.assessment.service import AssessmentDesk
from agent_core.engine.learn import SUBJECT_NAMES
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database

from jana_tools import REPO_ROOT


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000_000

    def read(self) -> int:
        return self.now


def locked(desk: AssessmentDesk, expected: bool) -> None:
    try:
        desk.guard_tutor()
    except Refused as error:
        assert expected and str(error) == "tutor_locked"
    else:
        assert not expected, "tutor must stay locked while an exposed question is active"


def key_answer(item: dict[str, Any]) -> dict[str, Any]:
    parts = []
    for part in item["parts"]:
        key = part["answer"]
        kind = key["kind"]
        typed = {"part_id": part["id"], "kind": kind}
        if kind == "numeric":
            typed.update(value=key["value"], unit=key["unit"])
        elif kind == "mcq":
            typed["option_id"] = next(o["id"] for o in key["options"] if o["correct"])
        elif kind == "multi_select":
            typed["option_ids"] = [o["id"] for o in key["options"] if o["correct"]]
        elif kind == "ordering":
            typed["element_ids"] = key["correct_order"]
        elif kind == "algebraic":
            typed["latex"] = key["expression"]
        elif kind == "equation_solutions":
            typed["values"] = key["values"]
        else:
            raise AssertionError(f"unhandled installed answer kind: {kind}")
        parts.append(typed)
    return {"parts": parts}


def reopen(desk: AssessmentDesk, clock: Clock) -> AssessmentDesk:
    return AssessmentDesk(
        desk.learner,
        desk.content,
        desk.settings,
        clock_ms=clock.read,
        monotonic_ms=clock.read,
        run_tool=desk.run_tool,
        recover=True,
    )


async def case(desk: AssessmentDesk, clock: Clock, kc: str) -> dict[str, Any]:
    subject = SUBJECT_NAMES[kc.split(".")[1]]
    bank = desk.eligible("mastery_check", [kc], subject)
    distinct = {desk._surface(i) for i in bank}
    row: dict[str, Any] = {
        "subject": subject,
        "kc_id": kc,
        "eligible_items": len(bank),
        "distinct_surfaces": len(distinct),
        "answers": [],
    }
    state = desk.start_assessment("mastery_check", subject, kc)
    identity = state["assessment_id"]
    if len(distinct) < 3:
        assert state["state"] == "waiting" and state["current_item"] is None and state["answered_count"] == 0
        assert not any(e.type in ("item_exposed", "mastery_check", "attempt") for e in desk.learner.log.by_seq())
        locked(desk, False)
        assert desk.stop_assessment(identity)["current_item"] is None
        desk = reopen(desk, clock)
        assert desk.resume_assessment(identity)["current_item"] is None
        locked(desk, False)
        row["status"] = "content_bank_incomplete_safely_waiting"
        return row
    selected = []
    surfaces = []
    reserved = desk._reserved()
    for n in range(3):
        assert state["state"] == "in_progress" and state["answered_count"] == n
        item_id = state["current_item"]["item_id"]
        item = desk._get(identity)["selected"][item_id]
        assert kc in item["kc_ids"] and item_id.startswith("itm." + kc.split(".")[1] + ".")
        assert item_id not in reserved and item_id not in selected
        surface = desk._surface(item)
        assert surface not in surfaces
        selected.append(item_id)
        surfaces.append(surface)
        locked(desk, True)
        if n == 0:
            assert desk.stop_assessment(identity)["current_item"]["item_id"] == item_id
            locked(desk, True)
            desk = reopen(desk, clock)
            assert desk.resume_assessment(identity)["current_item"]["item_id"] == item_id
        state = await desk.assessment_answer(identity, f"answer-{n}", item_id, key_answer(item))
        assert state["last_mark"]["verdict"] == "correct", state["last_mark"]
        row["answers"].append({"item_id": item_id, "kind": item["type"], "mark": state["last_mark"]})
        if n == 0:
            desk = reopen(desk, clock)
            state = desk.assessment(identity)
        elif n == 1:
            assert state["state"] == "waiting" and state["current_item"] is None
            locked(desk, False)
            first = desk._get(identity)["first_served"]
            clock.now = first + 24 * 3_600_000 - 1
            assert desk.assessment(identity)["current_item"] is None
            clock.now += 1
            # Passive list refresh and stop must not serve a due question or suddenly lock tutoring.
            assert desk.list_assessments()[0]["current_item"] is None
            assert desk.stop_assessment(identity)["current_item"] is None
            locked(desk, False)
            desk = reopen(desk, clock)
            state = desk.resume_assessment(identity)
    assert state["state"] == "completed" and state["answered_count"] == 3 and state["current_item"] is None
    assert desk.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id=?", (kc,)).fetchone()[0] == "mastered"
    desk = reopen(desk, clock)
    assert desk.assessment(identity)["state"] == "completed"
    locked(desk, False)
    row["status"] = "three_correct_spaced_complete_unlocked"
    return row


async def verify(packs: Path, output: Path, only: str | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(packs.glob("*.pack"))
    index = PackIndex.load(paths, Environment.DEV)
    assert paths and not index.rejected, index.rejected
    assert only is None or only in index.kcs, "requested KC is not installed"
    rows = []
    calls = []
    settings = Settings(worker_pool_size=1)
    with tempfile.TemporaryDirectory(prefix="jana-mastery-all-") as scratch:
        root = Path(scratch)
        runtime = AppRuntime(settings, REPO_ROOT / "content/agent", REPO_ROOT / "skills", root / "runtime")
        runtime.supervisor = await start_worker_pool(settings, root / "scratch")
        assert runtime.supervisor.compute_available(), "real worker must be available"
        assert not runtime.supervisor.reduced_protection, "this verification requires the worker's OS sandbox"

        async def tool(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
            value, check = await runtime._lesson_tool(name, args)
            calls.append({"name": name, "check_id": check, "ok": value is not None and check is not None})
            return value, check

        try:
            for number, kc in enumerate(sorted(index.kcs)):
                if only is not None and only != kc:
                    continue
                folder = root / str(number)
                folder.mkdir()
                conn, _ = open_database(folder / "learner.db", "learner")
                clock = Clock()
                learner = Learner.open(
                    conn,
                    profile_id="0" * 26,
                    device_id="f" * 32,
                    wall_ms=clock.read,
                    max_skew_ms=settings.sync_clock_skew_max_ms,
                    params=MasteryParams.from_settings(settings),
                    content=index,
                )
                desk = AssessmentDesk(
                    learner, index, settings, clock_ms=clock.read, monotonic_ms=clock.read, run_tool=tool
                )
                try:
                    row = await case(desk, clock, kc)
                except Exception:
                    row = {
                        "subject": SUBJECT_NAMES[kc.split(".")[1]],
                        "kc_id": kc,
                        "status": "software_or_marker_failure",
                        "error": traceback.format_exc(),
                    }
                finally:
                    conn.close()
                rows.append(row)
                with (output / "cases.jsonl").open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
                print(json.dumps({"kc_id": kc, "status": row["status"]}), flush=True)
        finally:
            await runtime.supervisor.close()
    summary = {
        "scope": (
            "Installed development packs; isolated learner stores, actual marking and sandboxed worker, "
            "controlled 24-hour clock"
        ),
        "installed_packs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "subjects": {
            subject: dict(Counter(r["status"] for r in rows if r["subject"] == subject))
            for subject in sorted({r["subject"] for r in rows})
        },
        "total_kcs": len(rows),
        "question_marks": sum(len(r.get("answers", [])) for r in rows),
        "worker_calls": len(calls),
        "worker_failures": sum(not c["ok"] for c in calls),
        "software_failures": [r for r in rows if r["status"] == "software_or_marker_failure"],
        "content_bank_gaps": [r for r in rows if r["status"] == "content_bank_incomplete_safely_waiting"],
        "production_spacing_hours": settings.mastery_check_min_spacing_hours,
        "live_profile_modified": False,
        "separate_requirements": [
            "hardware acceptance",
            "model qualification",
            "release signing",
            "independent curriculum and release review",
        ],
    }
    (output / "worker-calls.json").write_text(json.dumps(calls, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--kc")
    args = parser.parse_args()
    # Every run gets a fresh case log; keep the installed packs and learner profiles read-only.
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "cases.jsonl").write_text("")
    summary = asyncio.run(verify(args.packs, args.output, args.kc))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("content_bank_gaps", "installed_packs")}))
    return int(bool(summary["software_failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
