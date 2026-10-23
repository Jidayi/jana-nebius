"""Recording real small-model replies as cassettes (M3 exit evidence), replayed in CI by `FakeLlamaServer`.

`python -m jana_tools cassettes --record <url> <key> <model> [--inline-think]` runs each synthetic scenario against a
running llama-server, once plain and once streamed, and writes the raw replies under evals/cassettes/models/. The
prompts are synthetic; nothing is a real student's work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from . import REPO_ROOT

CASSETTES = REPO_ROOT / "evals" / "cassettes" / "models"
PROVENANCE = "Synthetic prompts recorded against a local llama-server; replies are model output, not student data."
SOLVE_TOOL = {
    "type": "function",
    "function": {
        "name": "math_solve",
        "description": "Solves equations exactly.",
        "parameters": {
            "type": "object",
            "properties": {"equations": {"type": "array", "items": {"type": "string"}}},
            "required": ["equations"],
        },
    },
}
OFF = {"chat_template_kwargs": {"enable_thinking": False}}
ON = {"chat_template_kwargs": {"enable_thinking": True}}

SCENARIOS: dict[str, dict[str, Any]] = {
    "plain_text": {
        "messages": [{"role": "user", "content": "In one sentence, what is acceleration?"}],
        "max_tokens": 80,
        **OFF,
    },
    "thinking": {
        "messages": [{"role": "user", "content": "What is 12 times 7? Answer with the number."}],
        "max_tokens": 400,
        **ON,
    },
    "thinking_cut_off": {
        "messages": [{"role": "user", "content": "Explain why 0.1 + 0.2 is not exactly 0.3."}],
        "max_tokens": 40,
        **ON,
    },
    "tool_call": {
        "messages": [{"role": "user", "content": "Use the tool to solve 3x - 4 = 11."}],
        "tools": [SOLVE_TOOL],
        "max_tokens": 200,
        **OFF,
    },
    "tool_call_cut_off": {
        "messages": [{"role": "user", "content": "Use the tool to solve 3x - 4 = 11 and 2y = 9."}],
        "tools": [SOLVE_TOOL],
        "max_tokens": 14,
        **OFF,
    },
    "json_cut_off": {
        "messages": [
            {
                "role": "user",
                "content": 'Reply only with JSON like {"answer": 5, "unit": "m"} for a ball that rises 5 m.',
            }
        ],
        "max_tokens": 9,
        **OFF,
    },
}


def record(url: str, key: str, model: str, suffix: str = "", scenarios: list[str] | None = None) -> list[Path]:
    CASSETTES.mkdir(parents=True, exist_ok=True)
    written = []
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=300, trust_env=False) as client:
        build = client.get("/props", params={"model": model}).json().get("build_info", "")
        for name, scenario in SCENARIOS.items():
            if scenarios and name not in scenarios:
                continue
            request = {"model": model, "temperature": 0, "seed": 7, **scenario}
            reply = client.post("/v1/chat/completions", json=request).json()
            events = []
            with client.stream(
                "POST",
                "/v1/chat/completions",
                json={**request, "stream": True, "stream_options": {"include_usage": True}},
            ) as s:
                for line in s.iter_lines():
                    if line.startswith("data:") and line[5:].strip() != "[DONE]":
                        events.append(json.loads(line[5:]))
            path = CASSETTES / f"{model}{suffix}.{name}.json"
            path.write_text(
                json.dumps(
                    {
                        "provenance": PROVENANCE,
                        "model": model,
                        "server_build": build,
                        "scenario": name + suffix,
                        "request": request,
                        "reply": reply,
                        "events": events,
                    },
                    indent=1,
                    ensure_ascii=False,
                )
                + "\n"
            )
            written.append(path)
    return written


def load() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(CASSETTES.glob("*.json"))]
