"""A loopback stand-in for `llama-server` (router mode), for tests and cassette replay.

It speaks the endpoints the adapter uses (`/health`, `/v1/models`, `/props`, `/v1/chat/completions`, plain and
streamed), checks the per-launch key, and answers each chat request with the next step of its script: a recorded
reply, a recorded stream, an HTTP error, a stall or a dropped connection. It never touches the network beyond
127.0.0.1.

Run as a process (`python -m jana_tools.fakes.llama_server <llama-server arguments>`) it stands in for the runtime
the shell supervises: it takes the port, key file and models folder from llama-server's own flags, ignores the
others, and answers every chat request with a short reply. Killing it is a runtime crash. Test-only flags stand in
for the ways a real build fails or measures (PLT-04, PLT-08):

    --list-devices                  print llama-server's device list (`--fake-device` lines, none by default) and exit
    --fake-device "Vulkan0: <name> (<total> MiB, <free> MiB free)"   one device line, repeatable
    --fake-crash-on-generation      die with SIGSEGV on the first generation, as a broken GPU driver does
    --fake-generation-tokens-s N    the generation speed `/completion` reports (the benchmark's probe)"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Step = dict[str, Any]


def default_props(model: str, n_ctx: int = 8192) -> dict[str, Any]:
    return {
        "default_generation_settings": {"n_ctx": n_ctx},
        "model_alias": model,
        "modalities": {"vision": False},
        "chat_template": "{%- if enable_thinking is defined %}<think>{% endif %}",
        "chat_template_caps": {"supports_tools": True, "supports_parallel_tool_calls": True},
    }


@dataclass
class FakeLlamaServer:
    models: list[str]
    api_key: str = "test-launch-key"
    script: list[Step] | Callable[[dict[str, Any]], Step] = field(default_factory=list)
    props: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    erased: list[tuple[str, int]] = field(default_factory=list)  # (model, slot) whose KV cache was erased
    healthy: bool = True
    # What `/completion` reports as the runtime's own timings (the PLT-08 benchmark reads them).
    timings: dict[str, float] = field(default_factory=lambda: {"prompt_per_second": 120.0,
                                                               "predicted_per_second": 20.0})  # fmt: skip
    crash_on_generation: bool = False
    port: int = 0
    _server: asyncio.Server | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> FakeLlamaServer:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> FakeLlamaServer:
        return await self.start()

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _next(self, body: dict[str, Any]) -> Step:
        self.requests.append(body)
        if callable(self.script):
            return self.script(body)
        if not self.script:
            return {"status": 500, "body": {"error": {"message": "script exhausted"}}}
        return self.script.pop(0)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in lines[1:] if h)}
            length = int(headers.get("content-length", "0"))
            body = json.loads(await reader.readexactly(length)) if length else {}
            path = target.split("?", 1)[0]
            if path == "/health":
                await self._json(writer, 200 if self.healthy else 503, {"status": "ok" if self.healthy else "loading"})
            elif path == "/v1/models":
                await self._json(writer, 200, {"data": [{"id": m, "object": "model"} for m in self.models]})
            elif headers.get("authorization") != f"Bearer {self.api_key}":
                await self._json(writer, 401, {"error": {"message": "Invalid API Key", "type": "authentication_error"}})
            elif path == "/props":
                model = target.partition("model=")[2] or self.models[0]
                await self._json(writer, 200, self.props.get(model) or default_props(model))
            elif path == "/slots" and method == "GET":
                await self._json(writer, 200, [{"id": 0, "n_ctx": 8192}, {"id": 1, "n_ctx": 8192}])
            elif path.startswith("/slots/") and method == "POST" and "action=erase" in target:
                self.erased.append((target.partition("model=")[2], int(path.rsplit("/", 1)[1])))
                await self._json(writer, 200, {"id_slot": int(path.rsplit("/", 1)[1]), "n_erased": 1})
            elif path in ("/v1/chat/completions", "/completion") and self.crash_on_generation:
                os.kill(os.getpid(), signal.SIGSEGV)  # a driver crash on the first generation (PLT-04)
            elif path == "/completion" and method == "POST":
                await self._json(writer, 200, self._completion(body))
            elif path == "/v1/chat/completions" and method == "POST":
                await self._chat(writer, body)
            else:
                await self._json(writer, 404, {"error": {"message": "not found"}})
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def _completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """llama-server's native completion with its timings: prompt and generation speed for the benchmark."""
        self.requests.append(body)
        predicted = int(body.get("n_predict") or 16)
        prompt_tokens = max(1, len(str(body.get("prompt", ""))) // 4)
        prompt_rate, rate = self.timings["prompt_per_second"], self.timings["predicted_per_second"]
        return {"content": " ok" * predicted, "tokens_predicted": predicted, "tokens_evaluated": prompt_tokens,
                "timings": {"prompt_n": prompt_tokens, "prompt_ms": 1000 * prompt_tokens / prompt_rate,
                            "prompt_per_second": prompt_rate, "predicted_n": predicted,
                            "predicted_ms": 1000 * predicted / rate, "predicted_per_second": rate}}  # fmt: skip

    async def _chat(self, writer: asyncio.StreamWriter, body: dict[str, Any]) -> None:
        step = self._next(body)
        if "stall_s" in step:
            await asyncio.sleep(step["stall_s"])
        if step.get("drop"):
            writer.transport.abort()
            return
        if "status" in step:
            await self._json(writer, step["status"], step.get("body", {}), step.get("headers", {}))
            return
        if body.get("stream"):
            events = step.get("events") or _events_from(step["reply"])
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
            for event in events:
                writer.write(f"data: {json.dumps(event)}\n\n".encode())
                await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()
            return
        reply = step.get("reply") or _reply_from(step["events"])
        await self._json(writer, 200, reply)

    @staticmethod
    async def _json(
        writer: asyncio.StreamWriter, status: int, payload: Any, headers: dict[str, str] | None = None
    ) -> None:
        data = json.dumps(payload).encode()
        extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n{extra}"
            "Connection: close\r\n\r\n".encode()
            + data
        )
        await writer.drain()


