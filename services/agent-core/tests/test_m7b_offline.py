"""M7.b: offline-only runs (EVL-16). The harness's egress monitor, a cloud-tier session whose network is cut mid-turn,
and the content-only class with no model and no network. Items, learners and replies are synthetic."""

import asyncio
import json
import socket
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine.marking import Converted, mark
from agent_core.providers.scripted import ScriptedProvider, default_capabilities
from agent_core.store.packs import read_pack
from agent_core.trace.ids import new_ulid
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.harness import report as rep
from jana_tools.harness.egress import EgressRefusedError, offline_run
from jana_tools.harness.gate import gate_errors
from learner_harness import Clock, make_learner

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
TEST_NET = "192.0.2.10"  # RFC 5737 documentation range: never routed


def run(coro):
    return LOOP.run_until_complete(coro)


def evl16_offline_run_no_egress(tmp_path: Path) -> None:
    with offline_run() as egress:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s, pytest.raises(EgressRefusedError):
            s.connect((TEST_NET, 443))
        with pytest.raises(EgressRefusedError):
            socket.getaddrinfo("example.com", 443)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, pytest.raises(EgressRefusedError):
            s.sendto(b"x", (TEST_NET, 53))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:  # loopback stays available
            server.bind(("127.0.0.1", 0))
            server.listen()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect(server.getsockname())
    assert len(egress.attempts) == 3
    assert socket.socket.connect.__qualname__ == "socket.connect", "the monitor restores the socket afterwards"

    # A run with a detected outbound connection is invalid, and no gate is reported from it.
    report = {"report_version": 1, "run_id": "evr_test_egress", "mode": "development",
              "created_at": "2026-10-09T00:00:00Z", "build": {"app_version": "0", "commit": "x", "stage": "S1"},
              "models": [], "fingerprints": {"prompts": {}, "skills": {}},
              "hardware": {"hardware_class": "mid", "os": "linux", "arch": "x86_64", "ram_gb": 16},
              "network": {"state": "disabled", "egress_attempts": len(egress.attempts)}, "seeds": [0],
              "suites": {}, "cases": [], "diff": {"against": None}, "valid": False,
              "invalid_reasons": [f"egress attempt during an offline run: {a}" for a in egress.attempts],
              "eval_only_paths": []}  # fmt: skip
    assert rep.errors(report) == []
    errors = gate_errors(report)
    assert any("outbound connection attempt" in e for e in errors)
    assert any("egress attempt during an offline run: connect" in e for e in errors)


def evl16_network_cut_degrades(tmp_path: Path) -> None:
    """The cloud tier serves the Coach until the network is cut in the middle of a turn: the regeneration the leak gate
    asks for falls back to the local model and the session carries on."""
    served = {"n": 0}
    leak = tutor("It rises 10 m. Which equation did you use?", hint_rung=1)

    def cloud_step(model, messages, body):
        served["n"] += 1
        if served["n"] <= 2:
            return tutor(SAFE)
        if served["n"] == 3:
            return leak  # the gate rejects it and asks for one regeneration...
        return {"transport": "connect"}  # ...which meets the cut network

    cloud = ScriptedProvider(cloud_step, kind="cloud", caps={"fast-model": default_capabilities("cloud", 32768)})

    def enable(data):
        data["cloud"]["enabled"] = True
        data["roles"]["coach"]["prefer"] = "cloud"

    local_coach = [tutor(SAFE, hint_rung=1), tutor("Good. Which equation links u, v, a and s?")]
    with offline_run() as egress:
        engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                               "coach": local_coach}, overrides=enable, cloud=cloud))  # fmt: skip
        engine.deps.router.cloud_on = lambda role: role == "coach"
        run(engine.start_problem(STATEMENT))
        run(engine.student_turn("s = 3 m"))
        cut = run(engine.student_turn("I'm stuck"))
        after = run(engine.student_turn("s = 12 m"))
        run(close(engine))
    assert egress.attempts == []
    coach = [c for c in cut.trace["model_calls"] if c["role"] == "coach"]
    kinds = [c["provider_kind"] for c in coach]
    assert kinds[:2] == ["cloud", "cloud"] and kinds[-1] == "local", kinds
    assert coach[1]["reason"] == "network_unavailable"
    assert coach[-1]["fallback_from"].startswith("cloud:")
    assert cut.status == "complete" and "10 m" not in (cut.tutor_turn or {}).get("say", "")
    assert after.status == "complete", "the session is not interrupted"
    later = [c["provider_kind"] for c in after.trace["model_calls"] if c["role"] == "coach"]
    assert later[-1] == "local"


