"""D96: the voice sidecar starts early, in the background, only while the open profile has read-aloud on (VOC-23).
Synthetic signed pack bytes, an in-memory endpoint and synthetic profiles; no sidecar or model runs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent_core.api.voice_adapter import follow_read_aloud
from agent_core.net.voice import LocalVoiceEndpoint
from api_harness import cli, start_core, stop_core
from test_m31_voice_socket import Endpoint
from test_m32_voice_launch import setup as launch_setup


async def until(condition, seconds: float = 2) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.005)


def endpoint_for(start: dict) -> dict:
    return {
        "type": "control.voice_endpoint",
        "request_id": start["request_id"],
        "url": "ws://127.0.0.1:2345/v1/realtime",
        "token": "synthetic_" + "b" * 32,
    }


def starts(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f["type"] == "control.voice_start"]


def stops(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f["type"] == "control.voice_stop"]


def voc23_sidecar_prewarms_only_with_read_aloud(tmp_path: Path, monkeypatch):
    """Read-aloud on: the sidecar is requested before any use and no connection is opened; off: none until first use.
    Turning it off stops an early start nothing used, never one in use; a later use reuses the early start."""
    opened: list[Endpoint] = []

    async def open_socket(_):
        opened.append(Endpoint())
        return opened[-1]

    monkeypatch.setattr(LocalVoiceEndpoint, "open", open_socket)

    async def scenario():
        link, frames, _, _ = launch_setup(tmp_path)
        assert link.scan(manifest_only=True)
        link.want_warm(False)  # a profile with read-aloud off: nothing starts
        await asyncio.sleep(0.05)
        assert frames == []

        link.want_warm(True)  # opened with read-aloud on, or turned on
        await until(lambda: starts(frames))
        link.on_shell(endpoint_for(starts(frames)[0]))
        await until(lambda: link._endpoint is not None)
        assert opened == [] and not stops(frames)  # started, but no connection or session opened

        link.want_warm(True)  # told again (the settings saved twice): no second start
        await asyncio.sleep(0.05)
        assert len(starts(frames)) == 1

        link.want_warm(False)  # turned off before anything used it: the 2.6 GB voice is released
        assert stops(frames)[-1]["request_id"] == starts(frames)[0]["request_id"]

        link.want_warm(True)  # on again: a fresh early start, then the first read-aloud uses it
        await until(lambda: len(starts(frames)) == 2)
        link.on_shell(endpoint_for(starts(frames)[1]))
        await until(lambda: link._endpoint is not None)
        connection = await link.connect()
        assert len(starts(frames)) == 2 and len(opened) == 1  # the use reused the early start
        link.want_warm(False)  # in use now: turning read-aloud off never stops it
        assert len(stops(frames)) == 1
        await connection.close()

        await link.close()
        assert len(stops(frames)) == 2

    asyncio.run(scenario())


def test_early_start_stopped_while_loading_leaves_the_next_profile_its_own(tmp_path: Path):
    """Switching from one read-aloud profile to another while the voice loads: the first start is stopped with the
    profile, and the next profile's early start goes ahead rather than being lost behind it."""

    async def scenario():
        link, frames, _, _ = launch_setup(tmp_path, timeout=5)
        assert link.scan(manifest_only=True)
        link.want_warm(True)
        await until(lambda: starts(frames))
        link.want_warm(False)  # the profile closes while the sidecar loads
        link.want_warm(True)  # the next profile opens with read-aloud on
        await until(lambda: len(starts(frames)) == 2)
        assert stops(frames)[-1]["request_id"] == starts(frames)[0]["request_id"]
        link.on_shell(endpoint_for(starts(frames)[1]))
        await until(lambda: link._endpoint is not None)
        await link.close()

    asyncio.run(scenario())


def test_no_pack_or_content_only_never_starts_early(tmp_path: Path):
    async def scenario():
        link, frames, _, _ = launch_setup(tmp_path)
        link.want_warm(True)  # not scanned yet: no pack selected
        link.device_class = "content_only"
        assert link.scan(manifest_only=True) is False
        link.want_warm(True)
        await asyncio.sleep(0.05)
        assert frames == []
        await link.close()

    asyncio.run(scenario())


def test_a_pack_installed_with_read_aloud_on_starts_early(tmp_path: Path):
    async def scenario():
        link, frames, _, _ = launch_setup(tmp_path)
        link.want_warm(True)  # read-aloud on before any pack is offered
        await asyncio.sleep(0.05)
        assert frames == []
        assert link.rescan()  # the pack's install finished
        await until(lambda: starts(frames))
        await link.close()

    asyncio.run(scenario())


def test_profile_open_settings_change_and_lock_tell_the_voice(tmp_path: Path):
    """The core's wiring: opening a profile hears its read-aloud, a settings change hears the new value, and a lock
    says off, so a closed profile never keeps the voice loaded (D96, VOC-23)."""
    heard: list[bool] = []

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            follow_read_aloud(r.core, heard.append)

            async def call(method: str, path: str, body=None, profile: str | None = None):
                sent = r.headers(mutating=method != "GET")
                if method != "GET":
                    sent["idempotency-key"] = cli()
                if profile:
                    sent["x-profile-token"] = profile
                return await r.client.request(method, f"{r.base}{path}", headers=sent,
                                              content=None if body is None else json.dumps(body))  # fmt: skip

            made = await call("POST", "/v1/profiles", {"display_name": "Ama", "avatar": "disc-teal", "level": "O",
                                                       "subjects": ["physics"], "age_band": "13_15"})  # fmt: skip
            assert made.status_code == 200, made.text
            profile = made.json()["profile_id"]
            opened = await call("POST", f"/v1/profiles/{profile}/open", {})
            assert opened.status_code == 200, opened.text
            token = opened.json()["profile_token"]
            assert heard == [False]  # read-aloud is off by default (VOC-18)
            changed = await call("PATCH", f"/v1/profiles/{profile}/settings", {"read_aloud": True}, profile=token)
            assert changed.status_code == 200, changed.text
            assert heard[-1] is True
            closed = await call("POST", f"/v1/profiles/{profile}/close", {}, profile=token)
            assert closed.status_code == 204, closed.text
            assert heard[-1] is False
            reopened = await call("POST", f"/v1/profiles/{profile}/open", {})
            assert reopened.status_code == 200, reopened.text
            assert heard[-1] is True  # the saved preference starts the voice early at the next open
        finally:
            await stop_core(r)

    asyncio.run(scenario())
