"""M19.a: the connectivity layer: policy, detection, outbox and zero egress by default (ARC-05 to ARC-09, DAT-11,
PRV-02). Our online services are a local TLS stand-in (net_harness); payloads and replies are synthetic."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import document
from agent_core.net.client import EgressClient
from agent_core.net.policy import EgressRefused, LanServer, load_policy
from agent_core.net.state import Connectivity
from agent_core.store import consents as consent_store
from agent_core.store import egress as store
from agent_core.store.generated.schema import DEVICE
from agent_core.store.local import open_local
from jana_tools.harness.egress import offline_run
from jana_tools.spec import DOCS, table_rows
from net_harness import HOSTS, FakeServices, enable, layer, make_pki, telemetry_payload

LOOP = asyncio.new_event_loop()
DAY_MS = 86_400_000


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _arc07_rows() -> list[list[str]]:
    text = (DOCS / "specification" / "architecture.md").read_text()
    return table_rows(text, "TABLE ARC-07a")


# --- ARC-06 -------------------------------------------------------------------------------------------------------


def arc06_zero_egress_when_all_off(tmp_path: Path) -> None:
    """Every feature off, no LAN server: a long scripted session of attempts, OS hints and the probe and drain loops
    opens no non-loopback socket and makes no lookup; the probe never runs and the ledger stays empty."""

    async def scenario() -> tuple[Any, int]:
        online = layer(tmp_path)
        online.start()
        refused = 0
        for minute in range(120):  # two hours of a scripted session, one beat a minute
            online.connectivity.os_hint(online=True, metered=minute % 30 == 0)
            for feature in load_policy().shipped():
                host = online.host_for(feature)
                payload = load_policy().features[feature].payload_classes[0]
                try:
                    await online.client.send(feature, "POST", f"https://{host}/v1/x", payload, body={"n": minute})
                except EgressRefused:
                    refused += 1
            await online.drain_once()
            await asyncio.sleep(0)
        await online.stop()
        return online, refused

    with offline_run() as egress:
        online, refused = run(scenario())
    assert egress.attempts == []
    assert online.connectivity.state == "off" and online.connectivity.probes == 0
    assert refused == 120 * len(load_policy().shipped())
    assert online.device.execute("SELECT count(*) FROM egress_ledger").fetchone()[0] == 0


def arc06_lan_peer_class_only(tmp_path: Path) -> None:
    """All features off and an adult-configured LAN compute server: only pinned TLS to that private address goes,
    and it is ledgered as LAN compute; anything else, or the same address with another key, is refused."""
    lan_ip = "10.20.30.40"
    pki = make_pki(["lan-server"], ips=(lan_ip,))

    async def scenario() -> tuple[Any, Any, list[str]]:
        async with FakeServices(tmp_path, pki=pki) as server:
            other = make_pki(["impostor"], "Other CA")
            server.handlers["/v1/lan/hello"] = lambda seen: (200, {"server_device_id": "srv_test"})
            online = layer(tmp_path, context=pki.client_context(), connect={lan_ip: ("127.0.0.1", server.port)},
                           lan=LanServer(lan_ip, 8443, (pki.ca_pin,)))  # fmt: skip
            reply = await online.client.send("lan_compute", "POST", f"https://{lan_ip}:8443/v1/lan/hello",
                                             "lan_session", body={"hello": True})  # fmt: skip
            reasons = []
            for feature, url, payload in (
                ("lan_compute", "https://10.20.30.41:8443/v1/lan/hello", "lan_session"),
                ("lan_compute", f"https://{lan_ip}:8443/v1/lan/hello", "cloud_prompt"),
                ("cloud_tier", f"https://{HOSTS['gateway']}/v1/chat/completions", "cloud_prompt"),
                ("update_checks", f"https://{HOSTS['updates']}/v1/check", "update_check"),
            ):
                with pytest.raises(EgressRefused) as refused:
                    await online.client.send(feature, "POST", url, payload, body={})
                reasons.append(refused.value.reason)
            public = layer(tmp_path / "public", lan=LanServer("8.8.8.8", 8443, (pki.ca_pin,)))
            with pytest.raises(EgressRefused) as refused:
                await public.client.send("lan_compute", "POST", "https://8.8.8.8:8443/v1/lan/hello", "lan_session",
                                         body={})  # fmt: skip
            reasons.append(refused.value.reason)
            impostor = layer(tmp_path / "impostor", context=pki.client_context(),
                             connect={lan_ip: ("127.0.0.1", server.port)},
                             lan=LanServer(lan_ip, 8443, (other.ca_pin,)))  # fmt: skip
            with pytest.raises(EgressRefused) as refused:
                await impostor.client.send("lan_compute", "POST", f"https://{lan_ip}:8443/v1/lan/hello",
                                           "lan_session", body={"secret": "never sent"})  # fmt: skip
            reasons.append(refused.value.reason)
            await online.stop()
            return reply, online, reasons + [r.path for r in server.requests]

    (tmp_path / "public").mkdir()
    (tmp_path / "impostor").mkdir()
    with offline_run() as egress:  # loopback only: the private address is dialled at the local stand-in
        reply, online, seen = run(scenario())
    assert egress.attempts == []
    assert reply.status == 200
    assert seen == ["host_not_allowed", "payload_class_not_allowed", "feature_off", "feature_off",
                    "not_private_address", "pin_mismatch", "/v1/lan/hello"]  # fmt: skip
    rows = online.device.execute("SELECT feature, destination, payload_class FROM egress_ledger").fetchall()
    assert rows == [("lan_compute", lan_ip, "lan_session")]


def arc06_policy_refuses_unlisted_egress(tmp_path: Path) -> None:
    """A disabled feature, a wrong host, a disallowed payload class or plain HTTP is refused before any lookup and
    logged with the feature and reason only."""

    async def scenario() -> tuple[Any, Any]:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            enable(online, "update_checks")
            online.connectivity.features_changed()
            await online.connectivity.check()
            cases = [
                ("telemetry", f"https://{HOSTS['telemetry']}/v1/agg", "telemetry_aggregate", "feature_off"),
                ("update_checks", "https://example.org/v1/check", "update_check", "host_not_allowed"),
                ("update_checks", f"https://{HOSTS['gateway']}/v1/check", "update_check", "host_not_allowed"),
                ("update_checks", f"https://{HOSTS['updates']}/v1/check", "cloud_prompt", "payload_class_not_allowed"),
                ("update_checks", f"http://{HOSTS['updates']}/v1/check", "update_check", "plain_http"),
                ("cloud_voice", f"https://{HOSTS['voice']}/v1/x", "voice_stream", "stage_not_shipped"),
            ]
            for feature, url, payload, reason in cases:
                with pytest.raises(EgressRefused) as refused:
                    await online.client.send(feature, "POST", url, payload, body={"secret": "kept"})
                assert refused.value.reason == reason, (feature, url, refused.value.reason)
            await online.stop()
            return online, [r.path for r in server.requests]

    with offline_run() as egress:
        online, paths = run(scenario())
    assert egress.attempts == []
    assert paths == ["/v1/ping"]  # the probe of the one enabled feature, nothing else
    assert [(r["feature"], r["reason"]) for r in online.client.refusals] == [
        ("telemetry", "feature_off"), ("update_checks", "host_not_allowed"), ("update_checks", "host_not_allowed"),
        ("update_checks", "payload_class_not_allowed"), ("update_checks", "plain_http"),
        ("cloud_voice", "stage_not_shipped")]  # fmt: skip
    assert all(set(r) == {"at", "feature", "reason"} for r in online.client.refusals)  # no address, no content


# --- ARC-07 -------------------------------------------------------------------------------------------------------


def arc07_policy_matches_feature_table() -> None:
    policy = load_policy()
    rows = _arc07_rows()
    table = {}
    for row in rows:
        ids = re.findall(r"`([a-z_]+)`", row[0])
        if ids:
            table[ids[0]] = (row[1].split()[0], row[2])
    assert set(policy.features) == set(table), "the policy's features are exactly TABLE ARC-07a's"
    for feature, (stage, leaves) in table.items():
        row = policy.features[feature]
        assert row.stage == stage, feature
        for named in re.findall(r"payload class `([a-z_]+)`", leaves):
            assert named in row.payload_classes, (feature, named)
        for env, hosts in policy.services.items():
            assert row.service in hosts, (feature, env)
    # The same ids everywhere they are listed: consents, the device schema, the event contract.
    assert consent_store.FEATURES == {f: r.stage for f, r in policy.features.items()}
    checked = re.search(r"feature\s+TEXT\s+PRIMARY KEY CHECK \(feature IN \((.*?)\)\)", DEVICE, re.S)
    assert checked is not None and set(re.findall(r"'([a-z_]+)'", checked.group(1))) == set(policy.features)
    assert set(document("api/events")["$defs"]["online_feature"]["enum"]) == set(policy.features)
    # Only authenticated features may carry the service credential (SEC-21).
    assert {f for f, r in policy.features.items() if not r.authenticated} == {
        "downloads", "update_checks", "telemetry", "crash_reports"}  # fmt: skip


def arc07_each_feature_offline_equivalent(tmp_path: Path) -> None:
    """With the network cut, each shipped feature takes its offline equivalent: the cloud tier is skipped by the
    router (MDL-24, tested in M19.c), downloads and update checks are refused so the USB paths apply, and telemetry
    and crash reports queue in the outbox."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            enable(online, *load_policy().shipped())
            online.connectivity.features_changed()
            await online.connectivity.check()
            assert online.connectivity.state == "online"
            online.connectivity.os_hint(online=False)  # the cable is pulled
            outcomes = {}
            for feature in ("downloads", "update_checks", "cloud_tier"):
                row = load_policy().features[feature]
                with pytest.raises(EgressRefused) as refused:
                    await online.client.send(feature, "GET", f"https://{online.host_for(feature)}/x",
                                             row.payload_classes[0])  # fmt: skip
                outcomes[feature] = (refused.value.reason, row.queued)
            for kind, feature in (("telemetry", "telemetry"), ("crash_report", "crash_reports")):
                online.outbox.put(
                    kind,
                    feature,
                    telemetry_payload() if kind == "telemetry" else b"{}",
                    expires_ms=online.clock_ms() + DAY_MS,
                )
            outcomes["drained"] = await online.drain_once()
            outcomes["queued"] = online.outbox.counts()
            outcomes["sent"] = [r.path for r in server.requests]
            await online.stop()
            return outcomes

    with offline_run() as egress:
        outcomes = run(scenario())
    assert egress.attempts == []
    assert outcomes["downloads"] == ("offline", "resume")
    assert outcomes["update_checks"] == ("offline", "next_check")
    assert outcomes["cloud_tier"] == ("offline", "never")  # never queued: the router serves it locally
    assert outcomes["drained"] == 0 and outcomes["queued"] == {"telemetry": 1, "crash_reports": 1}
    assert outcomes["sent"] == ["/v1/ping"]


