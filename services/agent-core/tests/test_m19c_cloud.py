"""M19.c: the cloud tier through our gateway, with its fallbacks, minimisation, budgets and notices (ARC-05, ARC-10,
ARC-12, API-15, UXS-08, MDL-09, MDL-24, MDL-25, MDL-29, BIZ-07, PRV-25). The gateway is the local TLS stand-in of
net_harness; the Solver and Checker run on the scripted local provider. Every reply is synthetic."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import document
from agent_core.net.layer import OnlineLayer
from agent_core.net.policy import load_policy
from agent_core.net.redaction import Redactor
from agent_core.providers.base import Message, ProviderError
from agent_core.providers.gateway import GatewayProvider
from agent_core.router.budget import CloudBudget, MemorySpend
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools.harness.egress import offline_run
from net_harness import HOSTS, FakeServices, enable, layer, sse_reply, telemetry_payload

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
NEXT = "Good. Which equation links u, v, a and s?"
SEEDED = "Seeded cloud words that must never be shown"
NAME = "Abena Owusu"  # an invented display name
PRICES = {"fast-model": (1.25, 10.0)}
PROFILE = "prf_01ARZ3NDEKTSV4RRFFQ69G5FAV"  # an invented profile id


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def settings() -> Settings:
    # Generous tool limits: these tests are about the network path, not tool speed on a loaded machine.
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_call_cpu_ms=30000,
                    ver_symbolic_slice_ms=10000)  # fmt: skip


def say(text: str) -> str:
    return str(tutor(text)["reply"]["choices"][0]["message"]["content"])


def cloud_says(text: str, cut: int | None = None) -> tuple[str, list[dict[str, Any]], int | None]:
    return ("sse", sse_reply(say(text)), cut)


def seeded_then_cut() -> tuple[str, list[dict[str, Any]], int | None]:
    """The cloud starts streaming a reply, then the network goes: the stream stops without its end."""
    return ("sse", sse_reply(SEEDED * 4), 6)


async def cloud_engine(tmp: Path, services: FakeServices, local_coach: list[Any], *, terms: tuple[str, ...] = (),
                       budget: CloudBudget | None = None, prefer_cloud: bool = True,
                       online: OnlineLayer | None = None) -> tuple[Any, Any, OnlineLayer, GatewayProvider]:  # fmt: skip
    online = online or layer(tmp, services)
    enable(online, "cloud_tier")
    online.connectivity.features_changed()
    await online.connectivity.check()
    provider = GatewayProvider(online.client, lambda: online.host_for("cloud_tier"), "primary",
                               token=online.credential.token, prices=PRICES, redactor=Redactor(terms),
                               on_network_failure=online.network_failure)  # fmt: skip

    def overrides(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True
        if prefer_cloud:
            data["roles"]["coach"]["prefer"] = "cloud"

    script = {"solver": solver_steps(), "checker": checker_steps(), "coach": local_coach}
    engine, local = await make_engine(tmp, script, settings=settings(), overrides=overrides, cloud=provider)
    router = engine.deps.router
    router.cloud_on = lambda role: role == "coach"
    router.network = lambda: online.connectivity.state
    if budget is not None:
        router.budget = budget
    return engine, local, online, provider


def events(engine: Any) -> list[dict[str, Any]]:
    return [f["event"] for f in engine.events.frames]


def chats(services: FakeServices) -> list[Any]:
    return [r for r in services.requests if r.path == "/v1/chat/completions"]


def coach_kinds(result: Any) -> list[str]:
    return [c["provider_kind"] for c in result.trace["model_calls"] if c["role"] == "coach"]


# --- ARC-12, MDL-09, PRV-25, UXS-08, API-15 ---------------------------------------------------------------------


def arc12_midstream_loss_continues_locally(tmp_path: Path) -> None:
    """The network is cut while the cloud streams the Coach's reply: the turn completes on the local model with one
    notice, and the cloud's partial text reaches no student event, no replay and no persisted transcript."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), seeded_then_cut()]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)])
            first = await engine.start_problem(STATEMENT)
            cut = await engine.student_turn("s = 3 m")
            await close(engine)
            await online.stop()
            return engine, first, cut

    engine, first, cut = run(scenario())
    assert coach_kinds(first) == ["cloud"]
    assert coach_kinds(cut)[0] == "cloud" and coach_kinds(cut)[-1] == "local", coach_kinds(cut)
    assert cut.status == "complete" and cut.tutor_turn["say"] == NEXT
    notices = [e for e in events(engine) if e["type"] == "notice" and e["code"].startswith("cloud_")]
    assert [n["code"] for n in notices] == ["cloud_continuing_locally"]
    shown = json.dumps(engine.events.frames) + json.dumps(engine.persisted) + json.dumps(engine.state.transcript)
    assert "Seeded cloud words" not in shown