def _events_from(reply: dict[str, Any]) -> list[dict[str, Any]]:
    choice = (reply.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    events: list[dict[str, Any]] = []
    for key in ("reasoning_content", "content"):
        text = message.get(key) or ""
        events += [{"choices": [{"delta": {key: text[i : i + 4]}}]} for i in range(0, len(text), 4)]
    for index, call in enumerate(message.get("tool_calls") or []):
        events.append({"choices": [{"delta": {"tool_calls": [{"index": index, **call}]}}]})
    events.append(
        {
            "choices": [{"delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
            "usage": reply.get("usage"),
            "timings": reply.get("timings"),
            "model": reply.get("model"),
        }
    )
    return events


def _reply_from(events: list[dict[str, Any]]) -> dict[str, Any]:
    content, reasoning, finish, usage = "", "", "stop", None
    calls: dict[int, dict[str, Any]] = {}
    for event in events:
        usage = event.get("usage") or usage
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            reasoning += delta.get("reasoning_content") or ""
            finish = choice.get("finish_reason") or finish
            for part in delta.get("tool_calls") or []:
                held = calls.setdefault(
                    part.get("index", 0), {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
                )
                held["id"] = part.get("id") or held["id"]
                function = part.get("function") or {}
                held["function"]["name"] += function.get("name") or ""
                held["function"]["arguments"] += function.get("arguments") or ""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}


def _process(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int)
    parser.add_argument("--api-key-file")
    parser.add_argument("--models-dir", default="")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--fake-device", action="append", default=[])
    parser.add_argument("--fake-crash-on-generation", action="store_true")
    parser.add_argument("--fake-generation-tokens-s", type=float, default=20.0)
    known, _ = parser.parse_known_args(argv)
    if known.list_devices:
        print("Available devices:")
        for line in known.fake_device:
            print(f"  {line}")
        return
    if known.port is None or known.api_key_file is None:
        parser.error("--port and --api-key-file are required")
    with open(known.api_key_file) as handle:
        key = handle.read().strip()
    folder = Path(known.models_dir) if known.models_dir else None
    models = sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder and folder.is_dir() else []
    models = models or ["fake-model"]

    def answer(body: dict[str, Any]) -> Step:
        message = {"role": "assistant", "content": "OK"}
        return {"reply": {"model": body.get("model"), "choices": [{"message": message, "finish_reason": "stop"}]}}

    async def serve() -> None:
        server = FakeLlamaServer(models, api_key=key, script=answer, port=known.port,
                                 crash_on_generation=known.fake_crash_on_generation)  # fmt: skip
        server.timings["predicted_per_second"] = known.fake_generation_tokens_s
        await server.start()
        await asyncio.Event().wait()

    asyncio.run(serve())


if __name__ == "__main__":
    _process(sys.argv[1:])