# --- ARC-08 -------------------------------------------------------------------------------------------------------


def arc08_state_transitions(tmp_path: Path) -> None:
    outcomes: list[str] = []
    probed: list[str] = []

    async def probe(host: str) -> str:
        probed.append(host)
        return outcomes.pop(0)

    async def scenario() -> list[tuple[str, int]]:
        online = layer(tmp_path, probe=probe)
        state = online.connectivity
        seen = [(state.state, state.probes)]
        state.os_hint(online=True)
        await state.check()  # everything off: no probe
        seen.append((state.state, state.probes))
        enable(online, "update_checks")
        online.connectivity.features_changed()
        seen.append((state.state, state.probes))
        for outcome in ("ok", "failed", "failed", "captive", "tls_failure", "ok"):
            outcomes.append(outcome)
            await state.check()
            seen.append((state.state, state.probes))
        delays = state.next_delay_s()
        state.os_hint(metered=True)
        seen.append((state.state, state.probes))
        state.os_hint(online=False)
        seen.append((state.state, state.probes))
        await state.check()  # no route: offline without a probe
        seen.append((state.state, state.probes))
        enable(online, "update_checks", on=False)
        online.connectivity.features_changed()
        state.os_hint(online=True)
        await state.check()
        seen.append((state.state, state.probes))
        await online.stop()
        assert delays == Settings().net_probe_interval_s
        return seen

    assert run(scenario()) == [
        ("off", 0), ("off", 0), ("unknown", 0),
        ("online", 1), ("offline", 2), ("offline", 3), ("limited", 4), ("limited", 5), ("online", 6),
        ("metered", 6), ("offline", 6), ("offline", 6), ("off", 6),
    ]  # fmt: skip
    assert set(probed) == {HOSTS["updates"]}, "probes go only to an enabled feature's host"
    # Backoff while offline: doubling from the interval, capped (TABLE ARC-08a proposal values).
    conn = Connectivity(lambda: {"telemetry"}, lambda: "h", probe, interval_s=60, backoff_max_s=900)
    for _ in range(6):
        outcomes.append("failed")
        run(conn.check())
    assert conn.next_delay_s() == 900