def mdl09_midturn_offline_fallback(tmp_path: Path) -> None:
    """A streamed cloud Coach reply that loses the network mid-turn ends with one Coach text part, status
    `complete`, on the local model."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [seeded_then_cut()]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(SAFE)])
            result = await engine.start_problem(STATEMENT)
            await close(engine)
            await online.stop()
            return engine, result

    engine, result = run(scenario())
    assert result.status == "complete"
    assert coach_kinds(result) == ["cloud", "local"]
    turn = [f for f in engine.events.frames if f["turn_id"] == result.turn_id]
    texts = [f["event"] for f in turn if f["event"]["type"] == "part.start" and f["event"]["kind"] == "text"]
    ends = [f["event"] for f in turn if f["event"]["type"] == "turn.end"]
    assert len(texts) >= 1 and ends and ends[-1]["status"] == "complete"
    assert "Seeded" not in json.dumps(turn)


def prv25_cloud_offline_fallback(tmp_path: Path) -> None:
    """The device goes offline in the middle of a cloud turn: the turn completes locally, no error reaches the
    student, and the prompt is never queued."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), "drop"]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)])
            await engine.start_problem(STATEMENT)
            turn = await engine.student_turn("s = 3 m")
            queued = online.outbox.counts()
            await close(engine)
            await online.stop()
            return engine, turn, queued

    engine, turn, queued = run(scenario())
    assert turn.status == "complete" and coach_kinds(turn)[-1] == "local"
    assert not [e for e in events(engine) if e["type"] == "error"]
    assert queued == {}, "prompts are never queued (DAT-18)"


def uxs08_cloud_drop_falls_back(tmp_path: Path) -> None:
    """Dropping the network during a cloud-tier turn: the turn completes on the local model with the board steps
    the session had, and exactly one notice."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)])
            await engine.start_problem(STATEMENT)
            board_before = [s.step_id for s in engine.state.board.steps]
            online.connectivity.os_hint(online=False)  # the cable is pulled before the next turn
            turn = await engine.student_turn("s = 3 m")
            board_after = [s.step_id for s in engine.state.board.steps]
            await close(engine)
            await online.stop()
            return engine, turn, board_before, board_after, len(chats(services))

    engine, turn, before, after, sent = run(scenario())
    assert turn.status == "complete" and coach_kinds(turn) == ["local"]
    assert after[: len(before)] == before, "the board's steps are kept"
    turn_events = [f["event"] for f in engine.events.frames if f["turn_id"] == turn.turn_id]
    notices = [e for e in turn_events if e["type"] == "notice"]
    assert [n["code"] for n in notices] == ["cloud_unavailable_using_local"]
    assert sent == 1, "nothing more went to the cloud once offline"


def api15_offline_fallback(tmp_path: Path) -> None:
    """Network pulled during a cloud-tier turn: a local model answers, with the notice and no error; the blocked
    attempt is announced as `blocked`."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(SAFE)])
            online.connectivity.os_hint(online=False)
            result = await engine.start_problem(STATEMENT)
            await close(engine)
            await online.stop()
            return engine, result, chats(services)

    engine, result, sent = run(scenario())
    assert result.status == "complete" and sent == []
    seen = events(engine)
    states = [e["state"] for e in seen if e["type"] == "egress.notice"]
    assert states and set(states) == {"blocked"}, "announced as blocked, never as started"
    assert [e["code"] for e in seen if e["type"] == "notice"] == ["cloud_unavailable_using_local"]
    assert not [e for e in seen if e["type"] == "error"]


