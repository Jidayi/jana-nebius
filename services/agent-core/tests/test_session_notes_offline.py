"""STU-14 software routing/queue evidence. The HTTP model is synthetic; hardware timing/packet capture are external."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.reflection import ReflectorModel
from agent_core.engine.session_notes import COLUMNS, note_of
from agent_core.providers.llama import LlamaServerProvider
from agent_core.providers.scripted import ScriptedProvider
from engine_harness import close, make_engine, reply
from jana_tools.harness.egress import offline_run
from test_session_notes import TEXT, seeded


@pytest.mark.parametrize("case", ["local", "pause_resume", "no_model", "local_failure"])
def stu14_offline_local_only(tmp_path: Path, case: str) -> None:
    async def scenario() -> None:
        requests: list[tuple[str, str, dict[str, Any]]] = []
        local_models = case != "no_model"
        busy = True
        first_call, release = asyncio.Event(), asyncio.Event()
        selection = {"statements": [{"evidence": 0, "section": "method"}]}

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                headers = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
                method, path, _ = headers[0].split(" ")
                values = dict(line.split(": ", 1) for line in headers[1:] if ": " in line)
                length = int(values.get("Content-Length", values.get("content-length", "0")))
                body = json.loads(await reader.readexactly(length)) if length else {}
                assert values.get("Authorization", values.get("authorization")) == "Bearer synthetic-local-key"
                requests.append((method, path, body))
                status = 200
                if path == "/v1/models":
                    value = (
                        {"data": [{"id": name} for name in ["qwen3-vl-8b", "gemma-4-12b"]]}
                        if local_models
                        else {"data": []}
                    )
                elif path.startswith("/props?"):
                    value = {
                        "chat_template_caps": {"supports_tools": True},
                        "default_generation_settings": {"n_ctx": 32768},
                    }
                else:
                    assert method == "POST" and path == "/v1/chat/completions", (method, path)
                    if case == "pause_resume" and not first_call.is_set():
                        first_call.set()
                        await release.wait()
                    if case == "local_failure":
                        status, value = 503, {"error": {"message": "Synthetic local runtime unavailable"}}
                    else:
                        value = {
                            "choices": [
                                {
                                    "message": {"role": "assistant", "content": json.dumps(selection)},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {"prompt_tokens": 8, "completion_tokens": 8},
                        }
                payload = json.dumps(value).encode()
                writer.write(
                    (
                        f"HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
                    ).encode()
                    + payload
                )
                with contextlib.suppress(ConnectionError):
                    await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()

        with offline_run() as monitor:
            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            provider = LlamaServerProvider(f"http://127.0.0.1:{port}", "synthetic-local-key", request_timeout_s=2)
            cloud = ScriptedProvider({"reflector": [reply(json.dumps(selection))]}, kind="cloud")

            def enabled(data: dict[str, Any]) -> None:
                data["cloud"]["enabled"] = True

            engine, _ = await make_engine(
                tmp_path / "engine", {}, worker=False, cloud=cloud, overrides=enabled, stage="S2"
            )
            conn, queue, _, _ = seeded(tmp_path)
            queue.busy = lambda: busy
            engine.deps.router.providers["local"] = provider
            # Fault injection after schema validation: runtime role policy still forbids cloud reflection.
            engine.deps.router.config.cloud["roles_allowed"].append("reflector")
            engine.deps.router.cloud_on = lambda _: True
            engine.deps.router.network = lambda: "online"  # Even an enabled cloud tier cannot receive note evidence.
            deps = engine.deps
            model = ReflectorModel(deps.router, deps.assets, deps.settings, deps.bundled_schemas, frozenset())
            queue.model = lambda: model
            events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
            try:
                queue.poll()
                assert conn.execute("SELECT state FROM session_notes").fetchone()[0] == "queued"
                assert queue.task is None and requests == []  # A foreground task holds the job without a model call.
                busy = False
                queue.poll()
                assert queue.task is not None
                if case == "pause_resume":
                    await asyncio.wait_for(first_call.wait(), 5)
                    busy = True
                    queue.poll()
                    await asyncio.gather(queue.task, return_exceptions=True)
                    assert queue.task.cancelled()
                    assert conn.execute("SELECT statements FROM session_notes").fetchone()[0] == "[]"
                    release.set()
                    busy = False
                    queue.poll()
                await asyncio.wait_for(queue.task, 5)  # Test hang guard, not a model/device timing qualification.
                if case == "no_model":
                    assert conn.execute("SELECT state FROM session_notes").fetchone()[0] == "no_model"
                    assert not [r for r in requests if r[0] == "POST"]
                    local_models = True
                    queue.poll()
                    await asyncio.wait_for(queue.task, 5)
                note = note_of(conn.execute(f"SELECT {COLUMNS} FROM session_notes").fetchone())  # noqa: S608 - fixed columns
                if case == "local_failure":
                    assert note["state"] == "failed" and note["statements"] == []
                else:
                    assert note["state"] == "ready" and note["statements"][0]["text"] == TEXT
                posts = [body for method, _, body in requests if method == "POST"]
                assert posts and all(
                    body["response_format"]["json_schema"]["name"] == "session_note_selection" for body in posts
                )
                assert all("REJECTED" not in json.dumps(body) and "DISCARDED" not in json.dumps(body) for body in posts)
                assert all(body["tools"] == [] for body in posts if "tools" in body)
                assert cloud.requests == []
                assert monitor.attempts == []
                assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == events
                assert conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
            finally:
                release.set()
                await queue.close()
                await provider.close()
                server.close()
                await server.wait_closed()
                await close(engine)
                conn.close()

    asyncio.run(scenario())