def test_large_downloads_pause_while_metered_is_the_shell_rule() -> None:
    """ARC-08's metered effect belongs to the shell's download transport (apps/desktop net.rs, M20.b); the core's
    resolved policy carries the state it needs."""
    resolved = load_policy().resolve("dev", {"downloads"}, network="metered")
    assert resolved.document()["network"] == "metered"


# --- ARC-09, DAT-11 -----------------------------------------------------------------------------------------------


def arc09_outbox_exactly_once_across_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            first = layer(tmp_path, server)
            enable(first, "telemetry")
            first.connectivity.features_changed()
            first.connectivity.os_hint(online=False)
            for n in range(3):
                first.outbox.put("telemetry", "telemetry", telemetry_payload(n),
                                 expires_ms=first.clock_ms() + DAY_MS)  # fmt: skip
            assert await first.drain_once() == 0 and server.requests == []
            await first.stop()
            # Restart: a new core on the same device database.
            device = open_local(tmp_path / "data", app_version="0.0.0", now_ms=1_760_000_000_000).device
            second = layer(tmp_path, server, device=device)
            await second.connectivity.check()
            assert await second.drain_once() == 3
            # A crash between the send and its "delivered" mark: the next start sends again with the same key.
            second.outbox.put("telemetry", "telemetry", telemetry_payload(3), expires_ms=second.clock_ms() + DAY_MS)
            real = store.delivered
            monkeypatch.setattr(store, "delivered", lambda *a: (_ for _ in ()).throw(RuntimeError("power cut")))
            with pytest.raises(RuntimeError):
                await second.drain_once()
            monkeypatch.setattr(store, "delivered", real)
            await second.stop()
            third = layer(tmp_path, server, device=device)
            await third.connectivity.check()
            again = await third.drain_once()
            await third.stop()
            return server, again, store.pending(device)

    server, again, left = run(scenario())
    posts = [r for r in server.requests if r.path.startswith("/v1/outbox/")]
    assert again == 1 and left == []
    assert len(posts) == 5, "the interrupted item was sent twice..."
    assert sorted(json.loads(p)["metrics"]["model_calls"]["sum"] for p in server.delivered.values()) == [0, 1, 2, 3], (
        "...and applied once"
    )


