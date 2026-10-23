"""Following one turn across processes, and the developer trace viewer (OBS-02, OBS-09, OBS-12).

`gather` reads every process's JSON-lines log in a directory and returns the lines of one turn: those carrying its
turn id and those carrying a call id the turn's lines name (worker JSON-RPC, runtime requests). `tier_diff` names the
prompt tiers whose fingerprints differ between two traces.

The viewer (`python -m jana_tools trace list|show|diff`) reads the trace store or an exported JSON file: a list of
turns with status and duration, a phase waterfall with model and tool calls, gate firings and skills loaded, and a
diff of two traces by fingerprint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def gather(log_dir: Path, turn_id: str) -> list[dict[str, Any]]:
    lines = []
    for path in sorted(log_dir.glob("*.jsonl")):
        for raw in path.read_text().splitlines():
            if raw.strip():
                lines.append(json.loads(raw))
    calls = {line["call_id"] for line in lines if line.get("turn_id") == turn_id and "call_id" in line}
    return [line for line in lines if line.get("turn_id") == turn_id or line.get("call_id") in calls]


def tier_diff(before: dict[str, Any], after: dict[str, Any], role: str | None = None) -> list[str]:
    changed = []
    pick = [p for p in before.get("prompts", []) if role is None or p["role"] == role]
    pair = [p for p in after.get("prompts", []) if role is None or p["role"] == role]
    for old, new in zip(pick, pair, strict=False):
        for a, b in zip(old["tiers"], new["tiers"], strict=False):
            if a["sha256"] != b["sha256"] and a["name"] not in changed:
                changed.append(a["name"])
    return changed


# --- the trace viewer (OBS-09) ----------------------------------------------------------------------------------------


def load(source: Path) -> list[dict[str, Any]]:
    """Trace records from the trace store (`traces.db`), a JSON list, or JSON lines, oldest first."""
    if source.suffix == ".db":
        import sqlite3

        conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT record FROM traces ORDER BY recorded_at, trace_id").fetchall()
        finally:
            conn.close()
        return [json.loads(r[0]) for r in rows]
    text = source.read_text()
    if text.lstrip().startswith("["):
        records: list[dict[str, Any]] = json.loads(text)
        return records
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def listing(traces: list[dict[str, Any]]) -> list[str]:
    """One line per turn: id, start, kind, mode, status, duration, model and tool calls."""
    lines = []
    for t in traces:
        flag = " degraded" if t.get("degraded") else ""
        lines.append(
            f"{t['trace_id']}  {t['started_at']}  {t['kind']:<4} {t.get('mode', '-'):<14} {t['status']:<11}"
            f"{t['duration_ms']:>7} ms  models {len(t['model_calls']):>2}  tools {len(t['tool_calls']):>2}{flag}"
        )
    return lines


def _bar(offset: int, duration: int, total: int, width: int = 40) -> str:
    total = max(total, 1)
    start = min(width - 1, offset * width // total)
    length = max(1, duration * width // total)
    return " " * start + "█" * min(length, width - start)


def waterfall(trace: dict[str, Any]) -> list[str]:
    """Phases as bars on the turn's timeline, then model calls, tool calls, gate firings and skills loaded."""
    total = int(trace["duration_ms"])
    out = [f"turn {trace.get('turn_id', '-')} · {trace['status']} · {total} ms · mode {trace.get('mode', '-')}"]
    for phase in trace["phases"]:
        verdict = f" ({phase['verdict']})" if phase.get("verdict") else ""
        bar = _bar(phase["start_offset_ms"], phase["duration_ms"], total)
        out.append(f"  {phase['phase']:<16}#{phase['iteration']} |{bar:<40}| {phase['duration_ms']} ms{verdict}")
    for call in trace["model_calls"]:
        reason = f" after {call['reason']}" if call.get("reason") else ""
        fallback = f" (fallback from {call['fallback_from']})" if call.get("fallback_from") else ""
        out.append(f"  model {call['role']:<8} {call['tier']:<6} {call['model_served']:<20} attempt {call['attempt']}"
                   f" {call['latency']['total_ms']} ms {call['finish_reason']}{reason}{fallback}")  # fmt: skip
    for call in trace["tool_calls"]:
        out.append(f"  tool  {call['name']:<24} {call['status']:<8} {call.get('duration_ms', 0)} ms"
                   f"{' ' + call['check_id'] if call.get('check_id') else ''}")  # fmt: skip
    for gate in trace["gates"]:
        if gate.get("fired"):
            out.append(f"  gate  {gate['gate']:<24} fired, {gate.get('nudges', 0)} nudge(s), {gate['outcome']}")
    for skill in trace.get("skills", []):
        out.append(f"  skill {skill['name']} {skill['version']} ({skill['delivery']})")
    return out


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """What changed between two traces, by fingerprint: prompt tiers per role, skill versions, tool schemas and
    models served ("prompt tier 3 guidance changed"; "skill `phy-o-motion` 1.3 → 1.4")."""
    out: list[str] = []
    # A role can make several requests in one turn, each with its own prompt (PRM-13): the nth request of a role is
    # compared with the nth request of that role in the first trace.
    old_prompts: dict[str, list[dict[str, Any]]] = {}
    for prompt in before.get("prompts", []):
        old_prompts.setdefault(prompt["role"], []).append(prompt)
    seen: dict[str, int] = {}
    for prompt in after.get("prompts", []):
        index = seen[prompt["role"]] = seen.get(prompt["role"], -1) + 1
        olds = old_prompts.get(prompt["role"], [])
        if index >= len(olds):
            out.append(f"{prompt['role']}: no prompt in the first trace" if not olds else
                       f"{prompt['role']}: request {index + 1} not in the first trace")  # fmt: skip
            continue
        old = olds[index]
        old_tiers = {t["name"]: t for t in old["tiers"]}
        for tier in prompt["tiers"]:
            previous = old_tiers.get(tier["name"])
            if previous is None:
                out.append(f"{prompt['role']}: prompt tier {tier['tier']} {tier['name']} added")
            elif previous["sha256"] != tier["sha256"]:
                out.append(f"{prompt['role']}: prompt tier {tier['tier']} {tier['name']} changed")
        for name in sorted(set(old_tiers) - {t["name"] for t in prompt["tiers"]}):
            out.append(f"{prompt['role']}: prompt tier {old_tiers[name]['tier']} {name} removed")
        if old["tool_schema_sha256"] != prompt["tool_schema_sha256"]:
            out.append(f"{prompt['role']}: tool schemas changed")
        if old["prompt_mode"] != prompt["prompt_mode"]:
            out.append(f"{prompt['role']}: prompt mode {old['prompt_mode']} → {prompt['prompt_mode']}")
    for role, olds in old_prompts.items():
        for index in range(seen.get(role, -1) + 1, len(olds)):
            out.append(f"{role}: request {index + 1} not in the second trace")
    old_skills = {s["name"]: s for s in before.get("skills", [])}
    for skill in after.get("skills", []):
        previous = old_skills.get(skill["name"])
        if previous is None:
            out.append(f"skill `{skill['name']}` {skill['version']} loaded")
        elif previous["version"] != skill["version"]:
            out.append(f"skill `{skill['name']}` {previous['version']} → {skill['version']}")
        elif previous["sha256"] != skill["sha256"]:
            out.append(f"skill `{skill['name']}` {skill['version']} changed without a version bump")
    served_before = sorted({c["model_served"] for c in before.get("model_calls", [])})
    served_after = sorted({c["model_served"] for c in after.get("model_calls", [])})
    if served_before != served_after:
        out.append(f"models {', '.join(served_before) or '-'} → {', '.join(served_after) or '-'}")
    return list(dict.fromkeys(out))
