"""A scripted model provider: returns the next scripted reply, validating structured replies against their
contract (for example the Coach's tutor turn), so engine code can be built and tested deterministically."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._validate import check


@dataclass
class ScriptedModelProvider:
    """`replies` is a list of {"role": model role, "content": text} or {"role", "contract", "json": object}."""

    replies: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for i, reply in enumerate(self.replies):
            if "contract" in reply:
                check(reply["contract"], reply["json"], f"scripted reply {i}")

    @classmethod
    def from_file(cls, path: Path) -> ScriptedModelProvider:
        return cls(json.loads(path.read_text())["replies"])

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """The next reply for the requesting role, as an OpenAI-style message (`content` is JSON text for a
        structured reply). Raises when the script is exhausted, so a test sees an unexpected extra call."""
        role = request.get("role")
        index = next((i for i, r in enumerate(self.replies) if r.get("role") == role and not r.get("_used")), None)
        if index is None:
            raise LookupError(f"no scripted reply left for role {role!r}")
        reply = self.replies[index]
        reply["_used"] = True
        self.calls.append(request)
        content = json.dumps(reply["json"]) if "contract" in reply else reply["content"]
        return {"role": "assistant", "content": content, "contract": reply.get("contract")}
