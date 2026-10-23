"""A scripted SSE event source replaying a recorded, contract-valid event stream."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ._validate import check


@dataclass
class ScriptedEventSource:
    """Replays `envelopes` in order; `after` resumes after a sequence number (Last-Event-ID)."""

    envelopes: list[dict[str, Any]]
    validate_contract: str = "api/events"
    _server: ThreadingHTTPServer | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        last: dict[tuple[str, str], int] = {}
        for i, envelope in enumerate(self.envelopes):
            check(self.validate_contract, envelope, f"envelope {i}")
            scope = (envelope["channel"], envelope["epoch"])
            if envelope["seq"] <= last.get(scope, 0):
                raise ValueError(f"envelope {i}: seq {envelope['seq']} is not increasing within its epoch")
            last[scope] = envelope["seq"]

    @classmethod
    def from_file(cls, path: Path) -> ScriptedEventSource:
        return cls(json.loads(path.read_text())["envelopes"])

    def events(self, after: int = 0) -> Iterator[dict[str, Any]]:
        return (e for e in self.envelopes if e["seq"] > after)

    def sse(self, after: int = 0) -> Iterator[str]:
        """SSE frames: `id` is the sequence number, `event` the channel, `data` the envelope."""
        for envelope in self.events(after):
            data = json.dumps(envelope, separators=(",", ":"))
            yield f"id: {envelope['seq']}\nevent: {envelope['channel']}\ndata: {data}\n\n"

    def serve(self) -> str:
        """Serve the stream at http://127.0.0.1:<port>/v1/events (loopback only); returns the URL."""
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                after = int(self.headers.get("Last-Event-ID") or 0)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for frame in source.sse(after):
                    self.wfile.write(frame.encode())
                    self.wfile.flush()

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1/events"

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
