"""One harness run over every suite of TABLE EVL-01a, producing one report (EVL-01, EVL-23).

Suites run through the shipped engine, router and tool worker (the scenario runner assembles the engine exactly as the
app does); nothing in the product branches on the harness (`bank.eval_only_paths`). The whole run sits inside the
egress monitor, so a run that tried to reach the network is reported invalid (EVL-16). A suite this build cannot run
is listed with the reason: a later stage, a model it needs, the device lab, or another CI job that runs it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import secrets
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT
from ..marking_golden import SIGNATURE_CRITERION
from ..scenarios import STAGES
from . import report as rep
from .bank import eval_only_paths
from .egress import offline_run
from .lock import LOCK, Suite, held_out_items, lock_errors, suites

HARDWARE_CLASSES = ("low", "mid", "high")  # every class with a local model (TABLE MDL-16a, D58)
DELEGATED = {"ui_gallery": "runs in the client test job (Vitest gallery render and contract checks, EVL-10)"}
Case = dict[str, Any]


def _case(suite: str, case_id: str, passed: bool | None, critical: bool, trace_ids: list[str], reason: str = "",
          hardware_class: str | None = None) -> Case:  # fmt: skip
    case: Case = {"suite": suite, "case_id": case_id, "critical": critical, "trace_ids": trace_ids,
                  "status": "skipped" if passed is None else "passed" if passed else "failed"}  # fmt: skip
    if reason:
        case["reason"] = reason[:300]
    if hardware_class:
        case["hardware_class"] = hardware_class
    return case


# --- scenario-format suites (scenarios, safety) --------------------------------------------------------------------


async def _scenario_cases(suite: str, directory: Path, build_stage: str, mode: str, classes: tuple[str, ...] | None,
                          concurrency: int) -> list[Case]:  # fmt: skip
    from ..scenarios import load_suite, run_scenario

    gate = asyncio.Semaphore(concurrency)
    jobs: list[tuple[str, dict[str, Any], str | None, bool]] = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name.endswith(".meta.yaml"):
            continue
        data = load_suite(path)
        for scenario in data["scenarios"]:
            if scenario["split"] == "held_out":
                continue  # held-out items live only in the encrypted file (EVL-18)
            for hw in classes or (None,):
                jobs.append((data["suite"], scenario, hw, False))
    if mode == "release" and (directory.parent / "held-out" / f"{suite}.enc").is_file():
        for scenario in held_out_items(suite, mode):
            for hw in classes or (None,):
                jobs.append((scenario.get("_suite", suite), scenario, hw, True))

    async def one(suite_name: str, scenario: dict[str, Any], hw: str | None, held: bool) -> Case:
        async with gate:
            result = await run_scenario(scenario, directory, build_stage, suite=suite_name, hardware_class=hw)
        passed = None if result.status == "skipped" else result.status == "passed"
        if passed and result.numbers_traced < result.numbers_total:  # EVL-02: whatever the final answer
            passed = False
            result.reason = f"{result.numbers_total - result.numbers_traced} board number(s) without a check id"
        if held:  # aggregates only: no id, no trace, no content
            return _case(suite, "held_out", passed, scenario["critical"], [], hardware_class=hw)
        failed = [f"{c.expectation} ({c.detail})" for c in result.checks if c.passed is False]
        reason = result.reason or "; ".join(failed)
        case_id = scenario["id"] + (f"@{hw}" if hw else "")
        traces = [t["trace_id"] for t in result.traces if "trace_id" in t]
        case = _case(suite, case_id, passed, scenario["critical"], traces, reason, hw)
        if passed is not None:
            case.update(numbers_total=result.numbers_total, numbers_traced=result.numbers_traced, leaks=result.leaks)
        return case

    return list(await asyncio.gather(*(one(*job) for job in jobs)))


# --- programmatic suites --------------------------------------------------------------------------------------------


STEP_PAIRS: dict[str, dict[str, int]] = {}  # seeded step pairs of the last marking run (TABLE EVL-17a, VER-06)


def _marking_cases() -> list[Case]:
    from ..golden import FINGERPRINTS, load, matches, result_sha256, run

    pinned = json.loads(FINGERPRINTS.read_text())
    cases = []
    found = categorised = invalid = 0
    for name, data in load().items():
        for case in data["cases"]:
            actual = run(case, data["tool"])
            if name.endswith(".seeded_errors") and case["expect"].get("verdict") == "invalid":
                invalid += 1
                found += isinstance(actual, dict) and actual.get("verdict") == "invalid"
                categorised += isinstance(actual, dict) and actual.get("category") == case["expect"].get("category")
            digest = result_sha256(actual)
            ok = matches(actual, case["expect"]) and pinned.get(case["id"]) == digest
            cases.append(_case("marking", f"{name}/{case['id']}", ok, False, [f"result:{digest[:16]}"],
                               "" if ok else f"expected {case['expect']}, got {str(actual)[:120]}"))  # fmt: skip
    STEP_PAIRS.clear()
    STEP_PAIRS.update(first_wrong={"passed": found, "total": invalid}, category={"passed": categorised,
                                                                                 "total": invalid})  # fmt: skip
    return cases + _marking_golden_cases()


SIGNATURES: dict[str, int] = {}  # the seeded misconception set of the last marking run (CUR-18, TABLE EVL-17a)


def _marking_golden_cases() -> list[Case]:
    """The item-type golden cases (CUR-14, CUR-15) and the seeded misconception set (CUR-18) of `evals/marking`."""
    from ..marking_golden import run_item_cases, run_signature_cases, signature_share

    items, seeded = run_item_cases(), run_signature_cases()
    matched, labelled = signature_share(seeded)
    SIGNATURES.clear()
    SIGNATURES.update(passed=matched, total=labelled)
    return [
        _case("marking", f"marking/{r.case_id}", r.passed, False, [f"verdict:{r.digest[:16]}"], r.detail)
        for r in [*items, *seeded]
    ]


def _prompt_cases() -> list[Case]:
    from ..prompt_snapshots import build_all, diff_errors

    built = build_all()
    errors = diff_errors(built=built)
    return [_case("prompt_regression", key, not [e for e in errors if key in e], False,
                  [f"snapshot:{hashlib.sha256(built[key][0].encode()).hexdigest()[:16]}"],
                  "; ".join(e for e in errors if key in e)) for key in sorted(built)]  # fmt: skip


def _pack_sources() -> list[Path]:
    return sorted(p.parent for p in (REPO_ROOT / "content" / "curriculum").glob("*/*/pack.yaml"))


def _oracle_cases() -> list[Case]:
    """Every bank item has a programmatic oracle and its key verifies (EVL-02). The model-answer half needs a model."""
    from agent_core.config import Settings
    from pack_builder.build import load_source, problems_of

    cases = []
    for directory in _pack_sources():
        source = load_source(directory)
        problems, _ = problems_of(source, Settings())
        for item in source.tables["items"]:
            mine = [p for p in problems if p.startswith(item["id"] + ":") or p.startswith(item["id"] + " ")]
            no_oracle = [part["id"] for part in item.get("parts", []) if not part.get("answer")]
            reason = "; ".join(mine + [f"part {p} has no oracle" for p in no_oracle])
            checks = sorted(
                {a["check_id"] for p in item.get("parts", []) if (a := p.get("answer")) and a.get("check_id")}
            )
            # A computed key cites the checks that reproduce it; a choice key (a conceptual item) is its own oracle,
            # stored in the item record.
            evidence = [f"check:{c}" for c in checks] or [f"record:{item['id']}"]
            cases.append(_case("answer_oracles", item["id"], not reason, False, evidence, reason))
    return cases


def _pack_cases() -> list[Case]:
    from pack_builder.build import BuildError, build

    cases = []
    for directory in _pack_sources():
        with tempfile.TemporaryDirectory() as out:
            try:
                built = build(directory, Path(out))
                digest = hashlib.sha256(built.pack_path.read_bytes()).hexdigest()[:16]
                cases.append(_case("content_packs", directory.name, True, False, [f"pack:{digest}"]))
            except BuildError as error:
                cases.append(_case("content_packs", directory.name, False, False, [], "; ".join(error.problems[:5])))
    return cases


def _memory_cases() -> list[Case]:
    """The memory suite's offline run (EVL-08, MEM-23): production compaction and the production write path."""
    from .memory import suite_cases

    return suite_cases()


