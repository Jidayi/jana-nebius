"""Full synthetic development corpus through real gateway and core stores; opt-in real provider only.

Results are not an independent content review or evidence of a reference-device local model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_core.config import Settings
from agent_core.engine.study import StudyDesk
from agent_core.store.sqlite import open_database
from cloud_gateway.app import create_app
from cloud_gateway.config import load_config
from cloud_gateway.providers.base import Usage
from cloud_gateway.quotas import cost_usd
from gateway_stubs import AUDIENCE, Device, licence_keys
from test_m19_gw_live import _owner_secrets

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "evals/study/m42-quality.json"
LIVE = os.environ.get("JANA_M42_QUALITY_LIVE") == "1"
SKIP_REASON = "Opt-in synthetic provider corpus: set JANA_M42_QUALITY_LIVE=1 with the existing owner secret source."


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_m42_quality_corpus_inventory():
    corpus = json.loads(CORPUS.read_text())
    cases = corpus["cases"]
    assert corpus["synthetic"] and len(cases) >= 100
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(re.fullmatch(r"[a-z0-9-]+", c["id"]) for c in cases)
    assert {c["kind"] for c in cases} == set(corpus["kinds"])
    for subject in ("biology", "chemistry", "mathematics", "physics", "accounting", "outside-syllabus"):
        assert {c["kind"] for c in cases if c["subject"] == subject} == set(corpus["kinds"])
    assert sum(c["expected"] == "insufficient_evidence" for c in cases) >= 10


def test_probability_regressions_preserve_original_observations_and_contrast_missing_premises():
    previous = json.loads((CORPUS.parent / "history/m42-quality-v2.json").read_text())
    current = json.loads((CORPUS.parent / "history/m42-quality-v3.json").read_text())
    original = {c["id"]: c for c in previous["cases"]}
    cases = {c["id"]: c for c in current["cases"]}
    assert current["version"] == 3 and len(cases) == len(original) + 4
    assert all(cases[key] == case for key, case in original.items() if key != "mth-probability-chat")
    assert cases["mth-probability-chat"] == {**original["mth-probability-chat"], "expected": "insufficient_evidence"}
    assert cases["mth-probability-stated-conditions-chat"]["sources"] == original["mth-probability-chat"]["sources"]
    assert cases["mth-probability-stated-conditions-chat"]["expected"] == "grounded"
    assert cases["mth-probability-explicit-explanation-chat"]["expected"] == "grounded"
    for key in ("mth-probability-missing-draw-rule-chat", "mth-probability-contradictory-draw-rule-chat"):
        assert cases[key]["expected"] == "insufficient_evidence"


def test_unicode_speed_fixture_defines_the_requested_quantity_and_retains_missing_definition_contrasts():
    previous = json.loads((CORPUS.parent / "history/m42-quality-v3.json").read_text())
    current = json.loads(CORPUS.read_text())
    old = {c["id"]: c for c in previous["cases"]}
    new = {c["id"]: c for c in current["cases"]}
    assert current["version"] == 4 and len(new) == len(old) + 3
    changed = {key for key in old if new[key] != old[key]}
    assert changed == {f"unicode-{kind.replace('_', '-')}" for kind in current["kinds"]}
    for key in changed:
        assert {k: v for k, v in new[key].items() if k != "sources"} == {
            k: v for k, v in old[key].items() if k != "sources"
        }
        assert "distance travelled" in new[key]["sources"][0]
        assert "defines the average speed v" in new[key]["sources"][0]
    for key in ("undefined-v-speed-chat", "undefined-v-value-chat", "undefined-v-flashcards"):
        assert new[key]["sources"] == old["unicode-chat"]["sources"]
    assert new["undefined-v-speed-chat"]["prompt"] == old["unicode-chat"]["prompt"]
    assert new["undefined-v-speed-chat"]["expected"] == "insufficient_evidence"
    assert new["undefined-v-value-chat"]["expected"] == new["undefined-v-flashcards"]["expected"] == "grounded"


@pytest.mark.skipif(not LIVE, reason=SKIP_REASON)
def test_m42_full_live_quality_corpus(tmp_path):
    async def run():
        corpus = json.loads(CORPUS.read_text())
        destination = Path(os.environ.get("JANA_M42_QUALITY_REPORT", str(tmp_path / "quality.json")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        config = load_config(
            environment="staging",
            audience_host=AUDIENCE,
            storage_dir=tmp_path / "gateway",
            entitlement_keys=licence_keys(),
            study_model="primary/fast-model",
        )
        app = create_app(config, secrets=_owner_secrets())
        selected_id = os.environ.get("JANA_M42_QUALITY_CASE")
        cases = [c for c in corpus["cases"] if not selected_id or c["id"] == selected_id]
        assert cases
        active: ContextVar[str] = ContextVar("m42_synthetic_case")
        traces: dict[str, list[Any]] = {}
        if os.environ.get("JANA_M42_QUALITY_TRACE") == "1":
            # Synthetic eval only. Production adapters never log material or model responses.
            adapter = app.state.gateway.providers.adapters["gemini"]
            complete = adapter.complete

            async def capture(request):
                reply = await complete(request)
                traces.setdefault(active.get(), []).append(reply.body)
                return reply

            adapter.complete = capture

        model = app.state.gateway.providers.resolve(config.study_model)[2]
        assert model.id == "gemini-3.8-flash"
        report: dict[str, Any] = {
            "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "model": model.id,
            "provider": "real",
            "gateway": "in-process staging",
            "synthetic": True,
            "full_corpus": selected_id is None,
            "independent_content_review": False,
            "max_usd": 2,
            "cases": [],
        }
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for case in cases:
            queue.put_nowait(case)
        budget = asyncio.Lock()

        def checkpoint():
            rows = app.state.gateway.store._db.execute(
                "SELECT coalesce(sum(actual_usd),0),coalesce(sum(reserved_usd),0) FROM study_receipts"
            ).fetchone()
            report.update(actual_usd=rows[0], held_usd=rows[1], complete=len(report["cases"]) == len(cases))
            pending = destination.with_suffix(".pending")
            pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            pending.replace(destination)

        async def worker(index: int):
            conn, _ = open_database(tmp_path / f"learner-{index}.sqlite3", "learner")
            desk = StudyDesk(conn, lambda: int(time.time() * 1000), Settings())
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=f"https://{AUDIENCE}", timeout=240
            ) as client:
                device = Device()
                while not queue.empty():
                    case = queue.get_nowait()
                    active.set(case["id"])
                    started = time.monotonic()
                    row: dict[str, Any] = {
                        "id": case["id"],
                        "kind": case["kind"],
                        "subject": case["subject"],
                        "expected": case["expected"],
                        "passed": False,
                    }
                    jid = ""
                    try:
                        await device.login(client)
                        sources = [
                            desk.create({"kind": "text", "title": case["title"], "text": text})
                            for text in case["sources"]
                        ]
                        selections = [{"source_id": s["source_id"], "revision": 1} for s in sources]
                        request = {"kind": case["kind"], "sources": selections, "execution": "prefer_cloud"}
                        if case["prompt"] is not None:
                            request["prompt"] = case["prompt"]
                        if case["kind"] in ("quiz", "flashcards"):
                            request["count"] = 2
                        job = desk.create_job(request)
                        jid = job["job_id"]
                        job["state"] = "running"
                        desk.save_job(job)
                        chunks = desk.selected(selections)
                        body = {k: v for k, v in request.items() if k not in ("sources", "execution")}
                        body.update(request_id=jid, chunks=chunks, output_locale="en")
                        bound = cost_usd(
                            config.prices[model.id], Usage(2 * (len(json.dumps(body).encode()) + 32000) + 32768, 32768)
                        )
                        # Reserve against one global test-spend ceiling, including unknown-outcome holds.
                        async with budget:
                            totals = app.state.gateway.store._db.execute(
                                "SELECT coalesce(sum(actual_usd+reserved_usd),0) FROM study_receipts"
                            ).fetchone()[0]
                            if totals + 2 * bound > report["max_usd"]:
                                raise RuntimeError("global_test_budget_exhausted")
                        result = await client.post("/v1/study/process", json=body, headers=device.headers())
                        row["http_status"] = result.status_code
                        output = result.json()
                        row["response"] = output
                        if case["expected"] == "insufficient_evidence":
                            assert result.status_code == 422 and output["error"]["code"] == "insufficient_evidence"
                        else:
                            assert result.status_code == 200, output.get("error", {}).get("code")
                            groups = (
                                len(output["claims"])
                                + len(output.get("flashcards", []))
                                + len(output.get("quiz", {}).get("items", []))
                            )
                            aid = desk.commit_aid(job, output, [True] * groups)
                            assert aid["status"] == "ready" and aid["sources"] == selections
                            for value in walk(output):
                                for citation in value.get("citations", []):
                                    chunk = next(c for c in chunks if c["chunk_id"] == citation["chunk_id"])
                                    assert chunk["text"][citation["start"] : citation["end"]] == citation["quote"]
                            text = " ".join(str(v.get("text", "")) for v in walk(output)).lower()
                            assert any(concept.lower() in text for concept in case["concepts"])
                            for forbidden in case.get("forbidden", []):
                                assert forbidden.lower() not in json.dumps(output).lower()
                            if aid.get("quiz_id"):
                                student = desk.quiz(aid["quiz_id"])["view"]
                                assert "keys" not in student and all("explanation" not in i for i in student["items"])
                        row["passed"] = True
                    except Exception as error:
                        row["failure"] = type(error).__name__ + ": " + str(error)[:200]
                    finally:
                        if jid:
                            cleanup = await client.delete("/v1/study/requests/" + jid, headers=device.headers())
                            row["cleanup_ack"] = cleanup.status_code == 204
                            row["passed"] = row["passed"] and row["cleanup_ack"]
                            if desk.job(jid)["state"] == "running":
                                job = desk.job(jid)
                                job.update(state="failed", error="insufficient_evidence")
                                desk.save_job(job)
                        if case["id"] in traces:
                            row["synthetic_provider_trace"] = traces[case["id"]]
                        row["elapsed_s"] = round(time.monotonic() - started, 3)
                        report["cases"].append(row)
                        checkpoint()
                        print(
                            f"M42 quality {len(report['cases'])}/{len(corpus['cases'])}: {case['id']} "
                            f"{'PASS' if row['passed'] else 'FAIL'}",
                            flush=True,
                        )
                assert conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
                conn.close()

        await asyncio.gather(worker(0), worker(1))
        assert not app.state.study.buffers
        report["passed"] = all(c["passed"] for c in report["cases"]) and report["complete"]
        report["source_bodies_persisted_in_gateway"] = False
        for path in (tmp_path / "gateway").rglob("*"):
            if path.is_file():
                raw = path.read_bytes()
                for case in corpus["cases"]:
                    for text in case["sources"]:
                        assert text.encode() not in raw, "Source content persisted in gateway storage"
        checkpoint()
        assert report["passed"], [c["id"] for c in report["cases"] if not c["passed"]]

    asyncio.run(run())
