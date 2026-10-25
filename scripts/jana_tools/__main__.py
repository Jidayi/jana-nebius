"""Command line: python -m jana_tools <check> [...]."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import REPO_ROOT
from .bundle_scan import bundle_scan_errors, client_network_errors
from .governance import codeowners_errors, load_boundaries, missing_approvals, render_codeowners, threat_model_errors
from .layer_rules import importlinter_errors, render_importlinter
from .layers import layer_errors
from .layout import layout_errors
from .product import (
    decided_decisions,
    epic_scope_errors,
    feature_review_errors,
    feature_review_paths,
    offline_behaviour_errors,
    principle_trace_errors,
    review_template_errors,
    scope_trace_errors,
)
from .repo import repo_paths
from .spec_lock import spec_lock_errors
from .stages import load_workflow, needs_errors, workflow_errors
from .supply_chain import (
    action_pin_errors,
    dependency_review_errors,
    lockfile_errors,
    notices_errors,
    render_notices,
    shipped_licence_errors,
    vendored_errors,
    write_sboms,
)

CHECKS: dict[str, Callable[[], list[str]]] = {
    "layout": lambda: layout_errors(repo_paths(REPO_ROOT)),
    "layers": lambda: layer_errors(REPO_ROOT),
    "spec-lock": lambda: spec_lock_errors(REPO_ROOT),
    "client-bundle": lambda: bundle_scan_errors(REPO_ROOT),
    "client-network": lambda: client_network_errors(REPO_ROOT),  # VOC-01, ARC-02: the UI talks only to the core
    "importlinter": lambda: importlinter_errors(REPO_ROOT),
    "codeowners": lambda: codeowners_errors(REPO_ROOT),
    "threat-model": lambda: threat_model_errors(),
    "lockfiles": lambda: lockfile_errors(REPO_ROOT),
    "action-pins": lambda: action_pin_errors(REPO_ROOT),
    "dependency-reviews": lambda: dependency_review_errors(REPO_ROOT),
    "licences": lambda: shipped_licence_errors(REPO_ROOT),
    "notices": lambda: notices_errors(REPO_ROOT),
    "vendored": lambda: vendored_errors(REPO_ROOT),
    "scope-trace": lambda: scope_trace_errors(),
    "offline-behaviour": lambda: offline_behaviour_errors(),  # PRD-03: every network use states its offline path
    "principle-trace": lambda: principle_trace_errors(),
    "review-template": lambda: review_template_errors(),
    "epic-scope": lambda: epic_scope_errors(),
    "proposals": lambda: _proposals(),
    "tools-snapshot": lambda: _tools_snapshot(),
    "skills": lambda: _skills(),
    "visual-renderers": lambda: _visual_renderers(),
    "prompt-snapshots": lambda: _prompt_snapshots(),
    "prompt-lint": lambda: _prompt_lint(),
    "schema-lint": lambda: _schema_lint(),
    "data-inventory": lambda: _data_inventory(),
    "stages": lambda: workflow_errors(load_workflow(REPO_ROOT / ".github" / "workflows" / "ci.yml")),
    "eval-lock": lambda: _eval_lock(),
    "eval-bank": lambda: _eval_bank(),
    "kc-coverage": lambda: _kc_coverage(),
    "test-names": lambda: _test_names(),  # plan Rule 6b: a requirement-prefixed test carries a spec test's name
    "installer-strings": lambda: _installer_strings(),  # LOC-01: the installer's words are keyed and generated
    "copy-lint": lambda: _copy_lint(),  # LRN-35: no dark patterns in any locale file
}
# Commands run explicitly by a CI stage, not by the default `python -m jana_tools`.
STAGE_COMMANDS: dict[str, Callable[[], list[str]]] = {}


def _test_names() -> list[str]:
    from .coverage import misnamed_test_errors

    return misnamed_test_errors(REPO_ROOT)


def _installer_strings() -> list[str]:
    from .release.installer_strings import installer_string_errors

    return installer_string_errors()


def _copy_lint() -> list[str]:
    from .copy_lint import copy_lint_errors

    return copy_lint_errors()


def _eval_lock() -> list[str]:
    from .harness.lock import lock_errors

    return lock_errors()


def _eval_bank() -> list[str]:
    from .harness.bank import build_bank, leakage_errors, shipped_hashes, training_hashes
    from .harness.lock import held_out_hashes

    _, errors = build_bank()
    return errors + leakage_errors(held_out_hashes(), shipped_hashes(), training_hashes())


def _git(*args: str) -> str:
    import subprocess

    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _memory_gate(report: dict[str, Any]) -> list[str]:
    """The MEM-23 gate on a harness report whose memory suite ran (EVL-08)."""
    from .harness.memory import SUITE, gate_errors

    if report.get("suites", {}).get(SUITE, {}).get("status") != "ran":
        return []
    return [f"memory: {e}" for e in gate_errors(report)]


def _lab(args: list[str]) -> int:
    """Device-lab measurements for a laptop's measurements file (EVL-14; M11), each printed as JSON:

    lab classbench <llama-server> <smallest gguf> [runs] [--offline]          PLT-08: the class each benchmark picks
    lab memfit <llama-server> <gguf> <context> [--mmproj F]                  MDL-17: estimate against resident memory
    lab capture-regression <llama-server> <gguf> <mmproj> <model id> <class> [--out D] [--only ids]  M21 development
    lab perception <llama-server> <gguf> <mmproj> <model id> <class> [set]   EVL-12: the printed set through the app
    lab overhead [turns] [--url U --key-file F --model M]                    OBS-24: tracing on against removed
    lab survey <survey.csv> [--machine ID]                                   PLT-29: append this machine's row"""

    def option(name: str) -> str | None:
        return args[args.index(name) + 1] if name in args else None

    if args[:1] == ["classbench"] and len(args) >= 3:
        from .harness.classbench import run as classbench

        runs = int(args[3]) if len(args) > 3 and args[3].isdigit() else None
        print(json.dumps(classbench(Path(args[1]), Path(args[2]), runs,
                                    "disabled" if "--offline" in args else "unknown"), indent=1))  # fmt: skip
        return 0
    if args[:1] == ["memfit"] and len(args) >= 4:
        from .harness.memfit import measure

        projector = option("--mmproj")
        print(json.dumps(measure(Path(args[1]), Path(args[2]), int(args[3]), Path(projector) if projector else None),
                         indent=1))  # fmt: skip
        return 0
    if args[:1] == ["capture-regression"] and len(args) >= 6:
        from .harness import report as rep
        from .harness.capture_eval import run_model
        from .harness.gate import gate_errors

        out = Path(option("--out") or REPO_ROOT / "evals" / "reports")
        out.mkdir(parents=True, exist_ok=True)
        try:
            report = run_model(
                Path(args[1]),
                Path(args[2]),
                Path(args[3]),
                args[4],
                args[5],
                only=set(selected.split(",")) if (selected := option("--only")) else None,
                progress=lambda ident: print(f"capture: {ident}", file=sys.stderr, flush=True),
                checkpoint=out / "capture-checkpoint.json",
            )
        except (ValueError, OSError, RuntimeError) as error:
            return _report("lab capture-regression", [str(error)])
        out = Path(option("--out") or REPO_ROOT / "evals" / "reports")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{report['run_id']}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
        (out / f"{report['run_id']}.md").write_text(rep.summary(report))
        print(rep.summary(report))
        failures = [
            f"{case['case_id']}: {case.get('reason', '')}" for case in report["cases"] if case["status"] == "failed"
        ]
        return _report("lab capture-regression", gate_errors(report) + failures)
    if args[:1] == ["perception"] and len(args) >= 6:
        from .harness.perception import PRINTED, run_local, set_errors

        folder = Path(args[6]) if len(args) > 6 else PRINTED
        problems = set_errors(folder)
        if problems:
            return _report("lab perception", problems)
        items = json.loads((folder / "set.json").read_text())["items"]
        try:
            result = run_local(Path(args[1]), Path(args[2]), Path(args[3]), args[4], items, folder, args[5])
        except (ValueError, OSError, RuntimeError) as error:
            return _report("lab perception", [str(error)])
        print(json.dumps(result, indent=1))
        return 0
    if args[:1] == ["overhead"]:
        from .harness.overhead import measure as overhead

        turns = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        url, key_file, model = option("--url"), option("--key-file"), option("--model")
        endpoint = (url, Path(key_file).read_text().strip(), model) if url and key_file and model else None
        print(json.dumps(overhead(turns, endpoint=endpoint), indent=1))
        return 0
    if args[:1] == ["overhead-child"] and len(args) in (4, 7):
        from .harness.overhead import child

        endpoint = (args[4], args[5], args[6]) if len(args) == 7 else None
        print(json.dumps(child(args[1], int(args[2]), int(args[3]), endpoint)))
        return 0
    if args[:1] == ["survey"] and len(args) >= 2:
        from .harness.survey import append_this_machine

        row = append_this_machine(Path(args[1]), option("--machine"))
        print(json.dumps(row, indent=1))
        return 0
    print(_lab.__doc__, file=sys.stderr)
    return 2


