"""A fake tool worker answering JSON-RPC from a recorded transcript (TOL-24 framing: one object per line).

Run as a process speaking stdio:  python -m jana_tools.fakes.worker <transcript.json>
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from ._validate import check


@dataclass
class FakeToolWorker:
    """`transcript` is a list of {"method": ..., "match": {param subset}, "result" | "error": ...}. A request is
    answered by the first unused entry whose method and params match; unmatched requests get a JSON-RPC error."""

    transcript: list[dict[str, Any]]
    used: set[int] = field(default_factory=set)

    @classmethod
    def from_file(cls, path: Path) -> FakeToolWorker:
        return cls(json.loads(path.read_text())["exchanges"])

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        check("tools/worker-protocol#/$defs/Request", request, "request")
        for i, entry in enumerate(self.transcript):
            params = request.get("params", {})
            if i in self.used or entry["method"] != request["method"]:
                continue
            if all(params.get(k) == v for k, v in entry.get("match", {}).items()):
                if entry.get("repeat") is not True:
                    self.used.add(i)
                body = {"error": entry["error"]} if "error" in entry else {"result": entry["result"]}
                response = {"jsonrpc": "2.0", "id": request["id"], **body}
                break
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32601, "message": f"no scripted answer for {request['method']}"},
            }
        check("tools/worker-protocol#/$defs/Response", response, "response")
        return response

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            response = self.handle(json.loads(line))
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()
            if json.loads(line).get("method") == "worker.shutdown":
                return


if __name__ == "__main__":
    FakeToolWorker.from_file(Path(sys.argv[1])).serve()
