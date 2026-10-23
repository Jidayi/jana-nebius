"""OBS-22: the gateway keeps per-request metadata only, with a device hash that rotates daily and a retention
window; prompt and completion bodies are never stored or logged."""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from pathlib import Path

from gateway_stubs import Clock, Device, Output, gateway_config, harness, sse_payloads

METADATA_COLUMNS = {
    "id",
    "at",
    "day",
    "device_hash",
    "licence_id",
    "feature",
    "model",
    "tokens_in",
    "tokens_out",
    "tokens_cached",
    "latency_ms",
    "status",
    "outcome",
    "cost_usd",
}


def _rows(storage: Path, sql: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(storage / "gateway.sqlite3") as db:
        return list(db.execute(sql))


def obs22_gateway_stores_no_bodies(tmp_path: Path) -> None:
    storage, logs = tmp_path / "storage", tmp_path / "logs"
    prompt_canary = "PROMPTCANARY" + secrets.token_hex(8)
    reply_canary = "REPLYCANARY" + secrets.token_hex(8)
    tool_canary = "TOOLCANARY" + secrets.token_hex(8)
    clock = Clock()

    async def main() -> list[Device]:
        h = harness(gateway_config(storage, log_path=logs / "gateway.log"), clock)
        devices = [Device() for _ in range(4)]
        for n, device in enumerate(devices):
            await device.register(h.client, "lic_school_one" if n % 2 else "lic_school_two")
            await device.login(h.client)
        for n in range(200):
            device = devices[n % 4]
            slot = "primary" if n % 3 else "fallback"
            stream = n % 2 == 0
            stub = h.stubs[h.config.slots[slot]]
            if n % 10 == 7:
                stub.say(Output(tool=("record_step", {"working": f"{tool_canary} step {n}"})))
            elif n % 25 == 3:
                stub.say(Output(text=f"{reply_canary} partial", fail_mid_stream=True))
            else:
                stub.say(Output(text=f"Here is the next step {reply_canary} number {n}."))
            body = {
                "model": f"{slot}/strong-model",
                "stream": stream,
                "messages": [
                    {"role": "system", "content": "Tutor."},
                    {"role": "user", "content": f"My working {prompt_canary} for item {n}"},
                ],
            }
            reply = await device.chat(h.client, body)
            assert reply.status_code == 200, reply.text
            if stream:
                assert sse_payloads(reply.text)
            clock.now += 2
        sent = [s for stub in h.stubs.values() for s in stub.seen]
        assert len(sent) == 200 and all(prompt_canary in " ".join(s.user_texts) for s in sent)
        return devices

    devices = asyncio.run(main())

    # Every file the gateway wrote: the database (with its WAL and shared memory files) and the log.
    files = [p for p in [*storage.rglob("*"), *logs.rglob("*")] if p.is_file()]
    assert any(p.name == "gateway.sqlite3" for p in files) and any(p.name == "gateway.log" for p in files)
    secrets_and_bodies = [
        prompt_canary,
        reply_canary,
        tool_canary,
        "Tutor.",
        "Here is the next step",
        *(d.pseudonym for d in devices),
        *(d.token for d in devices),
    ]
    for path in files:
        data = path.read_bytes()
        for canary in secrets_and_bodies:
            assert canary.encode() not in data, f"{canary[:12]} found in {path.name}"
    assert "request licence=" in (logs / "gateway.log").read_text()

    columns = {row[1] for row in _rows(storage, "PRAGMA table_info(requests)")}
    assert columns == METADATA_COLUMNS
    rows = _rows(storage, "SELECT feature, model, tokens_in, tokens_out, cost_usd, outcome FROM requests")
    assert len(rows) == 200 and {r[0] for r in rows} == {"cloud_tier"}
    assert all(r[4] > 0 for r in rows if r[5] == "ok") and {r[5] for r in rows} == {"ok", "network_unavailable"}

    # The device hash rotates every day: the same credential cannot be linked across days.
    async def next_day() -> None:
        h = harness(gateway_config(storage), clock)
        device = devices[0]
        for _ in range(2):
            await device.login(h.client)
            h.stubs["gemini"].say(Output(text="ok"))
            assert (
                await device.chat(
                    h.client, {"model": "primary/fast-model", "messages": [{"role": "user", "content": "hi"}]}
                )
            ).status_code == 200
            clock.now += 86400

    clock.now += 86400
    asyncio.run(next_day())
    by_day = _rows(storage, "SELECT day, device_hash FROM requests WHERE model = 'gemini-stub-flash'")
    assert len(by_day) == 2 and by_day[0][0] != by_day[1][0] and by_day[0][1] != by_day[1][1]
    assert len(_rows(storage, "SELECT day FROM day_keys")) == 1  # earlier days' keys are gone


def test_metadata_retention(tmp_path: Path) -> None:
    clock = Clock()

    async def main() -> None:
        h = harness(gateway_config(tmp_path), clock)
        device = Device()
        await device.login(h.client)
        chat = {"model": "primary/fast-model", "messages": [{"role": "user", "content": "hi"}]}
        assert (await device.chat(h.client, chat)).status_code == 200
        clock.now += (h.config.metadata_retention_days + 1) * 86400
        await device.login(h.client)
        assert (await device.chat(h.client, chat)).status_code == 200

    asyncio.run(main())
    assert len(_rows(tmp_path, "SELECT id FROM requests")) == 1