def arc09_disable_feature_purges_queue(tmp_path: Path) -> None:
    async def scenario() -> Any:
        online = layer(tmp_path)
        enable(online, "telemetry", "cloud_tier")
        expires = online.clock_ms() + DAY_MS
        for n in range(3):
            online.outbox.put("telemetry", "telemetry", telemetry_payload(n), expires_ms=expires)
        online.outbox.put("consent_withdrawal", "telemetry", b"w", expires_ms=expires)
        online.outbox.put("tombstone", "telemetry", b"t", expires_ms=expires)
        consent_store.queue_withdrawal(online.device, "PROFILE", "cloud_tier", online.clock_ms(), expires)
        enable(online, "telemetry", on=False)
        await online.switched({"telemetry": False})  # the PATCH handler awaits this before it answers
        kinds = sorted((i.feature, i.kind) for i in store.pending(online.device))
        await online.stop()
        return kinds

    assert run(scenario()) == [("cloud_tier", "consent_withdrawal"), ("telemetry", "consent_withdrawal"),
                               ("telemetry", "tombstone")]  # fmt: skip


def dat11_offline_flows_queue(tmp_path: Path) -> None:
    """Offline, the online side effects of student-facing flows land in the outbox and nothing is sent; they go out
    once the network is back."""

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            enable(online, "telemetry", "crash_reports", "cloud_tier")
            online.connectivity.os_hint(online=False)
            expires = online.clock_ms() + DAY_MS
            # A consent withdrawn while offline (PRV-05), a crash report the adult approved, the day's counters.
            consent_store.queue_withdrawal(online.device, "PROFILE", "cloud_tier", online.clock_ms(), expires)
            online.outbox.put("crash_report", "crash_reports", b"{}", expires_ms=expires)
            online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=expires)
            queued = dict(online.outbox.counts())
            sent_offline = list(server.requests)
            online.connectivity.os_hint(online=True)
            await online.connectivity.check()
            delivered = await online.drain_once()
            await online.stop()
            return queued, sent_offline, delivered, online.outbox.counts()

    with offline_run() as egress:  # the scenario dials only the loopback stand-in
        queued, sent_offline, delivered, after = run(scenario())
    assert egress.attempts == []
    assert queued == {"cloud_tier": 1, "crash_reports": 1, "telemetry": 1}
    assert sent_offline == [] and delivered == 3 and after == {}