def api15_egress_announced(tmp_path: Path) -> None:
    """Every request that carries session data is preceded by `egress.notice started` and followed by `ended`."""
    order: list[str] = []

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.handlers["/"] = lambda seen: order.append(f"sent {seen.path}")  # type: ignore[func-returns-value]
            services.chat = [cloud_says(SAFE), cloud_says(NEXT)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [])
            engine.events.sink = lambda env: order.append(f"notice {env['event']['state']}") if env["event"][
                "type"] == "egress.notice" else None  # fmt: skip
            await engine.start_problem(STATEMENT)
            await engine.student_turn("s = 3 m")
            await close(engine)
            await online.stop()

    run(scenario())
    open_notice = False
    carrying = 0
    for entry in order:
        if entry == "notice started":
            open_notice = True
        elif entry == "notice ended":
            open_notice = False
        elif entry.startswith("sent") and entry != "sent /v1/ping":
            assert open_notice, f"{entry} left without a preceding started notice: {order}"
            carrying += entry == "sent /v1/chat/completions"
    assert carrying == 2 and not open_notice


def api15_feature_ids_match_arc07(tmp_path: Path) -> None:
    ids = set(load_policy().features)
    assert set(document("api/events")["$defs"]["online_feature"]["enum"]) == ids
    online = layer(tmp_path)
    status = online.status()
    assert {f["feature"] for f in status["features"]} == set(load_policy().shipped()) <= ids
    notice_feature = document("api/events")["$defs"]["ev_egress_notice"]["properties"]["feature"]["$ref"]
    assert notice_feature.endswith("/online_feature")
    run(online.stop())


def arc12_only_gateway_egress(tmp_path: Path) -> None:
    """With the cloud tier on, every connection the core makes is to the gateway host (the stand-in sees each
    request's host); nothing else is dialled."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), cloud_says(NEXT)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [])
            await engine.start_problem(STATEMENT)
            await engine.student_turn("s = 3 m")
            await close(engine)
            await online.stop()
            rows = online.device.execute("SELECT DISTINCT destination FROM egress_ledger").fetchall()
            return services.requests, rows

    with offline_run() as egress:
        seen, ledger = run(scenario())
    assert egress.attempts == []
    assert {r.host.split(":")[0] for r in seen} == {HOSTS["gateway"]}
    assert ledger == [(HOSTS["gateway"],)]


# --- ARC-05 -----------------------------------------------------------------------------------------------------


def arc05_t1_offline_end_to_end(tmp_path: Path) -> None:
    """T1: the tutoring flow with the connectivity layer present, every feature off and the network refused."""

    async def scenario() -> Any:
        online = layer(tmp_path)
        online.start()
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                 "coach": [tutor(SAFE), tutor(NEXT)]}, settings=settings())  # fmt: skip
        engine.deps.router.network = lambda: online.connectivity.state
        first = await engine.start_problem(STATEMENT)
        second = await engine.student_turn("s = 3 m")
        await close(engine)
        await online.stop()
        return first, second, online

    with offline_run() as egress:
        first, second, online = run(scenario())
    assert egress.attempts == [] and online.connectivity.probes == 0
    assert first.status == second.status == "complete"


def arc05_t2_network_loss_mid_session(tmp_path: Path) -> None:
    """T2: every online feature on; the network is cut mid-session; no turn is interrupted, the cloud tier gives
    way to the local model and queued work waits in the outbox."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            online = layer(tmp_path, services)
            enable(online, *load_policy().shipped())
            services.chat = [cloud_says(SAFE), seeded_then_cut()]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT), tutor(SAFE)], online=online)
            results = [await engine.start_problem(STATEMENT), await engine.student_turn("s = 3 m")]
            online.connectivity.os_hint(online=False)
            online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=online.clock_ms() + 86_400_000)
            results.append(await engine.student_turn("s = 12 m"))
            queued = online.outbox.counts()
            await close(engine)
            await online.stop()
            return results, queued

    results, queued = run(scenario())
    assert [r.status for r in results] == ["complete"] * 3
    assert coach_kinds(results[1])[-1] == "local" and coach_kinds(results[2]) == ["local"]
    assert queued == {"telemetry": 1}


