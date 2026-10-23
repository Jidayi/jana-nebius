"""Colocated skill evals (SKL-21, EVL-07): `evals/*.yaml` beside each `SKILL.md`, run by the evaluation harness on the
local fast tier.

A skill's eval file is a scenario suite (the `evals/scenario` contract) named `skill.<skill name>`: scripted student
replies, each turn with assertions. The SKL-21 assertions map onto the contract's expectations:

- `no_answer_leak`: the deterministic detector, against the values the engine withheld when the turn started;
- `tool_called` (and order): `tool_call`, matched in the order listed within a turn;
- `marking_verdict`: `board_step` (owner, status, error category) on the student's marked line;
- `hint_rung_sequence`: `hint_rung` after each turn;
- `misconception_detected`: `learner` with the misconception the marker matched on the student's answer;
- `escalation`: `template`, `mode` or `card` after repeated failure.

`reply` and `judge` expectations are soft (wording); every other one is hard. Minimums: a teaching skill has a case
for each of its misconceptions (`setup.profile.misconceptions` names it) and at least `skill_eval_min_teaching`; a
pedagogy skill one per branch (tag `branch_<n>`) and at least `skill_eval_min_pedagogy`; an agent skill at least
`skill_eval_min_agent`. CI fails below a minimum.

A live run writes `evals/skill-evals/results.json`: per skill, its version and body hash, the hash of its eval files,
the model, and the hard-assertion results. A skill is `reviewed` only with a record for its current body and evals at
the `skill_eval_hard_pass_rate` (EVL-07); review itself stays a human code review (SKL-18)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT
from .skills import SKILLS, _section_text

RESULTS = REPO_ROOT / "evals" / "skill-evals" / "results.json"
CURRICULUM = REPO_ROOT / "content" / "curriculum"
SOFT = frozenset({"reply", "judge"})
HARD = frozenset({"no_answer_leak", "tool_call", "board_step", "hint_rung", "learner", "mode", "template",
                  "turn_status", "card", "event", "gate", "network_calls", "answer_revealed"})  # fmt: skip
STUCK_LINE = "I'm stuck, can I have a hint?"


def eval_files(folder: Path) -> list[Path]:
    return sorted((folder / "evals").glob("*.yaml")) if (folder / "evals").is_dir() else []


def case_sha256(case: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()


def evals_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in eval_files(folder):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def load_cases(folder: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every scenario of a skill's eval files, and the problems found (contract, suite name)."""
    from agent_core.contracts import errors as contract_errors

    cases: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in eval_files(folder):
        try:
            suite = yaml.safe_load(path.read_text())
        except yaml.YAMLError as error:
            problems.append(f"{path.name}: not YAML ({str(error)[:80]})")
            continue
        found = contract_errors("evals/scenario", suite)
        if found:
            problems.append(f"{path.name}: {found[0]}")
            continue
        if suite["suite"] != f"skill.{folder.name}":
            problems.append(f"{path.name}: suite is {suite['suite']}, not skill.{folder.name}")
        cases += suite["scenarios"]
    ids = [c["id"] for c in cases]
    problems += [f"case id {i} is repeated" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return cases, problems


def misconceptions(body: str) -> list[str]:
    section = _section_text(body, "Misconceptions")
    return re.findall(r"^- `(mc\.[^`]+)`", section[0], re.M) if section else []


def branches(body: str) -> int:
    """The branches of a pedagogy skill: the data rows of its student-state table (or its list items)."""
    section = _section_text(body, "Branches by student state")
    if not section:
        return 0
    rows = [ln for ln in section[0].splitlines() if ln.startswith("|") and not re.match(r"^\|\s*-", ln)]
    return max(0, len(rows) - 1) if rows else len(re.findall(r"^(?:- |\d+\. )", section[0], re.M))


def minimum(kind: str, body: str, settings: Any) -> int:
    if kind == "teaching":
        return max(settings.skill_eval_min_teaching, len(misconceptions(body)))
    if kind == "pedagogy":
        return max(settings.skill_eval_min_pedagogy, branches(body))
    return int(settings.skill_eval_min_agent)


def minimum_errors(root: Path = SKILLS, settings: Any = None) -> list[str]:
    """SKL-21: every skill has valid eval files with at least its minimum of cases, and the coverage its kind needs."""
    from agent_core.assets.skills import KINDS, SkillError, discover, parse
    from agent_core.config import Settings

    settings = settings or Settings()
    errors: list[str] = []
    for path in discover(root, KINDS):
        try:
            skill = parse(path)
        except (SkillError, ValueError):
            continue  # the skills check reports it
        cases, problems = load_cases(skill.folder)
        errors += [f"{skill.name}: {p}" for p in problems]
        needed = minimum(skill.kind, skill.body, settings)
        if len(cases) < needed:
            errors.append(f"{skill.name}: {len(cases)} eval cases, fewer than its minimum {needed} (SKL-21)")
        if skill.kind == "teaching":
            covered = {m for c in cases for m in c["setup"]["profile"].get("misconceptions", [])}
            missing = [m for m in misconceptions(skill.body) if m not in covered]
            if missing:
                errors.append(f"{skill.name}: no eval case for misconception {', '.join(missing[:3])}"
                              + (f" and {len(missing) - 3} more" if len(missing) > 3 else ""))  # fmt: skip
        if skill.kind == "pedagogy":
            tags = {t for c in cases for t in c.get("tags", [])}
            missing_branches = [n for n in range(1, branches(skill.body) + 1) if f"branch_{n}" not in tags]
            if missing_branches:
                errors.append(f"{skill.name}: no eval case for branch {missing_branches[0]}")
    return errors


# --- the record a reviewed skill needs (EVL-07) ----------------------------------------------------------------------


def read_results(path: Path = RESULTS) -> dict[str, Any]:
    return dict(json.loads(path.read_text())["skills"]) if path.is_file() else {}


def source_sha256(skill: Any) -> str:
    """Evaluation identity includes prompt-affecting front matter; status promotion does not change it."""
    meta = {k: v for k, v in skill.meta.items() if k not in ("status", "last_reviewed_by", "last_reviewed_at")}
    return hashlib.sha256(json.dumps({"meta": meta, "body": skill.body}, sort_keys=True).encode()).hexdigest()


def passing(record: dict[str, Any] | None, skill: Any, settings: Any) -> bool:
    return bool(
        record
        and record.get("version") == skill.version
        and record.get("source_sha256") == source_sha256(skill)
        and record.get("sha256") == skill.sha256
        and record.get("evals_sha256") == evals_sha256(skill.folder)
        and record.get("hard_total", 0) > 0
        and record.get("cases") == record.get("cases_total")
        and record["hard_passed"] / record["hard_total"] >= settings.skill_eval_hard_pass_rate
    )


def passing_records(root: Path = SKILLS, model: str = "fixture") -> dict[str, Any]:
    """A passing record for every skill under `root` as it is now: for tests of the gates that read the records."""
    from agent_core.assets.skills import KINDS, discover, parse

    out = {}
    for path in discover(root, KINDS):
        skill = parse(path)
        cases = len(load_cases(skill.folder)[0])
        out[skill.name] = {"version": skill.version, "source_sha256": source_sha256(skill),
                           "sha256": skill.sha256, "evals_sha256": evals_sha256(skill.folder),
                           "model": model, "cases_total": cases, "cases": cases, "hard_total": max(1, cases),
                           "hard_passed": max(1, cases)}  # fmt: skip
    return out


def review_errors(root: Path = SKILLS, results: Path = RESULTS, settings: Any = None) -> list[str]:
    """EVL-07: a skill marked `reviewed` without a passing colocated eval run for its current body and evals."""
    from agent_core.assets.skills import KINDS, SkillError, discover, parse
    from agent_core.config import Settings

    settings = settings or Settings()
    records = read_results(results)
    errors = []
    for path in discover(root, KINDS):
        try:
            skill = parse(path)
        except (SkillError, ValueError):
            continue
        if skill.status == "reviewed" and not passing(records.get(skill.name), skill, settings):
            errors.append(f"{skill.name}: reviewed without a passing colocated eval run for version {skill.version} "
                          "(EVL-07)")  # fmt: skip
    return errors


def gate_report(root: Path = SKILLS, results: Path = RESULTS, settings: Any = None) -> dict[str, list[str]]:
    """Which skills would pass their gates now: lint, minimums and a passing eval run (review is a human's, SKL-18)."""
    from agent_core.assets.skills import KINDS, SkillError, discover, parse
    from agent_core.config import Settings

    from .skills import Catalogue, lint

    settings = settings or Settings()
    records = read_results(results)
    names = {p.parent.name for p in discover(root, KINDS)}
    catalogue = Catalogue.from_registers(names).with_packs()
    short = {e.split(":", 1)[0] for e in minimum_errors(root, settings)}
    out: dict[str, list[str]] = {"would_pass": [], "would_fail": []}
    for path in discover(root, KINDS):
        try:
            skill = parse(path)
        except (SkillError, ValueError):
            out["would_fail"].append(path.parent.name)
            continue
        ok = not lint(path, catalogue) and skill.name not in short and passing(records.get(skill.name), skill,
                                                                                 settings)  # fmt: skip
        out["would_pass" if ok else "would_fail"].append(skill.name)
    return out


# --- running cases on a live model -----------------------------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    hard_passed: int = 0
    hard_total: int = 0
    soft_passed: int = 0
    soft_total: int = 0
    failures: list[str] = field(default_factory=list)
    dialogue: list[dict[str, str]] = field(default_factory=list)  # synthetic student line and the tutor's shown text
    error: str | None = None
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and self.hard_passed == self.hard_total


def load_item(item_ref: str, curriculum: Path = CURRICULUM) -> dict[str, Any]:
    """`<subject>.<level>:<item id>` from the packs' sources."""
    pack, item_id = item_ref.split(":", 1)
    subject, level = pack.split(".", 1)
    return dict(yaml.safe_load((curriculum / subject / level / "items" / f"{item_id}.yaml").read_text()))


def _part(case: dict[str, Any]) -> str:
    return next((t.removeprefix("part_") for t in case.get("tags", []) if t.startswith("part_")), "a")


def correct_option(item: dict[str, Any], part_id: str) -> dict[str, Any] | None:
    part = next(p for p in item["parts"] if p["id"] == part_id)
    return next((o for o in (part.get("answer") or {}).get("options") or [] if o.get("correct")), None)


def option_named(text: str, option: dict[str, Any] | None) -> bool:
    """The correct option given away by name ("the answer is B", "option B is right")."""
    if option is None:
        return False
    label = re.escape(str(option["id"]))
    return bool(re.search(rf"\b(answer|option|choice|choose|pick)\s+(is\s+)?\(?{label}\)?\b(?!\s*\w*\s*is (not|wrong))",
                          text, re.I))  # fmt: skip


def check(expectation: dict[str, Any], engine: Any, turn_id: str, withheld: list[tuple[Fraction, str | None]],
          givens: set[Fraction], learned: list[Any], order: dict[str, int], option: dict[str, Any] | None,
          session_tools: bool = False) -> tuple[
              bool | None, str]:  # fmt: skip
    """One expectation after one turn: (passed, detail); None when it cannot be checked in this harness."""
    from agent_core.engine.gates import leak_findings

    from .scenarios import _all_tools, _check, _visible

    ((key, spec),) = expectation.items()
    text, events = _visible(engine, turn_id)
    if key == "no_answer_leak":
        found = leak_findings({"visible": text}, withheld, engine.deps.settings, None, givens) if withheld else []
        named = option_named(text, option)
        return not found and not named, f"leaks: {[f.kind for f in found]}{' option named' if named else ''}"
    if key == "tool_call":
        calls = _all_tools(engine, None if session_tools else turn_id)  # a team role's calls run at the opening
        start = order.get(turn_id, 0)
        for index in range(start, len(calls)):
            c = calls[index]
            if c["name"] == spec["name"] and ("role" not in spec or c["role"] == spec["role"]):
                if spec.get("absent"):
                    return False, f"{c['name']} called"
                order[turn_id] = index + 1  # the next tool_call expectation must come later (SKL-21 tool order)
                return True, ""
        return bool(spec.get("absent")), f"calls: {[c['name'] for c in calls]}"
    if key == "board_step":
        steps = [e for e in events if e["type"] == "board.step"]
        hits = [e for e in steps if ("owner" not in spec or e["owner"] == spec["owner"])
                and ("status" not in spec or e["status"] == spec["status"])
                and ("error_category" not in spec or e.get("error_category") == spec["error_category"])]  # fmt: skip
        return bool(hits), str([(e["owner"], e["status"]) for e in steps])
    if key == "learner":
        verdicts = [e.payload for e in learned if e.type == "verdict" and e.turn_id == turn_id]
        if "misconception" in spec:
            found = [v.get("misconception_id") for v in verdicts]
            return spec["misconception"] in found, f"verdict misconceptions: {found}"
        return None, "learner mastery is checked by the learning suites"
    if key == "turn_status":
        trace = next((t for t in engine.traces if t.get("turn_id") == turn_id.split("_", 1)[-1]), None)
        status = {"complete": "complete", "error": "error", "interrupted": "interrupted"}.get(spec, spec)
        return bool(trace and trace["status"] == status), f"status {(trace or {}).get('status')}"
    if key == "card":
        cards = [e for e in events if e["type"] == "card.open" and e["card"].get("card_type") == spec["card_type"]]
        return (not cards) if spec.get("absent") else bool(cards), f"{len(cards)} cards"
    if key == "judge":
        return None, "judged by the rubric suite (EVL-05)"
    result = _check(expectation, engine, turn_id, [], set(), _NoCloud())
    return result.passed, result.detail


class _NoCloud:
    requests: tuple[Any, ...] = ()  # the skill evals run offline: no cloud provider is assembled


async def run_case(case: dict[str, Any], skill: Any, provider: Any, model: str, out: Path,
                   hardware_class: str = "mid", workspace: Path = REPO_ROOT,
                   engine_stage: str = "S1") -> CaseResult:  # fmt: skip
    """One case on the live engine with this skill pushed, whatever the session's KCs would select."""
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState, numbers_in
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    result = CaseResult(case["id"])
    setup = case["setup"]
    # A long handshake allowance: an evaluation machine may be busy; the tools must be offered for the run to count.
    settings = Settings(
        build_stage=engine_stage, worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0
    )
    supervisor = WorkerSupervisor(process_factory(settings, scratch_root=out / "scratch"), settings)
    await supervisor.start()
    if not supervisor.compute_available():  # a run without its tools says nothing about the skill
        await supervisor.close()
        result.error = "environment: the tool worker did not start"
        return result

    def only(data: dict[str, Any]) -> None:
        for tier in data["tiers"]:
            data["tiers"][tier] = [f"local:{model}"]

    profile = setup["profile"]
    subject = {"mathematics": "mathematics", "physics": "physics", "chemistry": "chemistry",
               "accounting": "accounting", "biology": "biology"}[profile["subjects"][0]]  # fmt: skip
    chosen = profile.get("settings", {})
    state = SessionState(new_id("ses"), subject=subject, level=profile["level"], mode=setup["mode"],
                         hardware_class=hardware_class,
                         reading_level=chosen.get("reading_level", "standard"))  # fmt: skip
    agent_content = (
        workspace / "content/agent" if (workspace / "content/agent").exists() else REPO_ROOT / "content/agent"
    )
    engine = assemble({"local": provider}, settings, state, agent_content,
                      workspace / "skills", out / "spill",
                      supervisor, router_overrides=only, session_date="2026-10-13")  # fmt: skip
    learned: list[Any] = []
    engine.learning = learned.extend
    if skill.kind == "teaching":
        engine._teaching_skill = lambda: skill  # type: ignore[method-assign]
    elif skill.kind == "pedagogy":
        base = engine._prompt_base

        def with_pedagogy() -> dict[str, Any]:
            return {**base(), "pedagogy_skill": skill}

        engine._prompt_base = with_pedagogy  # type: ignore[method-assign]
    started = time.monotonic()
    order: dict[str, int] = {}
    option = None
    try:
        question = setup["question"]
        if "item_ref" in question:
            item = load_item(question["item_ref"], workspace / "content/curriculum")
            option = correct_option(item, _part(case))
            opening = await engine.start_practice(item, _part(case))
        else:
            opening = await engine.start_problem(str(question["text"]))
        result.dialogue.append({"student": "", "tutor": engine.events.student_text(opening.turn_id)})
        for turn in case["turns"]:
            withheld = engine.state.withheld()
            givens = set(numbers_in(engine.state.problem.statement)) if engine.state.problem else set()
            for line in engine.state.student_lines:
                givens.update(numbers_in(line))
            if "student" in turn:
                outcome = await engine.student_turn(str(turn["student"]))
            elif turn["action"]["kind"] in ("stuck", "hint_request"):
                outcome = await engine.student_turn(STUCK_LINE, stuck=True)
            else:
                outcome = await engine.student_turn(str(turn["action"].get("value", "")))
            result.dialogue.append({"student": str(turn.get("student", STUCK_LINE)),
                                    "tutor": engine.events.student_text(outcome.turn_id)})  # fmt: skip
            for expectation in turn["expect"]:
                ((key, _),) = expectation.items()
                passed, detail = check(expectation, engine, outcome.turn_id, withheld, givens, learned, order, option,
                                       "session_tools" in case.get("tags", []))  # fmt: skip
                if passed is None:
                    continue
                hard = key not in SOFT
                if hard:
                    result.hard_total += 1
                    result.hard_passed += int(passed)
                else:
                    result.soft_total += 1
                    result.soft_passed += int(passed)
                if not passed:
                    result.failures.append(f"{key}: {detail[:160]}")
    except Exception as error:  # a crashed case is a failed case, recorded with its type
        result.error = f"{type(error).__name__}: {str(error)[:160]}"
    finally:
        await supervisor.close()
    result.seconds = round(time.monotonic() - started, 1)
    return result


def run_skills(url: str, key: str, model: str, out: Path, names: list[str] | None = None, jobs: int = 3,
               results: Path = RESULTS, hardware_class: str = "mid") -> dict[str, Any]:  # fmt: skip
    """Run the eval cases of every skill (or of `names`) on the live model and merge the records into `results`.
    A case's work is resumable: finished cases are kept under `out/done/`."""
    from agent_core.assets.skills import KINDS, discover, parse
    from agent_core.providers.llama import LlamaServerProvider

    skills = [parse(p) for p in discover(SKILLS, KINDS)]
    skills = [s for s in skills if names is None or s.name in names]
    by_skill = [[(s, c) for c in load_cases(s.folder)[0]] for s in skills]
    # Round robin over the skills, so a run cut short still has every skill's first cases.
    longest = max((len(p) for p in by_skill), default=0)
    work = [pairs[i] for i in range(longest) for pairs in by_skill if i < len(pairs)]
    done_dir = out / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    finished = _finished(out)

    def current(skill: Any, case: dict[str, Any]) -> bool:
        return _current(finished, skill, case)

    async def main() -> None:
        queue: asyncio.Queue[tuple[Any, dict[str, Any]]] = asyncio.Queue()
        for pair in work:  # a failed case is run again: a failure must reproduce before it is recorded
            if not current(*pair) or not finished[(pair[0].name, pair[1]["id"])]["passed"]:
                queue.put_nowait(pair)

        async def worker() -> None:
            provider = LlamaServerProvider(url, key)
            try:
                while not queue.empty():
                    skill, case = queue.get_nowait()
                    where = out / "runs" / skill.name / case["id"]
                    found = await run_case(case, skill, provider, model, where, hardware_class)
                    row = {"skill": skill.name, "source_sha256": source_sha256(skill),
                           "sha256": skill.sha256, "case_sha256": case_sha256(case),
                           "level": str(case["setup"]["profile"]["level"]), **found.__dict__,
                           "passed": found.passed}  # fmt: skip
                    (done_dir / f"{skill.name}.{case['id']}.json").write_text(json.dumps(row, indent=1))
                    finished[(skill.name, case["id"])] = row
                    print(json.dumps({k: row[k] for k in ("skill", "case_id", "passed", "seconds")}), flush=True)
            finally:
                await provider.close()

        await asyncio.gather(*(worker() for _ in range(max(1, jobs))))

    asyncio.run(main())
    return summarise(out, model, names, results, hardware_class)


def _finished(out: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = (json.loads(p.read_text()) for p in sorted((out / "done").glob("*.json")))
    return {(r["skill"], r["case_id"]): r for r in rows}


def _current(finished: dict[tuple[str, str], dict[str, Any]], skill: Any, case: dict[str, Any]) -> bool:
    row = finished.get((skill.name, case["id"]))
    return bool(
        row
        and row.get("source_sha256") == source_sha256(skill)
        and row.get("sha256") == skill.sha256
        and row.get("case_sha256") == case_sha256(case)
    )


def summarise(out: Path, model: str, names: list[str] | None = None, results: Path = RESULTS,
              hardware_class: str = "mid") -> dict[str, Any]:  # fmt: skip
    """Merge the finished cases under `out/done/` into the records and the dialogue corpus (also for a partial run:
    a skill whose cases did not all run gets a record that does not pass)."""
    from agent_core.assets.skills import KINDS, discover, parse

    finished = _finished(out)
    skills = [s for s in (parse(p) for p in discover(SKILLS, KINDS)) if names is None or s.name in names]
    records = read_results(results)
    dialogues = []
    for skill in skills:
        cases = load_cases(skill.folder)[0]
        rows = [finished[(skill.name, c["id"])] for c in cases if _current(finished, skill, c)]
        if not rows:
            continue
        dialogues += [{"source": f"skill:{skill.name}/{r['case_id']}", "level": r["level"], **turn}
                      for r in rows for turn in r["dialogue"]]  # fmt: skip
        records[skill.name] = {
            "version": skill.version, "source_sha256": source_sha256(skill),
                           "sha256": skill.sha256, "evals_sha256": evals_sha256(skill.folder),
            "model": model, "hardware_class": hardware_class, "run_on": time.strftime("%Y-%m-%d"),
            "cases_total": len(cases), "cases": len(rows), "cases_passed": sum(1 for r in rows if r["passed"]),
            "hard_total": sum(r["hard_total"] for r in rows) + sum(1 for r in rows if r["error"]),
            "hard_passed": sum(r["hard_passed"] for r in rows),
            "soft_total": sum(r["soft_total"] for r in rows), "soft_passed": sum(r["soft_passed"] for r in rows),
            "failed_cases": sorted(r["case_id"] for r in rows if not r["passed"]),
        }  # fmt: skip
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(json.dumps({"skills": dict(sorted(records.items()))}, indent=1, sort_keys=True) + "\n")
    # The dialogue corpus the tone checks read (PED-20, PED-21): synthetic student lines and the tutor's shown text.
    corpus = results.parent / "dialogues.jsonl"
    kept = [json.loads(line) for line in corpus.read_text().splitlines()] if corpus.is_file() else []
    ran = {d["source"].split("/")[0] for d in dialogues}
    kept = [d for d in kept if d["source"].split("/")[0] not in ran] + dialogues
    corpus.write_text("".join(json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n"
                              for d in sorted(kept, key=lambda d: d["source"])))  # fmt: skip
    return records
