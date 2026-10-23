"""PRV-29 all committed scenario/safety suites audit every actual scripted model request."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.harness.context import audit_requests
from jana_tools.scenarios import load_suite, run_scenario


def prv29_tutor_context_is_structured(tmp_path: Path) -> None:
    async def check() -> None:
        suites = [
            p
            for root in [REPO_ROOT / "evals/scenarios", REPO_ROOT / "evals/safety"]
            for p in sorted(root.glob("*.yaml"))
            if not p.name.endswith(".meta.yaml")
        ]
        assert len(suites) == 5
        gate = asyncio.Semaphore(3)
        rows: list[dict] = []

        async def scenario(path: Path, suite: str, case: dict) -> None:
            async with gate:
                result = await run_scenario(case, path.parent, build_stage="S2", suite=suite)
                audit = result.model_context
                rows.append(
                    {
                        "suite": suite,
                        "scenario": case["id"],
                        "status": result.status,
                        "reason": result.reason,
                        "audit": audit,
                    }
                )
                print(f"context {suite}/{case['id']}: {result.status}; {audit.get('requests', 0)} requests", flush=True)

        jobs = []
        for path in suites:
            data = load_suite(path)
            jobs += [scenario(path, data["suite"], case) for case in data["scenarios"]]
        await asyncio.gather(*jobs)
        (tmp_path / "model-context-evidence.json").write_text(json.dumps(rows, indent=2))
        assert len(rows) == 104
        assert not [(r["scenario"], r["reason"]) for r in rows if r["status"] == "failed"]
        print(
            "context totals:",
            len(rows),
            "cases;",
            sum(r["audit"].get("requests", 0) for r in rows),
            "requests",
            flush=True,
        )
        assert not [(r["scenario"], r["audit"]["failures"]) for r in rows if r["audit"].get("failures")]
        # A scenario that skips has made no request; all executed scenarios must carry audit evidence.
        assert all(r["audit"] or r["status"] == "skipped" for r in rows)
        assert sum(r["audit"].get("requests", 0) for r in rows) > 100

    asyncio.run(check())


def test_context_audit_rejects_external_or_unstructured_parts() -> None:
    good = {
        "_role": "coach",
        "messages": [{"role": "user", "content": "The student explicitly mentions a screenshot."}],
    }
    assert audit_requests([good])["failures"] == []
    for message in [
        {"role": "user", "content": b"screen pixels"},
        {"role": "user", "content": "hello", "screen": "foreign window"},
        {"role": "user", "content": [{"type": "screenshot", "pixels": "foreign window"}]},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://remote/image.jpg"}}]},
    ]:
        assert audit_requests([{**good, "messages": [message]}])["failures"]