# --- ARC-10 -----------------------------------------------------------------------------------------------------


def arc10_first_use_notice_per_feature(tmp_path: Path) -> None:
    """The cloud tier's first use on a profile shows its notice as a confirm card; "Keep it on this computer" sends
    nothing and the tutor stays local. Every other feature's first request on a profile waits for its notice the same
    way at the connectivity layer."""
    answers: dict[str, str] = {}

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(NEXT)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(SAFE), tutor(NEXT)])
            router = engine.deps.router
            router.cloud_on = lambda role: role == "coach" and answers.get("cloud_tier") == "accepted"
            engine.cloud_possible = lambda: True
            engine.cloud_notice = lambda: answers.get("cloud_tier")
            engine.record_cloud_notice = lambda ok: answers.__setitem__("cloud_tier", "accepted" if ok else "declined")
            first = await engine.start_problem(STATEMENT)
            cards = [e for e in events(engine) if e["type"] == "card.open"
                     and e["card"].get("purpose") == "egress"]  # fmt: skip
            assert len(cards) == 1 and cards[0]["card"]["cancel_label_key"] == "egress.first_use.keep_local"
            assert engine.answer_egress(cards[0]["request_id"], {"action": "cancel"})
            kept_local = await engine.student_turn("s = 3 m")
            sent_after_decline = len(chats(services))
            answers.clear()
            assert engine.answer_egress(cards[0]["request_id"], {"action": "confirm"})
            cloud_turn = await engine.student_turn("s = 12 m")
            # Every other shipped feature, at the connectivity layer: notice first, then declined or accepted.
            decided: dict[tuple[str, str | None], str] = {}
            asked: list[str] = []
            client = online.client
            client.notice = lambda f, p: decided.get((f, p))
            client.on_notice_needed = lambda f, p: asked.append(f)
            enable(online, *load_policy().shipped())
            outcomes = {}
            for feature in load_policy().shipped():
                row = load_policy().features[feature]
                url = f"https://{online.host_for(feature)}/v1/x"
                outcome = []
                for answer in (None, "declined", "accepted"):
                    if answer is not None:
                        decided[(feature, "prf_test")] = answer
                    before = len(services.requests)
                    try:
                        await client.send(
                            feature,
                            "POST",
                            url,
                            row.payload_classes[0],
                            content=telemetry_payload() if feature == "telemetry" else b"{}",
                            profile_id="prf_test",
                        )
                        outcome.append("sent")
                    except Exception as error:  # the refusal reason is the outcome
                        outcome.append(getattr(error, "reason", type(error).__name__))
                    assert answer == "accepted" or len(services.requests) == before
                outcomes[feature] = outcome
            await close(engine)
            await online.stop()
            return first, kept_local, sent_after_decline, cloud_turn, outcomes, asked

    first, kept_local, sent_after_decline, cloud_turn, outcomes, asked = run(scenario())
    assert coach_kinds(first) == ["local"] and coach_kinds(kept_local) == ["local"]
    assert sent_after_decline == 0
    assert coach_kinds(cloud_turn) == ["cloud"]
    for feature, outcome in outcomes.items():
        assert outcome == ["notice_pending", "notice_declined", "sent"], (feature, outcome)
    assert sorted(set(asked)) == sorted(load_policy().shipped())