def dat11_disable_purges_except_tombstones(tmp_path: Path) -> None:
    async def scenario() -> Any:
        online = layer(tmp_path)
        enable(online, "telemetry")
        expires = online.clock_ms() + DAY_MS
        online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=expires)
        online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=expires)
        online.outbox.put("tombstone", "telemetry", b"t", expires_ms=expires)
        enable(online, "telemetry", on=False)
        await online.switched({"telemetry": False})
        left = [i.kind for i in store.pending(online.device)]
        await online.stop()
        return left

    assert run(scenario()) == ["tombstone"]


def test_outbox_caps_expiry_and_backoff(tmp_path: Path) -> None:
    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            server.handlers["/v1/outbox/crash_report"] = lambda seen: (503, {"error": {"message": "busy"}})
            settings = Settings(outbox_cap_mb=1)
            online = layer(tmp_path, server, settings=settings)
            enable(online, "telemetry", "crash_reports")
            await online.connectivity.check()
            big = telemetry_payload(series_count=1400)
            for _ in range(4):
                online.outbox.put("telemetry", "telemetry", big, expires_ms=online.clock_ms() + DAY_MS)
            capped = store.total_bytes(online.device)
            online.outbox.put("crash_report", "crash_reports", b"{}", expires_ms=online.clock_ms() + DAY_MS)
            online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=online.clock_ms() - 1)
            await online.drain_once()
            crash = store.pending(online.device, "crash_reports")[0]
            note = online.device.execute("SELECT payload_class FROM egress_ledger WHERE bytes = 0").fetchall()
            await online.stop()
            return capped, crash, note, online.clock_ms()

    capped, crash, note, now = run(scenario())
    assert capped <= 1024 * 1024
    assert crash.attempts == 1 and crash.next_attempt_at is not None
    assert now + 15_000 <= crash.next_attempt_at <= now + 45_000 + 1000  # 30 s with jitter
    assert note == [("expired_unsent",)]