def _eval(args: list[str]) -> int:
    """eval lock [--write] | run [--release] [--stage S1..S5] [--only a,b] [--previous r.json] [--out dir]
    | gate <r.json> [--release] | commit-checks <rev range> | seal <suite> <items.yaml> | revision <entry.json>
      (EVL-01, EVL-18 to EVL-24)
    | oracles <url> <key> <model> <out dir> [--limit N] [--jobs N] [--hardware-class low|mid|high]
      (EVL-02 with a model in the loop; MDL-15)
    | personas <url> <key> <model> <out dir> [--items N] [--jobs N] [--hardware-class low|mid|high]
      (PED-08, MDL-15, MEM-20 on a local model)
    | memory <url> <key> <model> <out dir> [--runs N] [--hardware-class low|mid|high]
      (EVL-08, MEM-23 on a local model; `gate <out dir>/report.json` reads it)
    | classify <url> <key> <model> <set.yaml> <out dir> [--open] [--jobs N] [--hardware-class low|mid|high]
      (EVL-13: top-1 topic from the Diagnoser on a local model; the set lives outside the repository)
    | skills <url> <key> <model> <out dir> [--only name,name] [--jobs N]
      (SKL-21, EVL-07: the colocated skill evals on the local fast tier; writes evals/skill-evals/results.json)
    | skills-summary <out dir> <model>   (merge a partial skill-eval run into the records)
    | skill-outcomes [--pilot DIR] [--eval-runs DIR] [--out F]
      (SKL-28: mastery gain, hint use and answer-leak rate per skill version, and the edits that regressed them)
    | simulate <url> <key> <model> <out dir> [--sim-url U] [--sim-key K] [--sim-model M] [--jobs N] [--per-persona N]
      (EVL-04: simulated students on the pinned personas)
    | replay <trajectory.jsonl>   (OBS-10: replay with recorded model outputs; fails on any difference)"""
    from .harness import lock

    if args[:1] == ["classify"] and len(args) >= 6:
        from .harness.classification import run_live as classify

        hardware = args[args.index("--hardware-class") + 1] if "--hardware-class" in args else "mid"
        if hardware not in ("low", "mid", "high"):
            print("--hardware-class is low, mid or high", file=sys.stderr)
            return 2
        jobs = int(args[args.index("--jobs") + 1]) if "--jobs" in args else 3
        found = classify(args[1], args[2], args[3], Path(args[4]), Path(args[5]), scoped="--open" not in args,
                         jobs=jobs, hardware_class=hardware)  # fmt: skip
        shown = ("model", "mode", "total", "correct", "top1", "retrieval_top1", "retrieval_recall", "unusable_replies")
        print(json.dumps({k: found[k] for k in shown}))
        return _report("eval classify", found["gate_errors"])

    if args[:1] == ["simulate"] and len(args) >= 5:
        from .harness.simulator import run as simulate

        def opt(name: str) -> str | None:
            return args[args.index(name) + 1] if name in args else None

        found = simulate(args[1], args[2], args[3], Path(args[4]), opt("--sim-url"), opt("--sim-key"),
                         opt("--sim-model"), int(opt("--jobs") or 2),
                         int(opt("--per-persona")) if opt("--per-persona") else None)  # fmt: skip
        print(json.dumps({k: found[k] for k in ("runs", "scored", "discarded_broke_character", "detected_leaks",
                                                 "withheld_until_earned", "misconception_named")}))  # fmt: skip
        return 0
    if args[:1] == ["replay"] and len(args) >= 2:
        from .harness.trajectory import run_replay

        return _report("eval replay", run_replay(Path(args[1])))
    if args[:1] == ["skill-outcomes"]:
        from .skill_outcomes import report as skill_outcomes

        def given(name: str) -> Path | None:
            return Path(args[args.index(name) + 1]) if name in args else None

        found = skill_outcomes(given("--pilot"), given("--eval-runs"))
        if (out := given("--out")) is not None:
            out.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
        print(json.dumps(found["regressions"], indent=1))
        return 0
    if args[:1] == ["skills-summary"] and len(args) >= 3:
        from .skill_evals import gate_report, summarise

        summarise(Path(args[1]), args[2])
        print(json.dumps(gate_report()))
        return 0
    if args[:1] == ["skills"] and len(args) >= 5:
        from .skill_evals import gate_report, run_skills

        only = args[args.index("--only") + 1].split(",") if "--only" in args else None
        jobs = int(args[args.index("--jobs") + 1]) if "--jobs" in args else 3
        records = run_skills(args[1], args[2], args[3], Path(args[4]), only, jobs)
        print(json.dumps({n: f"{r['hard_passed']}/{r['hard_total']}" for n, r in records.items()
                          if only is None or n in only}))  # fmt: skip
        print(json.dumps(gate_report()))
        return 0
    if args[:1] == ["memory"] and len(args) >= 5:
        from .harness.memory import run_live

        hardware = args[args.index("--hardware-class") + 1] if "--hardware-class" in args else "mid"
        if hardware not in ("low", "mid", "high"):
            print("--hardware-class is low, mid or high", file=sys.stderr)
            return 2
        runs = int(args[args.index("--runs") + 1]) if "--runs" in args else 3
        result = run_live(args[1], args[2], args[3], Path(args[4]), hardware, runs)
        print(json.dumps({k: result[k] for k in ("model", "hardware_class", "notes_run", "criteria")}))
        return _report("eval memory", result["gate_errors"])
    if args[:1] == ["personas"] and len(args) >= 5:
        from .harness.personas import run as personas

        def count(name: str, default: int) -> int:
            return int(args[args.index(name) + 1]) if name in args else default

        hardware = args[args.index("--hardware-class") + 1] if "--hardware-class" in args else "mid"
        if hardware not in ("low", "mid", "high"):
            print("--hardware-class is low, mid or high", file=sys.stderr)
            return 2
        found = personas(args[1], args[2], args[3], Path(args[4]), count("--items", 10), count("--jobs", 1), hardware)
        print(json.dumps({k: found[k] for k in ("model", "runs", "detected_leaks", "withholding", "coach_first_pass")}
                         | {"mem20_over": len(found["mem20"]["over"])}))  # fmt: skip
        return 0
    if args[:1] == ["oracles"] and len(args) >= 5:
        from .harness.model_oracles import run as oracles

        def number(name: str) -> int | None:
            return int(args[args.index(name) + 1]) if name in args else None

        hardware = args[args.index("--hardware-class") + 1] if "--hardware-class" in args else "mid"
        if hardware not in ("low", "mid", "high"):
            print("--hardware-class is low, mid or high", file=sys.stderr)
            return 2
        result = oracles(args[1], args[2], args[3], Path(args[4]), number("--limit"), number("--jobs") or 1, hardware)
        shown = ("model", "hardware_class", "final_answer", "plans_verified", "first_turn_seconds_median")
        first = {k: result["structured_first_pass"][k] for k in ("passed", "total")}
        print(json.dumps({k: result[k] for k in shown} | {"structured_first_pass": first}))
        return 0

    if args == ["lock", "--write"]:
        lock.write_lock()
        print(f"eval: wrote {lock.LOCK.relative_to(REPO_ROOT)}")
        return 0
    if args == ["lock"]:
        return _report("eval lock", lock.lock_errors())
    if args[:1] == ["run"]:
        from .harness import report as rep
        from .harness.gate import gate_errors, release_errors
        from .harness.run import run

        def option(name: str) -> str | None:
            return args[args.index(name) + 1] if name in args else None

        mode = "release" if "--release" in args else "development"
        previous = json.loads(Path(p).read_text()) if (p := option("--previous")) else None
        only = set(o.split(",")) if (o := option("--only")) else None
        report = run(mode, build_stage=option("--stage") or "S1", only=only, previous=previous)
        out = Path(option("--out") or REPO_ROOT / "evals" / "reports")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{report['run_id']}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
        (out / f"{report['run_id']}.md").write_text(rep.summary(report))
        print(rep.summary(report))
        failed = [f"{c['suite']}/{c['case_id']}: {c.get('reason', '')}" for c in report["cases"]
                  if c["status"] == "failed"]  # fmt: skip
        return _report("eval run", gate_errors(report) + (release_errors(report) if mode == "release" else []) + failed
                       + _memory_gate(report))  # fmt: skip
    if args[:1] == ["gate"] and len(args) >= 2:
        from .harness.gate import gate_errors, release_errors
        from .harness.memory import SUITE
        from .harness.memory import gate_errors as memory_gate

        report = json.loads(Path(args[1]).read_text())
        if report.get("suite") == SUITE:  # a live memory report (eval memory)
            return _report("eval gate", memory_gate(report))
        return _report("eval gate", (release_errors(report, "--cloud" in args) if "--release" in args
                                     else gate_errors(report)) + _memory_gate(report))  # fmt: skip
    if args[:1] == ["commit-checks"] and len(args) == 2:
        from .harness.bank import build_bank
        from .harness.revisions import commit_errors, regression_errors

        errors = []
        decided = decided_decisions()
        for sha in _git("rev-list", "--no-merges", args[1]).split():
            modified = _git("diff-tree", "--no-commit-id", "--name-only", "--diff-filter=MR", "-r", sha).split()
            message = _git("log", "-1", "--format=%B", sha)
            errors += [f"{sha[:12]}: {e}" for e in commit_errors(message, modified, decided)]
        messages = [m for m in _git("log", "--no-merges", "--format=%B%x00", args[1]).split("\0") if m.strip()]
        changed = _git("diff", "--name-only", args[1]).split()
        items, _ = build_bank()
        return _report("eval commit-checks", errors + regression_errors(messages, items, changed))
    if args[:1] == ["seal"] and len(args) == 3:
        import os

        import yaml

        key = os.environ.get(lock.KEY_ENV)
        if not key:
            print(f"eval seal: set {lock.KEY_ENV} (the release key, kept outside the repository)", file=sys.stderr)
            return 2
        path = lock.seal(yaml.safe_load(Path(args[2]).read_text()), args[1], key)
        print(f"eval: sealed {path.relative_to(REPO_ROOT)}; bump the suite version and run: eval lock --write")
        return 0
    if args[:1] == ["revision"] and len(args) == 2:
        from .harness.revisions import RevisionError, append

        try:
            append(json.loads(Path(args[1]).read_text()))
        except RevisionError as error:
            return _report("eval revision", [str(error)])
        return 0
    print(_eval.__doc__, file=sys.stderr)
    return 2