# --- MDL-24, MDL-25, PRV-25 -------------------------------------------------------------------------------------


def mdl24_off_by_default(tmp_path: Path) -> None:
    """A fresh install: the cloud tier is not in effect for any profile, so the router never offers a cloud
    candidate and no model request leaves."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            online = layer(tmp_path, services)
            provider = GatewayProvider(online.client, lambda: online.host_for("cloud_tier"), "primary")

            def overrides(data: dict[str, Any]) -> None:
                data["cloud"]["enabled"] = True  # even a build with the gate open
                data["roles"]["coach"]["prefer"] = "cloud"

            engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                     "coach": [tutor(SAFE)]}, settings=settings(),
                                          overrides=overrides, cloud=provider)  # fmt: skip
            engine.deps.router.cloud_on = lambda role: online.cloud_effective("prf_test", None)
            result = await engine.start_problem(STATEMENT)
            await close(engine)
            await online.stop()
            return result, services.requests

    result, requests = run(scenario())
    assert requests == [] and coach_kinds(result) == ["local"]


def mdl24_offline_no_wait(tmp_path: Path) -> None:
    """The cloud tier on and the network off: the router skips cloud candidates at once, so a turn takes no longer
    than with the tier off, within the configured margin."""
    limit_s = Settings().cloud_offline_added_wait_ms / 1000

    async def timed(cloud: bool) -> tuple[float, list[str]]:
        sub = tmp_path / ("on" if cloud else "off")
        sub.mkdir(exist_ok=True)
        async with FakeServices(sub) as services:
            engine, _, online, _ = await cloud_engine(sub, services, [tutor(SAFE)] * 3)
            if cloud:
                online.connectivity.os_hint(online=False)
            else:
                engine.deps.router.cloud_on = lambda role: False
            await engine.start_problem(STATEMENT)
            started = time.monotonic()
            turn = await engine.student_turn("s = 3 m")
            took = time.monotonic() - started
            await close(engine)
            await online.stop()
            return took, coach_kinds(turn)

    async def scenario() -> Any:
        offs, ons = [], []
        for _ in range(2):  # the best of two, so machine load does not decide the outcome
            offs.append(await timed(False))
            ons.append(await timed(True))
        return min(t for t, _ in offs), min(t for t, _ in ons), ons[0][1]

    off, on, kinds = run(scenario())
    assert kinds == ["local"]
    assert on - off < limit_s, (on, off)


def mdl25_redaction_blocks(tmp_path: Path) -> None:
    """A request carrying the profile's name, or a contact detail, is blocked before it leaves and served locally."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE)]
            engine, _, online, provider = await cloud_engine(tmp_path, services, [tutor(NEXT), tutor(NEXT)],
                                                             terms=(NAME, PROFILE))  # fmt: skip
            await engine.start_problem(STATEMENT)
            sent = len(chats(services))
            named = await engine.student_turn(f"I am {NAME} and I got s = 3 m")
            try:  # a contact detail is blocked the same way, at the provider, before anything leaves
                await provider.complete("fast-model", [Message("user", "write to me at someone@example.org")], [])
                mailed = "sent"
            except ProviderError as error:
                mailed = error.reason
            after = len(chats(services))
            await close(engine)
            await online.stop()
            return sent, after, named, mailed, services

    sent, after, named, mailed, services = run(scenario())
    assert sent == 1 and after == 1, "the blocked requests never left"
    calls = [c for c in named.trace["model_calls"] if c["role"] == "coach"]
    assert calls[-1]["provider_kind"] == "local", "served locally"
    assert all(c["reason"] == "content_filter" for c in calls if c["provider_kind"] == "cloud")
    assert mailed == "content_filter"
    assert NAME not in json.dumps([r.body.decode() for r in services.requests])


