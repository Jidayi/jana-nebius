"""Model-in-the-loop answer oracles: the S1 gate "final answer correct, tool-checkable items" (EVL-02, TABLE EVL-17a)
and the per-role "structured output parses first time" count (MDL-15) from the same runs.

`python -m jana_tools eval oracles <url> <key> <model> <out dir> [--limit N] [--jobs N]` puts each bank item of the
S1 pack to the shipped engine as a new problem (the stem and the part's question) on one local model. The engine's
verified plan carries the final answer the tutor would lead the student to; it is marked against the item's key by
the same marker practice uses, with unit conversions done by the tool worker. A model never grades: a run with no
verified plan counts as wrong. Each item's trace is kept, and `report.json` holds:

- `final_answer`: passed and total over the items (the stage gate's `--oracles` input);
- `structured_first_pass`: model calls that needed no correction retry and were not cut off, in total and per role
  (the bake-off's MDL-15 measure; a tool call the host had to repair beyond id and normalisation counts against its
  turn as `tool_repairs`).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .. import REPO_ROOT

PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
BENIGN_REPAIRS = frozenset({"unique_id", "normalize"})


CORRECTIONS: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("corrections", default=None)


def _note_corrections(core: Any) -> None:
    """Record what each correction retry was for, per item (a context variable: items run concurrently)."""
    if getattr(core.correction, "noted", False):
        return
    correction = core.correction

    def noted(previous: str, errors: list[str]) -> Any:
        found = CORRECTIONS.get()
        if found is not None:
            found.append("; ".join(errors)[:300])
        return correction(previous, errors)

    noted.noted = True  # type: ignore[attr-defined]
    core.correction = noted


def statement(item: dict[str, Any], part_id: str = "a") -> str:
    part = next(p for p in item["parts"] if p["id"] == part_id)
    return f"{item['stem'].strip()} {part['prompt'].strip()}"


def structured(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """First-time structured output per role, from the turn traces."""
    roles: dict[str, list[int]] = {}
    repairs = 0
    for trace in traces:
        for call in trace.get("model_calls", []):
            ok = not call.get("correction_retry") and call.get("finish_reason") != "length"
            row = roles.setdefault(call["role"], [0, 0])
            row[0] += int(ok)
            row[1] += 1
        repairs += sum(bool(set(c.get("repairs", [])) - BENIGN_REPAIRS) for c in trace.get("tool_calls", []))
    passed, total = sum(r[0] for r in roles.values()), sum(r[1] for r in roles.values())
    return {"passed": passed, "total": total, "tool_repairs": repairs,
            "by_role": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(roles.items())}}  # fmt: skip


async def run_item(url: str, key: str, model: str, item: dict[str, Any], out: Path,
                   hardware_class: str = "mid") -> dict[str, Any]:  # fmt: skip
    from agent_core.engine.events import new_id
    from agent_core.engine.marking import Converted, mark
    from agent_core.router import core

    from ..live_session import open_engine

    engine, state, supervisor, provider = await open_engine(url, key, model, out, hardware_class=hardware_class)

    async def convert(quantity: str, to: str) -> Converted | None:
        done = await supervisor.call("units_convert", 1, {"quantity": quantity, "to": to}, new_id("chk"), 5000)
        value = ((done.result or {}).get("value") or {}).get("value") if done.ok else None
        decimal = value.get("decimal") if isinstance(value, dict) else None
        return Converted(Decimal(str(decimal)), done.result["check"]["check_id"]) if decimal is not None else None

    gaps: list[str] = []
    verify = engine._verified_plan
    corrections: list[str] = []
    _note_corrections(core)
    CORRECTIONS.set(corrections)

    def recorded(envelope: dict[str, Any]) -> Any:  # keep why each plan was refused, for the run's evidence
        plan, gap = verify(envelope)
        if plan is None:
            gaps.append(gap if envelope.get("schema_valid") else f"{gap}: {str(envelope.get('errors', ''))[:300]}")
        return plan, gap

    engine._verified_plan = recorded
    started = time.monotonic()
    row: dict[str, Any] = {"item": item["id"], "plan_verified": False, "answer": None, "outcome": "no_plan",
                           "plan_gaps": gaps, "corrections": corrections}  # fmt: skip
    try:
        result = await engine.start_problem(statement(item))
        row["seconds"] = round(time.monotonic() - started, 1)
        row["status"] = result.status
        if state.plan is not None:
            value, unit = state.plan.final_value.strip(), (state.plan.final_unit or "").strip()
            answer = value if not unit or value.endswith(unit) else f"{value} {unit}"  # a unit written twice
            verdict = await mark(item, "a", answer, convert, engine.deps.settings)
            row.update(plan_verified=True, answer=answer, outcome=verdict.outcome)
    except Exception as error:  # a crashed run counts as wrong, with its type recorded
        row.update(outcome="error", error=type(error).__name__)
    finally:
        await supervisor.close()
        await provider.close()
    row["structured"] = structured(engine.traces)
    out.mkdir(parents=True, exist_ok=True)
    (out / "traces.json").write_text(json.dumps(engine.traces, indent=1))
    return row


async def remark(rows: list[dict[str, Any]], items: dict[str, dict[str, Any]], scratch: Path) -> list[dict[str, Any]]:
    """Mark each kept answer again: a marker fix applies to every item of a run, not only to the ones still to run."""
    from agent_core.config import Settings
    from agent_core.engine.events import new_id
    from agent_core.engine.marking import Converted, mark
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))
    supervisor = WorkerSupervisor(process_factory(settings, scratch_root=scratch), settings)
    await supervisor.start()

    async def convert(quantity: str, to: str) -> Converted | None:
        done = await supervisor.call("units_convert", 1, {"quantity": quantity, "to": to}, new_id("chk"), 5000)
        value = ((done.result or {}).get("value") or {}).get("value") if done.ok else None
        decimal = value.get("decimal") if isinstance(value, dict) else None
        return Converted(Decimal(str(decimal)), done.result["check"]["check_id"]) if decimal is not None else None

    try:
        for row in rows:
            if row.get("answer") and row["item"] in items:
                row["outcome"] = (await mark(items[row["item"]], "a", row["answer"], convert, settings)).outcome
    finally:
        await supervisor.close()
    return rows


def committed_ids() -> set[str]:
    """Item ids committed to the repository. Held-out items are never committed (EVL-18), so a development run that
    takes only these can never read one, even while unsealed held-out files sit in the working tree."""
    import subprocess

    listed = subprocess.run(["git", "ls-files", str(PACK / "items")], cwd=REPO_ROOT, capture_output=True, text=True,
                            check=True).stdout.split()  # fmt: skip
    return {Path(name).stem for name in listed}


def bank_items(limit: int | None = None) -> list[dict[str, Any]]:
    from pack_builder.build import load_source

    committed = committed_ids()
    items = sorted((i for i in load_source(PACK).tables["items"] if i["id"] in committed), key=lambda i: i["id"])
    return items[:limit] if limit else items


def report(model: str, rows: list[dict[str, Any]], hardware_class: str = "mid") -> dict[str, Any]:
    traces = {"passed": 0, "total": 0, "tool_repairs": 0, "by_role": {}}  # type: dict[str, Any]
    for row in rows:
        s = row["structured"]
        traces["passed"] += s["passed"]
        traces["total"] += s["total"]
        traces["tool_repairs"] += s["tool_repairs"]
        for role, r in s["by_role"].items():
            mine = traces["by_role"].setdefault(role, {"passed": 0, "total": 0})
            mine["passed"] += r["passed"]
            mine["total"] += r["total"]
    seconds = sorted(r["seconds"] for r in rows if "seconds" in r)
    return {"model": model, "pack": "phy/o", "hardware_class": hardware_class,
            "final_answer": {"passed": sum(r["outcome"] == "correct" for r in rows), "total": len(rows)},
            "plans_verified": sum(r["plan_verified"] for r in rows), "structured_first_pass": traces,
            "first_turn_seconds_median": seconds[len(seconds) // 2] if seconds else None,
            "items": rows}  # fmt: skip


def run(url: str, key: str, model: str, out: Path, limit: int | None = None, jobs: int = 1,
        hardware_class: str = "mid") -> dict[str, Any]:  # fmt: skip
    items = bank_items(limit)
    done_dir = out / "items"
    rows: list[dict[str, Any]] = []
    for path in sorted(done_dir.glob("*.json")) if done_dir.is_dir() else []:  # resume an interrupted run
        rows.append(json.loads(path.read_text()))
    if rows:  # answers kept from an interrupted run are marked again with the current marker
        rows = asyncio.run(remark(rows, {i["id"]: i for i in items}, out / "scratch-remark"))
        for row in rows:
            (done_dir / f"{row['item']}.json").write_text(json.dumps(row, indent=1))
    finished = {r["item"] for r in rows}
    pending = [i for i in items if i["id"] not in finished]

    async def worker(queue: asyncio.Queue[dict[str, Any]]) -> None:
        while not queue.empty():
            item = queue.get_nowait()
            row = await run_item(url, key, model, item, out / "runs" / item["id"], hardware_class)
            done_dir.mkdir(parents=True, exist_ok=True)
            (done_dir / f"{item['id']}.json").write_text(json.dumps(row, indent=1))
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in ("item", "outcome", "answer", "seconds")}), flush=True)

    async def main() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for item in pending:
            queue.put_nowait(item)
        await asyncio.gather(*(worker(queue) for _ in range(max(1, jobs))))

    asyncio.run(main())
    wanted = {i["id"] for i in items}
    result = report(model, sorted((r for r in rows if r["item"] in wanted), key=lambda r: r["item"]), hardware_class)
    (out / "report.json").write_text(json.dumps(result, indent=1))
    return result