def _perception_cases() -> list[Case]:
    from .capture_eval import suite_cases

    return suite_cases()


PROGRAMMATIC: dict[str, Callable[[], list[Case]]] = {
    "marking": _marking_cases,
    "prompt_regression": _prompt_cases,
    "answer_oracles": _oracle_cases,
    "content_packs": _pack_cases,
    "memory_recall": _memory_cases,
    "perception": _perception_cases,
}
SCENARIO_DIRS = {"scenarios": REPO_ROOT / "evals" / "scenarios", "safety": REPO_ROOT / "evals" / "safety"}


# --- the run --------------------------------------------------------------------------------------------------------


def _status(suite: Suite, build_stage: str, model: bool) -> str:
    if STAGES.index(suite.stage) > STAGES.index(build_stage):
        return "not_run_stage"
    if suite.device_lab:
        return "not_run_device_lab"
    if suite.needs_model and not model:
        return "not_run_needs_model"
    if suite.name in DELEGATED:
        return "delegated"
    return "ran"


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _ram_gb() -> float:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return 0.0


def run(
    mode: str = "development",
    build_stage: str = "S1",
    only: set[str] | None = None,
    previous: dict[str, Any] | None = None,
    concurrency: int = 6,
    seeds: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    """Run every suite (or `only` these) and return the validated report."""
    registry = suites()
    locked = json.loads(LOCK.read_text())["suites"] if LOCK.is_file() else {}
    suite_rows: dict[str, Any] = {}
    cases: list[Case] = []
    with offline_run() as egress:
        for name, suite in sorted(registry.items()):
            status = _status(suite, build_stage, model=False)
            mine: list[Case] = []
            if status == "ran" and (only is None or name in only):
                if name in SCENARIO_DIRS:
                    classes = HARDWARE_CLASSES if name == "safety" else None
                    mine = asyncio.run(_scenario_cases(name, SCENARIO_DIRS[name], build_stage, mode, classes,
                                                       concurrency))  # fmt: skip
                elif name in PROGRAMMATIC:
                    mine = PROGRAMMATIC[name]()
            elif status == "ran":
                status = "not_selected"
            cases += mine
            ran = [c for c in mine if c["status"] != "skipped"]
            criteria = {"critical": rep.result(*_count([c for c in ran if c["critical"]]))}
            for hw in sorted({c.get("hardware_class") for c in ran} - {None}):
                criteria[f"class:{hw}"] = rep.result(*_count([c for c in ran if c.get("hardware_class") == hw]))
            if name == "marking" and STEP_PAIRS:
                criteria["step_first_wrong"] = rep.result(**STEP_PAIRS["first_wrong"])
                criteria["step_category"] = rep.result(**STEP_PAIRS["category"])
            if name == "marking" and SIGNATURES:
                criteria[SIGNATURE_CRITERION] = rep.result(**SIGNATURES)
            if name in SCENARIO_DIRS and ran:
                total = sum(c.get("numbers_total", 0) for c in ran)
                criteria["board_numbers_traced"] = rep.result(sum(c.get("numbers_traced", 0) for c in ran), total)
                criteria["no_answer_leak"] = rep.result(sum(c.get("leaks", 0) == 0 for c in ran), len(ran))
            if name == "memory_recall" and mine:
                from .memory import measures

                criteria.update(measures(mine))  # the five measures of MEM-23, read by the memory gate
            if name == "perception" and mine:
                from .capture_eval import measures

                criteria.update(measures(mine))
            if any(c["case_id"] == "held_out" for c in ran):
                criteria["held_out"] = rep.result(*_count([c for c in ran if c["case_id"] == "held_out"]))
            split = "regression" if name == "perception" else "development" if mode == "development" else "held_out"
            suite_rows[name] = {"version": suite.version, "lock_sha256": rep.lock_sha256(locked.get(name, {})),
                                "split": split,
                                "status": status, "result": rep.result(*_count(ran)), "criteria": criteria}  # fmt: skip
    invalid = [f"egress attempt during an offline run: {a}" for a in egress.attempts]
    invalid += [f"lock: {e}" for e in lock_errors()]
    invalid += [f"eval-only code path: {p}" for p in eval_only_paths()]
    report: dict[str, Any] = {
        "report_version": 1,
        "run_id": f"evr_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(3)}",
        "mode": mode,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "build": {"app_version": _app_version(), "commit": _commit(), "stage": build_stage},
        "models": [{"id": "scripted", "quantisation": "none", "tier": "all"}]
        + (
            [{"id": "tesseract-eng", "quantisation": "native", "tier": "ocr"}]
            if suite_rows.get("perception", {}).get("status") == "ran"
            else []
        ),
        "fingerprints": _fingerprints(),
        "hardware": {
            "hardware_class": "mid",
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "ram_gb": _ram_gb(),
        },
        "network": {"state": "disabled", "egress_attempts": len(egress.attempts)},
        "seeds": list(seeds),
        "suites": suite_rows,
        "cases": cases,
        "diff": {"against": None},
        "valid": not invalid,
        "eval_only_paths": eval_only_paths(),
    }
    if invalid:
        report["invalid_reasons"] = invalid
    report["diff"] = rep.diff(report, previous)
    return report


def _count(cases: list[Case]) -> tuple[int, int]:
    return sum(c["status"] == "passed" for c in cases), len(cases)


def _app_version() -> str:
    return str(json.loads((REPO_ROOT / "apps" / "desktop" / "package.json").read_text()).get("version", "0.0.0"))


def _fingerprints() -> dict[str, dict[str, str]]:
    """Prompt fingerprints from the prompt snapshots (role by fixture) and each skill's version and content hash."""
    index = json.loads((REPO_ROOT / "evals" / "prompt-snapshots" / "index.json").read_text())
    prompts = {k: v["sha256"] for k, v in sorted(index.items()) if isinstance(v, dict) and "sha256" in v}
    skills = {}
    for path in sorted((REPO_ROOT / "skills").glob("*/*/SKILL.md")):
        text = path.read_text()
        meta = yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        skills[path.parent.name] = f"{(meta or {}).get('version', '0')}@{digest}"
    return {"prompts": prompts, "skills": skills}
