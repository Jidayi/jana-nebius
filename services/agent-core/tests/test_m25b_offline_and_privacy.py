"""M25.b: offline-first, optionally online (PRD-03) and private by default (PRD-07), on the shipped core.

The journeys JRN-03 to JRN-10 are replayed on the runner under the egress monitor (the journey tests' own cases are
reused when they already ran in this session); a fresh install is used for a scripted session with every online
feature at its default; the network is cut during a cloud-tier turn; and the specification is checked statically
for every network use stating its offline behaviour. The OS-level form (networking disabled in a network namespace
under strace, `scripts/ci/offline-run.sh`) is the CI offline job, which runs this whole suite; the wall-clock
two-hour soak on a reference laptop is the device lab's. Every learner and reply is synthetic."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from jana_tools import REPO_ROOT
from jana_tools.harness.egress import offline_run
from jana_tools.journeys import runner
from jana_tools.journeys.scripts import script
from jana_tools.product import offline_behaviour_errors
from journey_harness import RESULTS, core, learner, session, turn
from test_m25a_journeys import MODULES, registered_cases

OFFLINE_JOURNEYS = tuple(f"JRN-{n:02d}" for n in range(3, 11))  # PRD-03: JRN-03 to JRN-10
S2_JOURNEYS = tuple(f"JRN-{n:02d}" for n in range(3, 12))  # PRD-07: every S2 journey (JRN-16 is the studio's)


def known_gaps() -> dict[tuple[str, str], str]:
    gaps: dict[tuple[str, str], str] = {}
    for name in MODULES:
        gaps.update(getattr(importlib.import_module(name), "GAPS", {}))
    return gaps


def journey_results(journeys: tuple[str, ...], tmp_path: Path) -> tuple[list[runner.CaseResult], dict[Any, str]]:
    """Every case of `journeys`: the result the journey test already produced in this session, else played now."""
    cases = registered_cases()
    gaps = known_gaps()
    results = []
    for journey in journeys:
        for part in ("main", *(b.id for b in script(journey).branches)):
            if (journey, part) in gaps:
                continue
            found = RESULTS.get(runner.case_id(journey, part))
            if found is None:
                factory = cases[(journey, part)]
                folder = tmp_path / runner.case_id(journey, part)
                folder.mkdir(parents=True)
                found = asyncio.run(runner.run_case(script(journey), part, factory(folder)))  # type: ignore[operator]
                RESULTS[found.case_id] = found
            results.append(found)
    return results, {k: v for k, v in gaps.items() if k[0] in journeys}


def prd03_core_journeys_offline(tmp_path: Path) -> None:
    """JRN-03 to JRN-10, their offline steps and branches (an online branch such as JRN-03 F5 includes its offline
    fallback), pass on the desktop local tier with every non-loopback connection refused and none attempted."""
    results, gaps = journey_results(OFFLINE_JOURNEYS, tmp_path)
    failed = [f"{r.case_id}: {r.reason.splitlines()[0]}" for r in results if r.status != "passed"]
    assert not failed, failed
    assert all(not r.egress for r in results)
    if gaps:
        pytest.xfail("journey cases waiting on product gaps: " + "; ".join(f"{k}: {v}" for k, v in gaps.items()))


def prd07_no_account_no_traffic(tmp_path: Path) -> None:
    """Used through every S2 journey, a fresh install sends no network request (each case ran under the egress monitor
    with zero attempts; the one online branch reached only its loopback stand-in) and creates no account: no account
    route exists, a profile needs no credential, and no service credential or subscription is created."""
    results, gaps = journey_results(S2_JOURNEYS, tmp_path / "journeys")
    assert results and all(r.status == "passed" and not r.egress for r in results), [
        r.case_id for r in results if r.status != "passed" or r.egress
    ]

    async def fresh() -> dict[str, Any]:
        with offline_run() as seen:
            async with core(tmp_path / "fresh", worker=False) as r:
                # The served routes, read from the running app: none signs in, signs up or holds an account.
                app = r.server.config.app if r.server is not None else None
                while app is not None and not hasattr(app, "routes"):  # under the loopback guard's middleware
                    app = getattr(app, "app", None)
                paths = [getattr(route, "path", "") for route in getattr(app, "routes", [])]
                c, _ = await learner(r, "Kofi")
                await c.ok("GET", "/v1/curriculum/cur.phy.o/map")
                await c.ok("GET", "/v1/plans/current")
                ledger = await c.ok("GET", "/v1/connectivity/ledger")
                subscription = await c.ok("GET", "/v1/subscription")
                credential = r.runtime.online.credential.credential_id() if r.runtime.online else None
                state = await c.ok("GET", "/v1/connectivity")
        return {"egress": seen.attempts, "ledger": ledger, "subscription": subscription, "credential": credential,
                "state": state, "paths": paths}  # fmt: skip

    found = asyncio.run(fresh())
    assert len(found["paths"]) > 50 and "/v1/profiles" in found["paths"], "the route table was not read"
    assert not [p for p in found["paths"] if any(w in p for w in ("account", "login", "signup", "sign-in"))]
    assert found["egress"] == [] and found["credential"] is None
    assert not found["ledger"].get("entries")
    assert found["subscription"]["subscription_id"] is None and not found["subscription"]["profiles"]
    assert not any(f["enabled"] for f in found["state"]["features"].values())
    if gaps:
        pytest.xfail("journey cases waiting on product gaps: " + "; ".join(f"{k}: {v}" for k, v in gaps.items()))


def prd03_zero_network_default(tmp_path: Path) -> None:
    """A fresh install with every online feature at its default (off), used for a scripted session while the
    connectivity layer runs, then two hours of its periodic work (probe, outbox, telemetry flush, retention) played
    on a simulated clock: the monitor records zero outbound connections and the egress ledger stays empty."""
    from agent_core.config import Settings
    from journey_harness import SETTINGS
    from test_m13g_learn import LESSON

    settings: Settings = SETTINGS.model_copy(update={"telemetry_flush_interval_s": 1.0})
    minutes = 120

    async def scenario() -> dict[str, Any]:
        with offline_run() as seen:
            async with core(tmp_path, settings=settings, stage="S1") as r:
                c, _ = await learner(r)
                sid = await session(c)
                engine = await turn(c, sid, "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high"
                                    " does it rise?")  # fmt: skip
                await c.ok("GET", f"/v1/lessons/{LESSON}")
                await c.ok("GET", "/v1/plans/current")
                await asyncio.sleep(3.0)  # the layer's own loops run (the flush loop ticks every second here)
                online = r.runtime.online
                assert online is not None
                start = r.core.clock_ms()
                for minute in range(minutes):
                    if online.features_on():
                        break
                    await online.drain_once()
                    r.core.retention(start + minute * 60_000)
                ledger = await c.ok("GET", "/v1/connectivity/ledger")
                state = await c.ok("GET", "/v1/connectivity")
                queued = online.outbox.depth() if hasattr(online.outbox, "depth") else 0
        return {"egress": seen.attempts, "ledger": ledger, "state": state, "turn": engine is not None,
                "queued": queued}  # fmt: skip

    found = asyncio.run(scenario())
    assert found["turn"]
    assert found["egress"] == [], found["egress"]
    assert not found["ledger"].get("entries")
    assert not any(f["enabled"] for f in found["state"]["features"].values())


def prd03_cloud_loss_falls_back_local(tmp_path: Path) -> None:
    """The network is cut while the cloud tier answers a turn: the turn completes on the local tier, the board keeps
    every step it had, and the student sees no error (only the continuing-locally notice)."""
    from engine_harness import STATEMENT, close, tutor
    from net_harness import FakeServices
    from test_m19c_cloud import NEXT, SAFE, cloud_engine, cloud_says, coach_kinds, events, seeded_then_cut

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), seeded_then_cut()]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)])
            first = await engine.start_problem(STATEMENT)
            before = [s.__dict__.copy() for s in engine.state.board.steps], dict(engine.state.board.knowns or {})
            cut = await engine.student_turn("s = 3 m")
            after = [s.__dict__.copy() for s in engine.state.board.steps], dict(engine.state.board.knowns or {})
            await close(engine)
            await online.stop()
            return engine, first, cut, before, after

    engine, first, cut, before, after = asyncio.new_event_loop().run_until_complete(scenario())
    assert coach_kinds(first) == ["cloud"] and coach_kinds(cut)[-1] == "local"
    assert cut.status == "complete" and cut.tutor_turn["say"] == NEXT
    assert after[0][: len(before[0])] == before[0] and after[1] == before[1], "the board state changed"
    shown = events(engine)
    assert not [e for e in shown if e["type"] == "error"]
    assert [e["code"] for e in shown if e["type"] == "notice" and e["code"].startswith("cloud_")] == [
        "cloud_continuing_locally"
    ]


def prd03_network_requirements_state_offline_behaviour(tmp_path: Path) -> None:
    """The specification states an offline behaviour for every network use (TABLE ARC-07a, PRD-03a and DAT-18a rows,
    the journeys' optional online steps) and the network policy holds the same features with a queueing rule; a
    feature added without its offline behaviour fails the check."""
    assert offline_behaviour_errors() == []
    policy = json.loads((REPO_ROOT / "services/agent-core/agent_core/net/policy.json").read_text())
    policy["features"]["cloud_tier"]["queued"] = ""
    policy["features"]["new_online_feature"] = {"queued": "never"}
    edited = tmp_path / "policy.json"
    edited.write_text(json.dumps(policy))
    found = offline_behaviour_errors(policy_path=edited)
    assert "PRD-03: the network policy gives cloud_tier no offline queueing rule" in found
    assert "PRD-03: the network policy has new_online_feature, which TABLE ARC-07a does not" in found


def prd07_consent_required_before_egress(tmp_path: Path) -> None:
    """Switching the cloud tier on without a recorded consent puts nothing online for a minor's profile: the profile's
    own switch is refused with the consent route (guardian_consent_required, the checkout's consent screen, D70),
    the tier is not in effect and a turn stays local; once the guardian's consent is recorded it is in effect. Sync
    (cloud_backup, multi_device) is not an online feature of this stage and cannot be switched on at all."""
    from agent_core.store import consents as store
    from agent_core.store import subscription as subscriptions
    from test_m10e_consent import NOTICE

    async def scenario() -> dict[str, Any]:
        async with core(tmp_path, worker=False) as r:
            c, profile = await learner(r)
            api = c.api
            alone = await api.call("PUT", f"/v1/profiles/{profile}/consents/cloud_tier",
                                   {"action": "on", "notice_version": NOTICE}, profile=c.token)  # fmt: skip
            device = await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": True}})
            online = r.runtime.online
            assert online is not None
            # A subscription applied for the profile whose guardian's consent is still needed (D70): pending.
            now = r.core.clock_ms()
            pending = {
                "subscription_id": "sub_synthetic",
                "period_start": now - 1000,
                "period_end": now + 86_400_000,
                "seats": 1,
                "allowance_tokens": None,
                "licence_id": "lic_synthetic",
                "profiles": [profile],
                "consent_needed": [profile],
                "payer": "synthetic",
                "ended_at": None,
                "entitlement": None,
            }
            subscriptions.save(r.runtime.directory.device, pending, now)  # fmt: skip
            with r.runtime.directory.open_learner(profile) as conn:
                without = online.cloud_effective(profile, conn)
                store.grant(conn, "cloud_tier", "guardian", "Parent", NOTICE, r.core.settings.consent_dpia_ref, now)
                subscriptions.save(r.runtime.directory.device, subscriptions.consent_given(pending, [profile]), now)
                with_consent = online.cloud_effective(profile, conn)
            sync = await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_backup": True}})
            ledger = await c.ok("GET", "/v1/connectivity/ledger")
        return {"alone": alone.json(), "device": device.status_code, "without": without, "with": with_consent,
                "sync": (sync.status_code, sync.json()), "ledger": ledger}  # fmt: skip

    found = asyncio.run(scenario())
    assert found["alone"]["error"]["code"] == "guardian_consent_required"
    assert found["device"] == 200 and found["without"] is False and found["with"] is True
    assert found["sync"][0] != 200 and "not an online feature of this version" in found["sync"][1]["error"]["message"]
    # The device switch lets the layer probe the gateway's reachability (ARC-08): no learner data class goes with it.
    entries = found["ledger"]["entries"]
    assert all(e.get("payload_class") == "probe" and not e.get("data_classes") for e in entries), entries