def _release(args: list[str]) -> int:
    """release stage <S1..S5> [--junit F]... [--cargo F]... [--report F] [--gallery F] [--oracles F] [--bakeoff F]
    [--steps F] [--timings F] [--s2-evidence F] [--pilot-evidence F] [--m25-evidence DIR] [--pilot] [--tag vX.Y.Z]
    (EVL-17, PRD-11, PRD-17; --tag creates the tag only when all pass; --pilot: a closed pilot, labelled as one,
    before the pilot-measured exit metrics are met)
    | release gate <gate> --evidence F [--candidate SHA] [--field-evidence INDEX] [--date D]   (every gate of the
      decisions register: its undecided decisions and its own evidence; see jana_tools.release.gates)
    | release dpia-list --records DIR --created-at T --out F   (PRV-08: the unsigned DPIA list from signed records)
    | release compliance [--previous F] [--out F] [--models a,b]   (OPS-36)
    | release models   (MDL-27, MDL-28: the recommendations file and its bake-off records)
    | release publish <file> --kind K --id I --version V --attestation F [--signatures F]   (OPS-01, OPS-05;
      --kind app_update needs the offline signing's update-signatures.json, SEC-12, SEC-15)
    | release resources|runtime-fetch|bundle|sign-audit|antivirus|icons|smoke ...   (M20 packaging: see
      jana_tools.release.package_cli)"""
    import hashlib
    import subprocess

    from .release.package_cli import COMMANDS as PACKAGING

    if args[:1] == ["ops"]:
        from .release.operations_cli import run

        return run(args[1:])

    if args[:1] and args[0] in PACKAGING:
        return _report(f"release {args[0]}", PACKAGING[args[0]](args[1:]))

    def option(name: str) -> str | None:
        return args[args.index(name) + 1] if name in args else None

    def options(name: str) -> list[str]:
        return [args[i + 1] for i, a in enumerate(args) if a == name]

    def load(name: str) -> dict | None:
        path = option(name)
        return json.loads(Path(path).read_text()) if path else None

    if args[:1] == ["bakeoff-record"]:
        from .release.bakeoff import record, record_errors

        try:
            entry = record(
                load("--input") or {},
                candidate=option("--candidate") or "",
                run_id=option("--run-id") or "",
                created_at=option("--date") or "",
                weights_fixed_at=option("--weights-fixed-at") or "",
            )
            errors = record_errors(entry, candidate=option("--candidate"))
            if errors:
                return _report("release bakeoff-record", errors)
            output = option("--out")
            if output is None:
                return _report("release bakeoff-record", ["--out is required"])
            Path(output).write_text(json.dumps(entry, indent=2, allow_nan=False) + "\n")
            return _report("release bakeoff-record", [])
        except (OSError, ValueError, KeyError, TypeError) as error:
            return _report("release bakeoff-record", [str(error)])
    if args[:1] == ["prompt-record"]:
        from .release.prompts import AGENT, RUNS, record_evaluated_run

        try:
            record_evaluated_run(
                AGENT,
                [json.loads(Path(p).read_text()) for p in options("--report")],
                candidate=option("--candidate") or "",
                run_id=option("--run-id") or "",
                date=option("--date") or "",
                runs=Path(option("--out") or RUNS),
            )
            return _report("release prompt-record", [])
        except (OSError, ValueError, KeyError, TypeError) as error:
            return _report("release prompt-record", [str(error)])
    if args == ["models"]:  # MDL-27, MDL-28: the recommendations file and the bake-off records behind it
        from .release.models import release_errors

        return _report("release models", release_errors())
    if args[:1] == ["gate"] and len(args) >= 2:  # PRD-11 (c) and each gate's own evidence, for every register gate
        from datetime import date as day

        from .release.gates import gate_errors

        candidate = (
            option("--candidate")
            or subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        index = option("--field-evidence")
        try:
            errors = gate_errors(args[1], load("--evidence"), candidate=candidate,
                                 today=day.fromisoformat(option("--date") or day.today().isoformat()),
                                 field_index=Path(index) if index else None)  # fmt: skip
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors = [f"{args[1]}: {error}"]
        return _report(f"release gate {args[1]}", errors)
    if args[:1] == ["dpia-list"]:  # PRV-08: the unsigned DPIA list from the Safety lead's signed records
        from .release.dpia import build_list, record_errors

        folder = Path(option("--records") or "")
        try:
            records = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]
            problems = [e for r in records for e in record_errors(r, folder)]
            if problems:
                return _report("release dpia-list", problems)
            document = build_list(records, created_at=option("--created-at") or "")
            output = option("--out")
            if output is None:
                return _report("release dpia-list", ["--out is required"])
            Path(output).write_text(json.dumps(document, indent=2) + "\n")
            return _report("release dpia-list", [])
        except (OSError, ValueError, KeyError) as error:
            return _report("release dpia-list", [str(error)])
    if args[:1] == ["stage"] and len(args) >= 2:
        from .codegen import drift_metric
        from .coverage import cargo_results, junit_results, merge
        from .release.stage import exit_metrics, release_rule_failures, s1_gates
        from .spec import DOCS

        stage = args[1]
        results = merge(*[junit_results(Path(p)) for p in options("--junit")],
                        *[cargo_results(Path(p)) for p in options("--cargo")])  # fmt: skip
        report = load("--report")
        decision_path = DOCS / "specification/registers/decisions.json"
        # No approvals are inferred. release_rule_failures separately refuses a missing owner register.
        decisions = (
            {d["id"]: d["status"] for d in json.loads(decision_path.read_text())["decisions"]}
            if decision_path.is_file()
            else {}
        )
        gates = s1_gates(report or {}, gallery=load("--gallery"), model_oracles=load("--oracles"),
                         bakeoff=load("--bakeoff"), step_pairs=load("--steps"), decisions=decisions)  # fmt: skip
        if stage != "S1":
            from .release.evaluation import s2_gates

            gates = s2_gates(report or {}, evidence=load("--s2-evidence"), decisions=decisions)
            candidate = (report or {}).get("build", {}).get("commit")
            current = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
            if candidate != current:
                from .release.stage import Gate

                gates.append(
                    Gate(
                        "Evidence belongs to the candidate being released",
                        current,
                        str(candidate),
                        False,
                        "candidate commit",
                    )
                )
            if stage != "S2":
                from .release.stage import Gate

                gates.append(
                    Gate(
                        f"{stage} additional release gates",
                        "implemented stage gates",
                        "not implemented",
                        False,
                        "TABLE EVL-17a",
                    )
                )
        clean, total, _ = drift_metric(REPO_ROOT)
        closed_pilot = "--pilot" in args  # PRD-11: a closed pilot ships before the pilot-measured rows are met
        metrics = exit_metrics(stage, report, load("--timings"), (clean, total), evidence=load("--s2-evidence"),
                               pilot=load("--pilot-evidence"))  # fmt: skip
        failures = release_rule_failures(stage, results, metrics, closed_pilot=closed_pilot)
        if stage != "S1":
            from .m23.gates import release_errors as safety_release_errors

            failures["m23"] = safety_release_errors(
                load("--m23-evidence") or {},
                candidate=(report or {}).get("build", {}).get("commit", ""),
                stage=stage,
                gate={"S2": "s2_launch", "S3": "s3_launch", "S4": "s4_launch", "S5": "s5_launch"}[stage],
            )
            from agent_core.config import Settings

            from .m23.programme import product_report

            try:
                product = product_report(load("--product-metrics") or {}, Settings(**(load("--product-policy") or {})))
                if product["north_star"]["build"] != (report or {}).get("build", {}).get("commit"):
                    failures["product_guardrails"] = ["PRD-18: product evidence belongs to another candidate"]
                elif not product["release_allowed"]:
                    failures["product_guardrails"] = product["blocking"] or ["PRD-18: guardrail breach"]
            except (ValueError, KeyError, TypeError):
                failures["product_guardrails"] = ["PRD-18: missing or invalid product evidence/policy"]
        failures["gates"] = [f"{g.metric}: {g.measured} (needs {g.threshold}; {g.evidence})" for g in gates
                             if not g.passed]  # fmt: skip
        if stage != "S1":  # local models per class ship from S2 (D6): each needs its bake-off record (MDL-27)
            from .release.models import release_errors

            failures["models"] = release_errors()
            from .release.prompts import verified_release_errors as prompt_release_errors

            failures["prompts"] = prompt_release_errors(candidate=(report or {}).get("build", {}).get("commit"))
        if stage == "S2":  # M25: journeys per reference laptop, usability, teacher review, claims (JRN-02, EVL-21)
            from datetime import date as day

            from agent_core.config import Settings as S2Settings

            from .release.s2_evidence import m25_evidence_errors

            folder = option("--m25-evidence")
            failures.update(m25_evidence_errors(Path(folder) if folder else None, candidate=str(
                (report or {}).get("build", {}).get("commit", "")), results=results, metrics=metrics,
                today=day.today(), settings=S2Settings(), closed_pilot=closed_pilot))  # fmt: skip
        from .release.stage import pilot_pending

        pending = pilot_pending(metrics) if closed_pilot else []
        tag = option("--tag")
        if closed_pilot and tag and "pilot" not in tag:
            failures["label"] = [f"PRD-11: a closed-pilot release is labelled as a pilot; the tag {tag!r} is not"]
        print(json.dumps({"stage": stage, "closed_pilot": closed_pilot, "gates": [g.__dict__ for g in gates],
                          "exit_metrics": metrics, "pilot_pending": pending, "failures": failures}, indent=1,
                         default=str))  # fmt: skip
        blocked = [f"{k}: {item}" for k, items in failures.items() for item in items]
        if blocked:
            return _report(f"release {stage}", blocked)
        if tag:
            message = f"{stage} closed pilot release" if closed_pilot else f"{stage} release"
            if pending:
                message += "\n\nExit metrics reported at the end of the pilot:\n" + "\n".join(pending)
            subprocess.run(["git", "tag", "-a", tag, "-m", message], cwd=REPO_ROOT, check=True)
            print(f"release {stage}: tagged {tag}")
        return _report(f"release {stage}", [])
    if args[:1] == ["compliance"]:
        from .release import compliance

        components, _, packs, notices = compliance.current_inputs()
        models = [m for m in (option("--models") or "").split(",") if m]
        previous = load("--previous")
        record = compliance.record(components, previous["components_list"] if previous else None, packs, models,
                                   notices)  # fmt: skip
        record["components_list"] = components
        if out := option("--out"):
            Path(out).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
        return _report("release compliance", record["blocking"])
    if args[:1] == ["publish"] and len(args) >= 2:
        from .release.provenance import provenance_errors
        from .release.versions import ImmutableVersionError, Ledger

        file = Path(args[1])
        attestation = load("--attestation") or {}
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        errors = provenance_errors(attestation, REPO_ROOT)
        if attestation.get("sha256") != sha:
            errors.append("the attestation's sha256 does not match the artefact")
        if option("--kind") == "app_update":
            # SEC-12, SEC-15: an app update is published only as the offline signing signed it (owner ruling
            # 2026-10-17), its signature checked against the updater public key the app ships.
            from signing_service.updater import UpdateSigningRefused, configured_public_key, signed_entry

            signatures = option("--signatures")
            try:
                if signatures is None:
                    raise UpdateSigningRefused("an app update needs --signatures <folder>/update-signatures.json")
                signed_entry(Path(signatures), file, configured_public_key())
            except UpdateSigningRefused as error:
                errors.append(f"SEC-15: {error}")
        if not errors:
            try:
                Ledger().publish(str(option("--kind")), str(option("--id")), str(option("--version")), sha)
            except (ImmutableVersionError, ValueError) as error:
                errors.append(str(error))
        return _report("release publish", errors)
    print(_release.__doc__, file=sys.stderr)
    return 2