def prv25_cloud_request_pseudonymous(tmp_path: Path) -> None:
    """A captured cloud request carries a per-session pseudonym and no profile id, display name or note."""
    note = "Likes worked examples with diagrams"  # an invented memory note

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE)]
            engine, _, online, provider = await cloud_engine(tmp_path, services, [], terms=(NAME,))
            engine.profile_ref = "prf_01ARZ3NDEKTSV4RRFFQ69G5FAV"
            await engine.start_problem(STATEMENT)
            await close(engine)
            await online.stop()
            return [r for r in services.requests if r.path == "/v1/chat/completions"], provider

    captured, provider = run(scenario())
    assert len(captured) == 1
    wire = captured[0].body.decode() + json.dumps(captured[0].headers)
    assert captured[0].headers["x-session-pseudonym"] == provider.pseudonym
    for forbidden in ("prf_", NAME, note, "x-profile-token", "ses_"):
        assert forbidden not in wire, forbidden


# --- MDL-29, BIZ-07 ---------------------------------------------------------------------------------------------


def mdl29_budget_fallback(tmp_path: Path) -> None:
    """The session budget is crossed by a cloud call: that turn finishes on the cloud, the next is served locally
    without a word to the student, and the engine got each reminder once."""
    reminders: list[tuple[str, float]] = []
    spend = MemorySpend()
    budget = CloudBudget(session_usd=0.002, day_usd=1.0, reminders=(0.5, 0.85), spend=spend,
                         today=lambda: "2026-10-13",
                         on_reminder=lambda limit, f: reminders.append((limit, f)))  # fmt: skip

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), cloud_says(NEXT)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)], budget=budget)
            first = await engine.start_problem(STATEMENT)
            second = await engine.student_turn("s = 3 m")
            await close(engine)
            await online.stop()
            return engine, first, second

    engine, first, second = run(scenario())
    assert coach_kinds(first) == ["cloud"] and first.status == "complete"
    assert coach_kinds(second) == ["local"] and second.status == "complete"
    assert ("session", 0.5) in reminders and reminders.count(("session", 0.85)) == 1
    assert not [e for e in events(engine) if e["type"] == "notice" and "cost" in json.dumps(e)]
    assert budget.exhausted() == ["session"]


def biz07_allowance_falls_back_local(tmp_path: Path) -> None:
    """The month's allowance runs out mid-session: the next turn is local, the board is intact, and the student sees
    no payment prompt."""
    budget = CloudBudget(session_usd=100.0, day_usd=100.0, reminders=(0.5, 0.85), spend=MemorySpend(),
                         today=lambda: "2026-10-13", allowance_tokens=1000)  # fmt: skip

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as services:
            services.chat = [cloud_says(SAFE), cloud_says(NEXT)]
            engine, _, online, _ = await cloud_engine(tmp_path, services, [tutor(NEXT)], budget=budget)
            first = await engine.start_problem(STATEMENT)
            board = [s.step_id for s in engine.state.board.steps]
            second = await engine.student_turn("s = 3 m")
            board_after = [s.step_id for s in engine.state.board.steps]
            await close(engine)
            await online.stop()
            return engine, first, second, board, board_after

    engine, first, second, board, board_after = run(scenario())
    assert coach_kinds(first) == ["cloud"] and coach_kinds(second) == ["local"]
    assert second.status == "complete"
    assert budget.exhausted() == ["month"]
    shown = json.dumps(events(engine)).lower()
    for word in ("payment", "subscribe", "subscription", "price", "allowance", "buy"):
        assert word not in shown, word
    assert board_after[: len(board)] == board, "the board is intact"


