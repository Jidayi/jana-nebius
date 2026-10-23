"""INP-30 request fixtures validated at the real local HTTP boundary; no recognition/model claims."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import httpx
from agent_core.api.app import create_app
from agent_core.api.security import LaunchSecret
from agent_core.contracts import errors
from agent_core.engine.events import new_id
from jana_tools import REPO_ROOT
from test_m21_capture_drafts import setup

COMMANDS = "api/commands"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/capture-endpoints.json").read_text())


def inp30_capture_endpoint_fixtures(tmp_path: Path) -> None:
    async def check() -> None:
        core, engine, old_desk, sid = setup(tmp_path)
        app = create_app(core, LaunchSecret("synthetic-fixture-secret"), lambda: 8787)
        desk = core.capture_desk
        endpoints = {
            (e["method"], e["path"]): e
            for e in json.loads((REPO_ROOT / "docs/specification/contracts/api/commands.schema.json").read_text())[
                "x-endpoints"
            ]
            if e["path"].startswith("/v1/captures")
        }
        seen: set[tuple[str, str]] = set()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8787",
            headers={"authorization": "Bearer synthetic-fixture-secret", "origin": "tauri://localhost"},
        ) as client:

            async def call(
                method: str,
                template: str,
                path: str,
                body: dict | None = None,
                key: str | None = None,
                expected: int = 200,
            ) -> httpx.Response:
                endpoint = endpoints[(method, template)]
                if endpoint["request"]:
                    assert errors(COMMANDS + endpoint["request"], body) == []
                headers = {"idempotency-key": key or new_id("cli")}
                response = await client.request(method, path, json=body, headers=headers)
                assert response.status_code == expected, response.text
                if endpoint["response"]:
                    assert errors(COMMANDS + endpoint["response"], response.json()) == []
                elif expected == 204:
                    assert response.content == b""
                seen.add((method, template))
                return response

            try:
                meta = {**FIXTURES["create"], "client_capture_id": new_id("cli"), "session_id": sid}
                assert errors(COMMANDS + "#/$defs/CreateCapture", meta) == []
                raw = (
                    Path(__file__).resolve().parents[3] / "packages/ui/gallery/photo-source-fixture.jpg"
                ).read_bytes()

                async def create(data: bytes = raw) -> httpx.Response:
                    return await client.post(
                        "/v1/captures",
                        files={"meta": (None, json.dumps(meta)), "file": ("synthetic.jpg", data, "image/jpeg")},
                        headers={"idempotency-key": meta["client_capture_id"]},
                    )

                response = await create()
                assert (
                    response.status_code == 200 and errors(COMMANDS + "#/$defs/CapturedQuestion", response.json()) == []
                )
                seen.add(("POST", "/v1/captures"))
                cap = response.json()["capture_id"]
                assert (await create()).json() == response.json()
                conflict = await create(raw + b"different")
                assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "request_conflict"
                path = f"/v1/captures/{cap}"
                await call("GET", "/v1/captures/{capture_id}", path)
                preview = await call(
                    "PATCH",
                    "/v1/captures/{capture_id}/crop",
                    path + "/crop",
                    {**FIXTURES["crop"], "preview_only": True},
                )
                assert len(preview.json()["outline"]) == 4 and preview.json()["attachments"] == []
                crop = await call("PATCH", "/v1/captures/{capture_id}/crop", path + "/crop", FIXTURES["crop"])
                image = crop.json()["attachments"][0]
                data = await client.get(path + "/images/" + image["image_id"])
                assert data.headers["content-type"] == "image/jpeg"
                assert hashlib.sha256(data.content).hexdigest() == image["sha256"]
                key = new_id("cli")
                read = await call("POST", "/v1/captures/{capture_id}/read", path + "/read", FIXTURES["read"], key, 202)
                await asyncio.gather(*list(desk.tasks.values()))
                assert (
                    await call("POST", "/v1/captures/{capture_id}/read", path + "/read", FIXTURES["read"], key, 202)
                ).json() == read.json()
                assert engine.calls == 1
                ready = (await call("GET", "/v1/captures/{capture_id}", path)).json()
                edits = copy.deepcopy(ready["regions"])
                edits[0]["text"] = FIXTURES["confirm"]["text"]
                confirmed = await call(
                    "POST",
                    "/v1/captures/{capture_id}/confirm",
                    path + "/confirm",
                    {**FIXTURES["confirm"], "regions": edits},
                )
                assert confirmed.json()["confirmation"]["edit_distance"] > 0
                assert confirmed.json()["regions"][0]["text"] == FIXTURES["confirm"]["text"]
                assert not core.app_channel.rejected
                frames = core.app_channel.ring.after(0)
                assert frames and all(b'"text"' not in frame for frame in frames)
                for frame in frames:
                    envelope = json.loads(frame.decode().split("data: ", 1)[1].strip())
                    assert errors("api/events", envelope) == []
                for suffix, method, fixture in [
                    ("/crop", "PATCH", FIXTURES["crop"]),
                    ("/read", "POST", FIXTURES["read"]),
                    ("/confirm", "POST", FIXTURES["confirm"]),
                ]:
                    bad = await client.request(
                        method,
                        path + suffix,
                        json={**fixture, "unexpected": True},
                        headers={"idempotency-key": new_id("cli")},
                    )
                    assert bad.status_code == 422 and errors(COMMANDS + "#/$defs/error_envelope", bad.json()) == []
                assert (await client.get(path, headers={"authorization": "Bearer wrong"})).status_code == 401
                await call("DELETE", "/v1/captures/{capture_id}", path, expected=204)
                assert not list((tmp_path / "attachments").glob("*.jpg"))
                missing = await client.get(path)
                assert missing.status_code == 404 and errors(COMMANDS + "#/$defs/error_envelope", missing.json()) == []
                # Binary image responses have their own hash/MIME assertion; all five JSON/mutation rows are covered.
                required = {(m, p) for m, p in endpoints if "/images/" not in p}
                assert seen == required
            finally:
                await desk.close()
                await old_desk.close()
                core.store.conn.close()

    asyncio.run(check())