async def _convert(quantity: str, to: str) -> Converted | None:
    from tool_worker.functions.units import units_convert
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    context = CallContext("t", "chk_offline_units", {}, {}, lambda: False, settings={})
    try:
        value, _ = units_convert({"quantity": quantity, "to": to}, context)
    except WorkerError:
        return None
    return Converted(Decimal(value["value"]["decimal"]), "chk_offline_units")


def _response(part: dict, correct: bool) -> Any:
    """The key, or a wrong answer, in the form each item type's marker reads."""
    answer = part["answer"]
    if answer["kind"] == "numeric":
        value = Decimal(answer["value"]) if correct else Decimal(answer["value"]) * 3 + 1
        return f"{value} {answer['unit'] or ''}".strip()
    if answer["kind"] == "multi_select":
        chosen = [o["id"] for o in answer["options"] if o["correct"]]
        return chosen if correct else chosen[:-1] or [o["id"] for o in answer["options"] if not o["correct"]][:1]
    if answer["kind"] == "ordering":
        order = list(answer["correct_order"])
        return order if correct else order[::-1]
    options = [o for o in answer["options"] if o["correct"] is correct]
    return options[0]["id"]


def evl16_content_only_offline(tmp_path: Path) -> None:
    """No model installed and the network off: the pack opens (worked examples, items), practice is marked by code and
    every verdict updates mastery."""
    from pack_builder.build import build

    settings = Settings()
    clock = Clock()
    learner = make_learner(clock=clock)
    with offline_run() as egress:
        built = build(REPO_ROOT / "content" / "curriculum" / "phy" / "o", tmp_path / "pack")
        manifest, tables = read_pack(built.pack_path)
        assert tables["worked_examples"] and tables["kcs"], "the lesson material is in the pack"
        session = new_ulid(clock.now)
        learner.record(
            "session_started",
            {"session_id": session, "mode": "practice", "entry": "practice", "hardware_class": "content_only"},
            source="engine",
            session_id=session,
        )
        outcomes = []
        for item in tables["items"]:
            part = item["parts"][0]
            for correct in (False, True):
                verdict = run(mark(item, part["id"], _response(part, correct), _convert, settings))
                assert verdict.provenance, "a code verdict carries its check"
                outcomes.append((verdict.outcome, correct))
                attempt = new_ulid(clock.now)
                clock.now += 1000
                learner.record("attempt", {
                    "attempt_id": attempt, "session_id": session, "mode": "practice", "item_id": item["id"],
                    "problem_ref": item["id"], "step_index": 0,
                    "kc_ids": [{"kc_id": kc, "weight": round(1 / len(item["kc_ids"]), 3)} for kc in item["kc_ids"]],
                    "kc_source": "pack", "attempt_index": 2 if correct else 1, "response_kind": "typed",
                    "normalised_response": str(_response(part, correct)), "time_ms": 30_000,
                }, source="student", session_id=session)  # fmt: skip
                clock.now += 1000
                learner.record("verdict", {
                    "verdict_id": new_ulid(clock.now), "attempt_id": attempt, "outcome": verdict.outcome,
                    "check_ids": list(verdict.check_ids) or ["chk_offline_key"], "closes_opportunity": correct,
                    "marker_version": verdict.marker_version,
                }, source="checker", session_id=session)  # fmt: skip
        learner.record("session_ended", {"session_id": session, "reason": "completed", "active_ms": 60_000},
                       source="engine", session_id=session)  # fmt: skip
    assert egress.attempts == []
    assert manifest["pack_id"] == "pack.phy.o"
    assert all((outcome == "correct") is correct for outcome, correct in outcomes), outcomes
    kcs = {kc for item in tables["items"] for kc in item["kc_ids"]}
    rows = dict(learner.conn.execute("SELECT kc_id, attempts FROM kc_mastery").fetchall())
    assert kcs <= set(rows) and all(rows[kc] >= 1 for kc in kcs), rows
    assert json.dumps(rows)  # plain data, nothing pending on a model