# --- PRV-02 -------------------------------------------------------------------------------------------------------


def prv02_fresh_install_zero_egress(tmp_path: Path) -> None:
    """A fresh install through onboarding, a scripted session and closing: with the core's connectivity layer
    attached and running, no outbound connection and no lookup."""
    from api_harness import ask, cli, start_core, stop_core

    async def scenario() -> Any:
        r = await start_core(tmp_path, worker=False)
        online = r.runtime.attach_online()
        r.core.online = online
        online.start()
        try:
            state = (await r.get("/v1/connectivity")).json()
            assert all(not f["enabled"] for f in state["features"].values()) and state["network"] == "off"
            sid = await r.session()
            for text in ("Hello", "What is speed?", "Thanks"):
                await r.post(f"/v1/sessions/{sid}/turns", ask(text))
                await r.wait_idle(sid)
            await r.post(f"/v1/sessions/{sid}/archive", {"client_request_id": cli()})
            ledger = online.device.execute("SELECT count(*) FROM egress_ledger").fetchone()[0]
            return online, ledger
        finally:
            await stop_core(r)
            await online.stop()

    with offline_run() as egress:
        online, ledger = run(scenario())
    assert egress.attempts == []
    assert online.connectivity.probes == 0 and ledger == 0


def prv02_disable_stops_traffic(tmp_path: Path) -> None:
    """Switching a feature off stops its traffic at once: the request in flight ends, nothing more is sent, within
    the configured budget."""
    settings = Settings()

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            enable(online, "telemetry", "update_checks")
            await online.connectivity.check()
            stall = asyncio.Event()

            def hold(seen: Any) -> Any:
                stall.set()
                return ("sse", [{"t": i} for i in range(10_000)], None)

            server.handlers["/v1/check"] = hold
            stream = online.client.stream_events("update_checks", f"https://{HOSTS['updates']}/v1/check",
                                                 "update_check", {})  # fmt: skip
            got = 0

            async def consume() -> str:
                nonlocal got
                try:
                    async for _ in stream:
                        got += 1
                        await asyncio.sleep(0.001)
                except EgressRefused as refused:
                    return refused.reason
                return "finished"

            task = asyncio.ensure_future(consume())
            await stall.wait()
            await asyncio.sleep(0.05)
            started = asyncio.get_running_loop().time()
            enable(online, "update_checks", on=False)
            await online.switched({"update_checks": False})
            reason = await asyncio.wait_for(task, settings.cloud_disable_all_budget_s)
            took = asyncio.get_running_loop().time() - started
            before = len(server.requests)
            with pytest.raises(EgressRefused):
                await online.client.send("update_checks", "GET", f"https://{HOSTS['updates']}/v1/check",
                                         "update_check")  # fmt: skip
            after = len(server.requests)
            await online.stop()
            return reason, took, before, after, got

    reason, took, before, after, got = run(scenario())
    assert got > 0 and reason == "feature_off"
    assert took < Settings().cloud_disable_all_budget_s
    assert before == after


def test_disable_mid_request_ends_a_plain_send(tmp_path: Path) -> None:
    async def scenario() -> Any:
        online = layer(tmp_path)
        client: EgressClient = online.client
        enable(online, "telemetry")
        online.connectivity.state = "online"
        gate = asyncio.Event()

        async def never(*_: Any) -> Any:
            await gate.wait()

        client._request = never  # type: ignore[method-assign]
        task = asyncio.ensure_future(client.send("telemetry", "POST", f"https://{HOSTS['telemetry']}/v1/agg",
                                                 "telemetry_aggregate", content=telemetry_payload()))  # fmt: skip
        await asyncio.sleep(0.01)
        assert client.in_flight("telemetry") == 1
        await online.switched({"telemetry": False})
        with pytest.raises(EgressRefused) as refused:
            await task
        await online.stop()
        return refused.value.reason

    assert run(scenario()) == "feature_off"