def test_biz07_allowance_resets_each_month_of_a_prepaid_term() -> None:
    """D33 (decided in D100): the allowance is per student per month, also inside a term paid three months at once.
    A used-up month falls back to local; the next calendar month of the paid period starts from zero, offline; a
    start on the 31st falls on the last day of a shorter month; the last month ends with the period."""
    import sqlite3
    from datetime import UTC, datetime

    from agent_core.store import subscription as subscriptions
    from agent_core.store.egress import DeviceSpend

    def ms(*parts: int) -> int:
        return int(datetime(*parts, tzinfo=UTC).timestamp() * 1000)

    start = ms(2026, 1, 31, 9)
    stored = {"subscription_id": "sub_term", "period_start": start, "period_end": subscriptions.add_months(start, 3),
              "allowance_tokens": 1000, "profiles": ["prf_a"]}  # fmt: skip
    assert stored["period_end"] == ms(2026, 4, 30, 9)
    assert subscriptions.allowance_window(stored, ms(2026, 2, 15)) == (0, start, ms(2026, 2, 28, 9))
    assert subscriptions.allowance_window(stored, ms(2026, 3, 1)) == (1, ms(2026, 2, 28, 9), ms(2026, 3, 31, 9))
    assert subscriptions.allowance_window(stored, ms(2026, 4, 30, 8)) == (2, ms(2026, 3, 31, 9), stored["period_end"])
    device = sqlite3.connect(":memory:", isolation_level=None)
    device.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)")
    clock = [ms(2026, 2, 20)]

    def budget() -> CloudBudget:
        spend = DeviceSpend(device, "prf_a", subscriptions.allowance_period(stored, clock[0]), lambda: clock[0])
        return CloudBudget(session_usd=100.0, day_usd=100.0, reminders=(0.5, 0.85), spend=spend,
                           today=lambda: "2026-02-20", allowance_tokens=stored["allowance_tokens"])  # fmt: skip

    february = budget()
    february.record(0.01, 1000)
    assert february.exhausted() == ["month"] and not budget().allows()  # the rest of the month is local
    clock[0] = ms(2026, 3, 2)  # the term's next month
    march = budget()
    assert march.allows() and march.used()["month"] == 0.0
    assert subscriptions.allowance_period(stored, clock[0]) == "sub_term#m1"


def test_device_chat_bodies_match_the_gateway_contract() -> None:
    """Every body the device sends the gateway is a `ChatCompletionRequest` (D39): plain and streamed turns, tools
    and a forced tool, a tool's reply with its name, a photo, structured output and a reasoning effort."""
    from agent_core.contracts import errors as contract_errors
    from agent_core.providers.base import ToolCall, ToolSchema

    provider = GatewayProvider(None, lambda: HOSTS["gateway"], "primary")  # type: ignore[arg-type]  # never sends
    tool = ToolSchema(
        "math_eval", "Evaluate an expression.", {"type": "object", "properties": {"x": {"type": "string"}}}
    )
    call = ToolCall("call_1", "math_eval", {"x": "2+2"})
    messages = [
        Message("system", "Be brief."),
        Message("user", "What is 2+2?", images=("data:image/jpeg;base64,AA==",)),
        Message("assistant", "", tool_calls=(call,)),
        Message("tool", "4", tool_call_id="call_1", name="math_eval"),
    ]
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    settings: list[dict[str, Any]] = [
        {},
        {"temperature": 0.2, "max_tokens": 200, "top_p": 0.9, "seed": 7, "stop": ["END"], "role": "coach"},
        {"structured": {"mode": "json_schema", "name": "reply", "schema": schema}},
        {"structured": {"mode": "json_object"}, "reasoning": {"control": "low"}},
        {"structured": {"mode": "tool", "tool": "math_eval"}},
        {"param_fixes": {"max_tokens": "max_completion_tokens"}, "max_tokens": 64},
    ]

    async def bodies() -> list[dict[str, Any]]:
        built = []
        for chosen in settings:
            for stream in (False, True):
                body, _, _ = await provider._prepare("fast-model", messages, [tool], chosen, stream)
                built.append(body)
        return built

    for body in run(bodies()):
        assert contract_errors("cloud/gateway#/$defs/ChatCompletionRequest", body) == [], body