def _tools_snapshot() -> list[str]:
    from .toolcheck import committed, snapshot, snapshot_errors

    return snapshot_errors(snapshot(), committed())


def _schema_lint() -> list[str]:
    from agent_core.store.generated.schema import DATABASES
    from agent_core.store.sqlite import connect

    from .schema_lint import lint

    conn = connect(":memory:")
    try:
        # An in-memory database has no write-ahead log; the journal mode is checked on a file by dat03_schema_lint.
        return [e for e in lint(DATABASES, conn) if not e.startswith("pragma journal_mode")]
    finally:
        conn.close()


def _data_inventory() -> list[str]:
    from agent_core.store.generated.schema import DATABASES

    from .data_inventory import inventory_errors

    return inventory_errors(DATABASES)


def _prompt_snapshots() -> list[str]:
    from .prompt_snapshots import diff_errors

    return diff_errors()


def _skills() -> list[str]:
    from .skills import check, kc_skill_coverage

    found = kc_skill_coverage()
    mapped = sum(1 for r in found.rows if r.skill)
    print(f"skills: {mapped} of {len(found.rows)} KCs of the {found.stage} launched packs map to one teaching skill; "
          f"{len(found.awaiting_review)} teaching skills await review (SKL-18)")  # fmt: skip
    from .skill_evals import minimum_errors, review_errors

    return check() + minimum_errors() + review_errors()  # SKL-21, EVL-07


