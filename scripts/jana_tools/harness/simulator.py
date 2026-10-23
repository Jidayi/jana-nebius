"""Simulated students (EVL-04): a model plays the personas of TABLE EVL-04a against items from the syllabus bank, on
the shipped engine, offline in the eval environment (never on a student device).

`python -m jana_tools eval simulate <url> <key> <tutor model> <out dir> [--sim-url U --sim-key K --sim-model M]
[--jobs N]` reads the pinned personas (`evals/personas/personas.yaml`, locked by the suite lock), plays every persona
on its items with each pinned seed, and writes `<out>/report.json`, `<out>/dialogues.jsonl` (the corpus the tone
checks read) and `<out>/review-sample.json` (runs for a teacher's persona-fidelity review). Each run is checked by:

- the deterministic leak detector, on every tutor turn, against the values withheld when the turn started; a turn
  that gave the worked solution the student asked for (the engine opened solution mode, D87) is not a leak;
- the persona's scenario-style checks (an attempt asked for, the misconception named, a hint offered, the topic kept,
  no mode change, the word cap, no false praise);
- the pedagogy rubric, when calibrated judges are available (EVL-05, EVL-06): graded separately by `eval rubric`.

A run where the simulator broke character (wrote as the tutor, as an AI, or ignored the persona's one rule) is
discarded and counted, never scored."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT

PERSONAS = REPO_ROOT / "evals" / "personas" / "personas.yaml"
CORPORA = (REPO_ROOT / "evals" / "skill-evals" / "dialogues.jsonl",)
LIVE_RUNS = REPO_ROOT / "evals" / "live-runs"
BROKE = re.compile(r"\b(as an ai|language model|i am (the|your) tutor|tutor:|assistant:)", re.I)
PRAISE = re.compile(r"\b(genius|so smart|brilliant|perfect|amazing|you're a natural)\b", re.I)
STOP = {"the", "a", "an", "is", "are", "of", "to", "and", "in", "on", "it", "that", "this", "for", "you", "your", "be",
        "by", "with", "as", "at", "or", "not", "so", "what", "which", "how", "do", "does"}  # fmt: skip


def corpus(extra: tuple[Path, ...] = ()) -> list[dict[str, Any]]:
    """Every tutor turn of the committed dialogue corpora: skill-eval runs and simulated-student runs."""
    paths = [*CORPORA, *sorted(LIVE_RUNS.glob("*/dialogues.jsonl")), *extra]
    out = []
    for path in paths:
        if path.is_file():
            out += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [t for t in out if t.get("tutor")]


def load_personas(path: Path = PERSONAS) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text()))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOP}


def named(tutor_text: str, misconception: dict[str, Any]) -> bool:
    """The tutor named the matched wrong idea and aimed at it: its reply shares at least two content words with the
    library entry's name, description or fix (a deterministic proxy for the rubric's names_misconception)."""
    fixing = misconception.get("fix")
    fix = fixing.get("text", {}).get("en", "") if isinstance(fixing, dict) else ""
    reference = " ".join([str(misconception.get("student_name", "")), str(misconception.get("description", "")), fix])
    return len(_words(tutor_text) & _words(reference)) >= 2


def broke_character(line: str, persona: str, options: list[str]) -> bool:
    if not line.strip() or len(line) > 400 or BROKE.search(line):
        return True
    return persona == "misconception_holder" and bool(options) and line.strip() not in options


def _student_prompt(persona: dict[str, Any], item_text: str, options: dict[str, str], history: list[tuple[str, str]],
                    misconception: str) -> str:  # fmt: skip
    rules = persona["prompt"].format(misconception=misconception)
    lines = [rules, "", f"The question you were given: {item_text}"]
    if options:
        lines.append("Options: " + "; ".join(f"{k}) {v}" for k, v in options.items()))
        lines.append("Reply with the letter of the option you choose and nothing else.")
    lines.append("The conversation so far:")
    lines += [f"{who}: {text}" for who, text in history[-6:]]
    lines.append("Write only your next message as the student, in one short line.")
    return "\n".join(lines)


async def _simulate(provider: Any, model: str, prompt: str, seed: int, temperature: float, max_tokens: int,
                    choices: list[str] | None = None) -> str:  # fmt: skip
    """The simulator's next student line. On a multiple-choice item it picks an option through a constrained reply
    (the option letters only), as a student taps one."""
    from agent_core.providers.base import Message

    structured = None
    if choices:
        schema = {"type": "object", "additionalProperties": False, "required": ["choice"],
                  "properties": {"choice": {"enum": choices}}}  # fmt: skip
        structured = {"mode": "json_schema", "schema": schema, "name": "choice"}
    turn = await provider.complete(model, [Message("user", prompt)], [], max_tokens=max_tokens, effort="none",
                                   temperature=temperature, seed=seed, structured=structured)  # fmt: skip
    text = str(turn.text).strip()
    if choices:
        try:
            return str(json.loads(text)["choice"])
        except (ValueError, KeyError, TypeError):
            return text
    return text.splitlines()[0] if text else ""


async def run_one(url: str, key: str, model: str, sim: Any, sim_model: str, config: dict[str, Any], name: str,
                  item_id: str, seed: int, out: Path, workspace: Path = REPO_ROOT,
                  item_record: dict[str, Any] | None = None, engine_stage: str = "S1") -> dict[str, Any]:  # fmt: skip
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.gates import leak_findings
    from agent_core.engine.state import SessionState, numbers_in
    from agent_core.engine.tone import banned_phrases, word_cap
    from agent_core.providers.llama import LlamaServerProvider
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    from ..skill_evals import load_item

    persona = config["personas"][name]
    sim_conf = config["simulator"]
    code = ".".join(item_id.split(".")[1:3])
    item = item_record or load_item(f"{code}:{item_id}", workspace / "content/curriculum")
    part = item["parts"][0]
    options = {str(o["id"]): str(o["text"]) for o in (part.get("answer") or {}).get("options") or []}
    seeded = next((o for o in (part.get("answer") or {}).get("options") or [] if o.get("misconception_id")), None)
    misconception: dict[str, Any] = {}
    if seeded is not None:
        library = workspace / "content/curriculum" / item["subject"] / item["level"] / "misconceptions"
        path = library / f"{seeded['misconception_id']}.yaml"
        misconception = dict(yaml.safe_load(path.read_text()))
    settings = Settings(
        build_stage=engine_stage, worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0
    )
    supervisor = WorkerSupervisor(process_factory(settings, scratch_root=out / "scratch"), settings)
    await supervisor.start()
    tutor = LlamaServerProvider(url, key)

    def only(data: dict[str, Any]) -> None:
        for tier in data["tiers"]:
            data["tiers"][tier] = [f"local:{model}"]

    state = SessionState(
        new_id("ses"),
        subject={"mth": "mathematics", "phy": "physics", "chm": "chemistry", "bio": "biology", "acc": "accounting"}[
            item["subject"]
        ],
        level=item["level"].upper(),
        hardware_class="mid",
    )
    agent_content = (
        workspace / "content/agent" if (workspace / "content/agent").exists() else REPO_ROOT / "content/agent"
    )
    engine = assemble({"local": tutor}, settings, state, agent_content,
                      workspace / "skills",
                      out / "spill", supervisor, router_overrides=only, session_date="2026-10-13")  # fmt: skip
    learned: list[Any] = []
    engine.learning = learned.extend
    row: dict[str, Any] = {"persona": name, "item": item_id, "seed": seed, "turns": [], "leaks": [], "checks": {},
                           "broke_character": False, "outcome": "complete"}  # fmt: skip
    history: list[tuple[str, str]] = []
    started = time.monotonic()
    try:
        opening = await engine.start_practice(item, str(part["id"]))
        history.append(("Tutor", engine.events.student_text(opening.turn_id)))
        statement = engine.state.problem.statement if engine.state.problem else ""
        for n in range(int(sim_conf["turns"])):
            prompt = _student_prompt(persona, statement, options, history, str(misconception.get("description", "")))
            line = await _simulate(sim, sim_model, prompt, seed + n, float(sim_conf["temperature"]),
                                   int(sim_conf["max_tokens"]), list(options) if n == 0 else None)  # fmt: skip
            expected = [str(seeded["id"])] if (name == "misconception_holder" and seeded and n == 0) else []
            if broke_character(line, name, expected):
                row["broke_character"] = True
                row["broken_line"] = line[:200]
                break
            withheld = engine.state.withheld()
            givens = set(numbers_in(statement)) | {v for s in engine.state.student_lines for v in numbers_in(s)}
            mode_before = engine.state.mode
            result = await engine.student_turn(line)
            shown = engine.events.student_text(result.turn_id)
            history += [("Student", line), ("Tutor", shown)]
            # D87, PED-09: the worked solution the student asked for is the policy, not a leak. The engine itself
            # decides the request (the turn that opened solution mode), and from then on nothing is withheld.
            asked = engine.state.mode == "solution"
            if not asked:
                found = leak_findings({"say": shown}, withheld, engine.deps.settings, None,
                                      givens | set(numbers_in(line)))  # fmt: skip
                row["leaks"] += [{"turn": n + 1, "kind": f.kind} for f in found]
            row["turns"].append({"student": line, "tutor": shown, "template": engine.turn_log[-1]["template"],
                                 "mode_changed": engine.state.mode != mode_before, "solution_on_request": asked,
                                 "words": len(shown.split()), "banned": banned_phrases(shown)})  # fmt: skip
        turns = row["turns"]
        cap = word_cap(engine.deps.settings, "O")
        checks: dict[str, bool] = {"no_leak": not row["leaks"]}
        for check in persona["checks"]:
            if check == "asks_for_attempt":
                checks[check] = any(t["tutor"].rstrip().endswith("?") for t in turns)
            elif check == "misconception_named":
                matched = [e for e in learned if e.type == "verdict" and e.payload.get("misconception_id")]
                after = [t["tutor"] for t in turns[:2]]
                checks[check] = bool(matched) and any(named(t, misconception) for t in after)
            elif check == "offers_hint":
                checks[check] = any(re.search(r"\b(hint|start|first step|try)\b", t["tutor"], re.I) for t in turns)
            elif check in ("no_lecture", "stays_kind", "understood"):
                checks[check] = all(t["words"] <= cap for t in turns)
            elif check == "returns_to_topic":
                checks[check] = any(t["template"] == "tpl.off_topic" or re.search(r"\b(question|speed|distance|"
                                    r"time|metres?)\b", t["tutor"], re.I) for t in turns)  # fmt: skip
            elif check == "no_false_praise":
                checks[check] = not any(PRAISE.search(t["tutor"]) or t["banned"] for t in turns)
            elif check == "no_distress_template":
                checks[check] = not any(t["template"] == "tpl.distress" for t in turns)
            elif check == "no_mode_change":
                checks[check] = not any(t["mode_changed"] for t in turns) and engine.state.mode == "guided"
        row["checks"] = checks
        row["withheld_until_earned"] = not row["leaks"]
    except Exception as error:  # a crashed run is recorded, never scored as a pass
        row.update(outcome="error", error=f"{type(error).__name__}: {str(error)[:160]}")
    finally:
        await supervisor.close()
        await tutor.close()
    row["seconds"] = round(time.monotonic() - started, 1)
    return row


def report(rows: list[dict[str, Any]], model: str, sim_model: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_core.config import Settings

    settings = Settings()
    scored = [r for r in rows if r["outcome"] == "complete" and not r["broke_character"]]
    holders = [r for r in scored if r["persona"] == "misconception_holder"]
    named_runs = sum(1 for r in holders if r["checks"].get("misconception_named"))
    withheld = sum(1 for r in scored if r.get("withheld_until_earned"))
    per_persona: dict[str, dict[str, int]] = {}
    for r in scored:
        entry = per_persona.setdefault(r["persona"], {"runs": 0, "all_checks": 0})
        entry["runs"] += 1
        entry["all_checks"] += int(all(r["checks"].values()))
    return {
        "suite": "simulated_students", "tutor_model": model, "simulator_model": sim_model,
        "simulator_pinned": config["simulator"], "runs": len(rows), "scored": len(scored),
        "discarded_broke_character": sum(1 for r in rows if r["broke_character"]),
        "errors": sum(1 for r in rows if r["outcome"] == "error"),
        "detected_leaks": sum(len(r["leaks"]) for r in scored),
        "withheld_until_earned": {"passed": withheld, "total": len(scored),
                                  "gate": settings.eval_simulated_withholding_rate},
        "misconception_named": {"passed": named_runs, "total": len(holders),
                                "gate": settings.eval_misconception_named_rate},
        "per_persona": per_persona, "rows": rows,
    }  # fmt: skip


def run(url: str, key: str, model: str, out: Path, sim_url: str | None = None, sim_key: str | None = None,
        sim_model: str | None = None, jobs: int = 2, per_persona: int | None = None) -> dict[str, Any]:  # fmt: skip
    from agent_core.config import Settings
    from agent_core.providers.llama import LlamaServerProvider

    config = load_personas()
    sim_model = sim_model or str(config["simulator"]["model"])
    work = [(name, item, seed) for name, persona in config["personas"].items()
            for item in config["items"][persona["items"]] for seed in config["simulator"]["seeds"]]  # fmt: skip
    if per_persona is not None:  # a smaller first pass: the first runs of every persona
        work = [w for w in work if sum(1 for v in work[: work.index(w)] if v[0] == w[0]) < per_persona]
    done = out / "done"
    done.mkdir(parents=True, exist_ok=True)
    rows = {(r["persona"], r["item"], r["seed"]): r
            for r in (json.loads(p.read_text()) for p in sorted(done.glob("*.json")))}  # fmt: skip

    async def main() -> None:
        queue: asyncio.Queue[tuple[str, str, int]] = asyncio.Queue()
        for entry in work:
            if entry not in rows or rows[entry]["outcome"] == "error":
                queue.put_nowait(entry)

        async def worker() -> None:
            sim = LlamaServerProvider(sim_url or url, sim_key or key)
            try:
                while not queue.empty():
                    name, item, seed = queue.get_nowait()
                    row = await run_one(url, key, model, sim, sim_model, config, name, item, seed,
                                        out / "runs" / f"{name}.{item}.{seed}")  # fmt: skip
                    (done / f"{name}.{item}.{seed}.json").write_text(json.dumps(row, indent=1))
                    rows[(name, item, seed)] = row
                    print(json.dumps({k: row.get(k) for k in ("persona", "item", "seed", "outcome", "seconds")}
                                     | {"leaks": len(row["leaks"]), "checks": row["checks"]}), flush=True)  # fmt: skip
            finally:
                await sim.close()

        await asyncio.gather(*(worker() for _ in range(max(1, jobs))))

    asyncio.run(main())
    ordered = [rows[w] for w in work if w in rows]
    result = report(ordered, model, sim_model, config)
    (out / "report.json").write_text(json.dumps(result, indent=1))
    dialogues = [{"source": f"simulated:{r['persona']}/{r['item']}/{r['seed']}", "level": "O", **t}
                 for r in ordered if not r["broke_character"] for t in r["turns"]]  # fmt: skip
    (out / "dialogues.jsonl").write_text("".join(json.dumps({k: d[k] for k in ("source", "level", "student", "tutor")},
                                                            ensure_ascii=False) + "\n" for d in dialogues))  # fmt: skip
    size = Settings().eval_persona_review_sample
    sample = ordered[:: max(1, len(ordered) // size)][:size]
    (out / "review-sample.json").write_text(json.dumps([{"persona": r["persona"], "item": r["item"],
                                                          "seed": r["seed"], "turns": r["turns"]}
                                                         for r in sample], indent=1))  # fmt: skip
    return result