def _prompt_lint() -> list[str]:
    """PRM-21 marked writing techniques, PRM-01 soul shape and LOC-22 readability of lessons and interface copy."""
    from agent_core.assets.agent import AgentAssets, soul_problems
    from agent_core.engine.assembly import DEV_SKILL_STATUSES
    from agent_core.prompts.lint import technique_findings
    from agent_core.tools.specs import registry

    from .readability import lint_errors
    from .skills import SKILLS

    assets = AgentAssets.load(REPO_ROOT / "content" / "agent", SKILLS, DEV_SKILL_STATUSES)
    soul = [f"soul: {p}" for p in soul_problems(assets.soul, set(registry().specs))]
    return technique_findings(assets) + soul + lint_errors()


def _visual_renderers() -> list[str]:
    from .visual_parity import check

    return check()


def _proposals() -> list[str]:
    from .proposals import proposal_errors, proposal_report

    print(f"proposals: {proposal_report()}")
    return proposal_errors()


def _kc_coverage() -> list[str]:
    from .kc_coverage import matrix

    found = matrix()
    print(f"kc-coverage: {sum(len(p.rows) for p in found.packs)} KCs in {len(found.packs)} launched packs at "
          f"{found.stage}; {len(found.pending)} launched pairs have no pack yet")  # fmt: skip
    return found.errors


def _codegen_check() -> list[str]:
    from .codegen import stale_errors

    return stale_errors(REPO_ROOT)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] == ["m23"]:
        from .m23.cli import main as m23_main

        return m23_main(args[1:])
    if args[:1] == ["evidence"]:
        from .evidence.cli import main as evidence_main

        return evidence_main(args[1:])
    if args[:1] == ["stages-needs"]:
        # Gate job: python -m jana_tools stages-needs '<toJSON(needs)>'
        return _report("stages-needs", needs_errors(json.loads(args[1])))
    if args == ["importlinter", "--write"]:
        (REPO_ROOT / ".importlinter").write_text(render_importlinter())
        return 0
    if args[:1] == ["boundary-review"]:
        # boundary-review <changed-files.txt> <approver> [<approver> ...]  (SEC-02, pull requests)
        changed = Path(args[1]).read_text().split()
        codeowners = (REPO_ROOT / ".github" / "CODEOWNERS").read_text()
        approvers = {"@" + login.lstrip("@") for login in args[2:]}
        return _report("boundary-review", missing_approvals(changed, approvers, codeowners))
    if args == ["codegen"]:
        from .codegen import generate

        generate(REPO_ROOT)
        print("codegen: bindings regenerated")
        return 0
    if args == ["codegen", "--metric"]:
        from .codegen import drift_metric

        clean, total, errors = drift_metric(REPO_ROOT)
        print(f"codegen: {clean}/{total} contracts generate types with zero drift ({100 * clean // total}%)")
        return _report("codegen", errors)
    if args == ["codegen", "--check"]:
        return _report("codegen", _codegen_check())
    if args == ["fixtures", "--write"]:
        from .fixtures import build, write_corpus

        files, failed = build()
        write_corpus(files)
        for f in failed:
            print(f"fixtures: cannot synthesise {f}", file=sys.stderr)
        print(f"fixtures: wrote {len(files) - 1} fixtures")
        return 1 if failed else 0
    if args == ["recordings", "--write"]:
        from .recordings import write as write_recordings

        for path in write_recordings():
            print(f"recordings: wrote {path.relative_to(REPO_ROOT)}")
        return 0
    if args == ["fixtures", "--check"]:
        from .fixtures import corpus_errors

        return _report("fixtures", corpus_errors())
    if args[:1] == ["lab"]:
        return _lab(args[1:])
    if args[:1] == ["eval"]:
        return _eval(args[1:])
    if args[:1] == ["release"]:
        return _release(args[1:])
    if args[:1] == ["trace"] and len(args) >= 3:
        # trace list <source> | trace show <source> <trace id> | trace diff <source> <trace id> <trace id> (OBS-09)
        from .traceview import diff, listing, load, waterfall

        traces = {t["trace_id"]: t for t in load(Path(args[2]))}
        if args[1] == "list":
            print("\n".join(listing(list(traces.values()))))
            return 0
        if args[1] == "show" and len(args) == 4 and args[3] in traces:
            print("\n".join(waterfall(traces[args[3]])))
            return 0
        if args[1] == "diff" and len(args) == 5 and args[3] in traces and args[4] in traces:
            print("\n".join(diff(traces[args[3]], traces[args[4]])) or "no fingerprint differs")
            return 0
        print("usage: trace list|show|diff <traces.db or JSON> [trace id] [trace id]", file=sys.stderr)
        return 2
    if args == ["installer-strings", "--write"]:  # LOC-01: regenerate installer/strings.nsh from strings.json
        from .release.installer_strings import write as write_installer_strings

        print(f"installer-strings: wrote {write_installer_strings().relative_to(REPO_ROOT)}")
        return 0
    if args == ["golden", "--write"]:
        import json as _json

        from .golden import FINGERPRINTS, fingerprints, write

        paths = write()
        FINGERPRINTS.write_text(_json.dumps(fingerprints(), indent=1) + "\n")
        print(f"golden: wrote {len(paths)} sets and their fingerprints")
        return 0
    if args[:1] == ["cassettes"] and len(args) >= 5 and args[1] == "--record":
        from .cassettes import record

        suffix = ".inline-think" if "--inline-think" in args else ""
        for path in record(args[2], args[3], args[4], suffix):
            print(f"cassettes: wrote {path.relative_to(path.parents[3])}")
        return 0
    if args == ["prompt-snapshots", "--write"]:
        from .prompt_snapshots import write as write_snapshots

        print(f"prompt-snapshots: wrote {write_snapshots()} snapshots")
        return 0
    if args == ["prompt-snapshots", "--review-status"]:
        from .prompt_snapshots import review_errors

        return _report("prompt-snapshots review", review_errors())
    if args[:2] == ["prompt-snapshots", "--approve"] and len(args) == 3:
        from .prompt_snapshots import approve

        print(f"prompt-snapshots: {approve(args[2])} snapshots approved by {args[2]}")
        return 0
    if args == ["scenarios"]:
        from .scenarios import run_suites

        results = run_suites()
        for result in results:
            print(f"scenarios: {result.scenario_id}: {result.status} {result.reason}".rstrip())
        return 1 if any(r.status == "failed" for r in results) else 0
    if args[:1] == ["live-session"] and len(args) in (5, 6):
        from .live_session import run as live

        for summary in live(args[1], args[2], args[3], Path(args[4]), int(args[5]) if len(args) == 6 else 1):
            print(json.dumps({k: summary[k] for k in ("model", "plan_verified", "solved", "board_numbers_checked")}))
        return 0
    if args == ["worker-bench"]:
        import json as _json

        from .bench import bench

        print(_json.dumps(bench(), indent=2))
        return 0
    if args[:1] == ["kc-coverage"] and len(args) <= 2:  # VER-36: the KC → checker matrix of a stage
        from .kc_coverage import STAGE, matrix, render

        found = matrix(args[1] if len(args) == 2 else STAGE)
        print(render(found), end="")
        return 1 if found.errors else 0
    if args == ["worker-bench", "--lab"]:  # VER-28 timings for a reference laptop's device-lab measurements file
        from .bench import lab

        print(json.dumps(lab(), indent=2))
        return 0
    if args[:1] == ["visual-fixtures"] and len(args) <= 2:  # VSL-03, VSL-31, VSL-35: engine-resolved visual fixtures
        from .visual_fixtures import stale
        from .visual_fixtures import write as write_fixtures

        if args[1:] == ["--write"]:
            return _report("visual-fixtures", write_fixtures())
        return _report("visual-fixtures", stale())
    if args == ["tools-snapshot", "--write"]:
        from .toolcheck import write

        write()
        print("tools-snapshot: written")
        return 0
    if args[:1] == ["feature-review"]:
        # feature-review <pr-body.md> <changed-files.txt>  (PRV-01, PRD-20; pull requests)
        body = Path(args[1]).read_text()
        changed = Path(args[2]).read_text().split()
        errors = feature_review_errors(body, changed, decided_decisions(), feature_review_paths())
        return _report("feature-review", errors)
    if args[:1] == ["coverage"]:
        # coverage <milestone> [--junit results.xml]  (plan section 7.5)
        from .coverage import coverage, render

        junit = [Path(args[i + 1]) for i, a in enumerate(args) if a == "--junit"]
        cargo = [Path(args[i + 1]) for i, a in enumerate(args) if a == "--cargo"]
        print(render(args[1], coverage(args[1], junit, cargo=cargo)), end="")
        return 0
    if args[:1] == ["sbom"]:
        # sbom <out-dir>: one CycloneDX SBOM per release artefact
        per_artefact = write_sboms(Path(args[1]))
        print(f"sbom: wrote {len(per_artefact)} SBOMs to {args[1]}")
        return 0
    if args == ["notices", "--write"]:
        from .supply_chain import ARTEFACTS, artefact_components

        notices = render_notices({a.name: artefact_components(a, REPO_ROOT) for a in ARTEFACTS})
        (REPO_ROOT / "THIRD_PARTY_NOTICES").write_text(notices)
        return 0
    if args == ["codeowners", "--write"]:
        (REPO_ROOT / ".github" / "CODEOWNERS").write_text(render_codeowners(load_boundaries()))
        return 0
    names = args or list(CHECKS)
    failed = False
    for name in names:
        check = CHECKS.get(name) or STAGE_COMMANDS.get(name)
        if check is None:
            print(f"unknown check {name!r}; choose from {', '.join([*CHECKS, *STAGE_COMMANDS])}", file=sys.stderr)
            return 2
        failed = _report(name, check()) != 0 or failed
    return 1 if failed else 0


def _report(name: str, errors: list[str]) -> int:
    for error in errors:
        print(f"{name}: {error}", file=sys.stderr)
    print(f"{name}: {'FAIL' if errors else 'ok'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
