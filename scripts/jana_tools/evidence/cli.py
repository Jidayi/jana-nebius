"""`uv run python -m jana_tools evidence ...`: the owner's launch-evidence kit (guide:
scripts/governance/evidence/README.md). Nothing here sends a message, contacts a school or records an event that a
person did not observe and enter."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

USAGE = """usage: python -m jana_tools evidence <command>
  list                                   every record and drill, with requirement ids
  targets                                the current numeric targets the gates apply (named config keys)
  new <record|all> [--to DIR]            copy fill-in templates to your private governance folder
  check <record> FILE [--candidate C] [--stage S] [--gate G] [--date YYYY-MM-DD]
                                         what the gate says about one filled record
  assemble [--from DIR] --candidate C --gate G [--stage S2]
                                         write release.json (and programme.json) from the filled records
  drill <drill|test> [--folder DIR] [--answers FILE] [--candidate C] [--dry-run]
                                         run a device test or drill checklist and write its evidence
  remark --data DIR --old ITEM --new ITEM [--release] [--out FILE]
                                         wrong-key drill: re-mark a withdrawn item's attempts on a test device
                                         (app closed) and print the numbers the checklist asks for
  status [--folder DIR] [--candidate C]  what each JANA_M24_EVIDENCE check would say about a folder
  templates [--write]                    check (or regenerate) the M24 templates from the drill checklists"""


def main(args: list[str]) -> int:
    from .runner import evidence_home, outside_repository

    def option(flag: str, default: str = "") -> str:
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default

    command = args[0] if args else ""
    try:
        if command == "list":
            return _list()
        if command == "targets":
            return _targets()
        if command == "new" and len(args) >= 2:
            from .templates import GOVERNANCE, TEMPLATES

            target = Path(option("--to") or evidence_home() / "governance").expanduser()
            outside_repository(target)
            target.mkdir(parents=True, exist_ok=True)
            names = list(GOVERNANCE) if args[1] == "all" else [args[1]]
            for name in names:
                if name not in GOVERNANCE:
                    raise ValueError(f"unknown record {name!r}; choose from {', '.join(GOVERNANCE)}")
                destination = target / f"{name}.json"
                if destination.exists():
                    print(f"kept {destination} (already exists)")
                    continue
                shutil.copyfile(TEMPLATES / f"{name}.json", destination)
                print(f"wrote {destination}")
            print("Replace every FILL-IN value, then: python -m jana_tools evidence check <record> <file>")
            return 0
        if command == "check" and len(args) >= 3:
            from .records import record_errors

            record = json.loads(Path(args[2]).read_text())
            today = date.fromisoformat(option("--date", date.today().isoformat()))
            errors = record_errors(
                args[1],
                record,
                candidate=option("--candidate"),
                stage=option("--stage", "S2"),
                gate=option("--gate") or None,
                today=today,
            )
            return _report(f"{args[1]} {args[2]}", errors)
        if command == "assemble":
            from .records import assemble

            folder = Path(option("--from") or evidence_home() / "governance").expanduser()
            outside_repository(folder)
            if not option("--candidate") or not option("--gate"):
                raise ValueError("--candidate and --gate are required")
            result = assemble(
                folder, candidate=option("--candidate"), stage=option("--stage", "S2"), gate=option("--gate")
            )
            for path in result["written"].values():
                print(f"wrote {path}")
            if "programme" in result["written"] and option("--gate") == "pilot_start":
                print(
                    "next: uv run python -m jana_tools m23 pilot-start-check --evidence "
                    f"{result['written']['programme']} --candidate {option('--candidate')} --stage S2"
                )
            return _report("release evidence", result["release_errors"])
        if command == "drill" and len(args) >= 2:
            return _drill(args[1], option, dry_run="--dry-run" in args)
        if command == "remark":
            from .remark import run as remark

            if not option("--data") or not option("--old") or not option("--new"):
                raise ValueError("--data, --old and --new are required")
            out = Path(option("--out")).expanduser() if option("--out") else None
            result = remark(Path(option("--data")).expanduser(), option("--old"), option("--new"),
                            release="--release" in args, out=out)  # fmt: skip
            print(json.dumps(result["device"], indent=2))
            if out is not None:
                print(f"wrote {out} (give it as the drill's log proof)")
            return 0
        if command == "status":
            from .runner import current_candidate

            candidate = option("--candidate") or current_candidate()
            folder = Path(option("--folder") or evidence_home() / "m24" / candidate[:12]).expanduser()
            return _status(folder, candidate)
        if command == "templates":
            from .templates import stale_templates, write_templates

            if "--write" in args:
                for name in write_templates():
                    print(f"wrote {name}")
                return 0
            return _report("evidence templates", stale_templates())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        return 1
    print(USAGE)
    return 2


FIELD_SUITE = "scripts/tests/test_m24_field_evidence.py"


def _report(label: str, errors: list[str]) -> int:
    if errors:
        print(f"{label}: REFUSED ({len(errors)} problem{'s' if len(errors) != 1 else ''})")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"{label}: no problems found by the gate")
    return 0


def _list() -> int:
    from .drills import DRILLS
    from .templates import GOVERNANCE

    print("Records you fill in (python -m jana_tools evidence new <record>):")
    for name, (_, ids, what) in GOVERNANCE.items():
        print(f"  {name:<12} {ids:<34} {what}")
    print("\nDevice tests and drills (python -m jana_tools evidence drill <drill>):")
    for drill in DRILLS.values():
        print(f"  {drill.id:<12} {drill.requirements:<34} {drill.title}")
        print(f"  {'':<12} tests: {', '.join(drill.tests)}")
    return 0


TARGET_KEYS = (
    "redteam_max_age_days", "incident_triage_hours", "incident_review_workdays", "security_fuzz_hours_per_target",
    "pilot_min_weeks", "pilot_max_weeks", "pilot_min_effect_sd", "wtp_parent_min", "wtp_school_owner_min",
    "ops_sev1_ack_hours", "ops_sev1_contain_hours", "ops_sev2_ack_hours", "ops_sev2_contain_days",
    "ops_school_notice_hours", "ops_support_open_hour", "ops_support_close_hour", "ops_triage_school_days",
    "ops_withdraw_hours", "ops_correction_days", "ops_usb_sample_every", "ops_usb_min_samples",
    "ops_switch_max_age_s", "ops_switch_response_s", "ops_failback_healthy_s", "ops_alert_delay_s",
    "ops_first_words_median_s", "ops_first_words_p95_s", "ops_peak_share", "ops_load_multiple",
    "ops_capacity_multiple", "ops_drill_quarter_days", "ops_drill_halfyear_days", "ops_drill_year_days",
    "build_stage",
)  # fmt: skip


def _targets() -> int:
    from agent_core.config import Settings

    from ..release import incidents as inc
    from ..release import operations as ops

    cfg = Settings()
    print("Targets the gates apply now (agent_core/config/keys.py):")
    for key in TARGET_KEYS:
        print(f"  {key:<34} {getattr(cfg, key)}")
    print("\nService objectives (availability, p95 seconds):")
    for service, (availability, p95) in ops.slo_objectives(cfg).items():
        print(f"  {service:<34} {availability}, {p95 if p95 is not None else '-'}")
    print(f"\nRunbook drills for {cfg.build_stage} (name: frequency):")
    for name, frequency in inc.required_drills(cfg.build_stage).items():
        print(f"  {name:<34} {frequency}")
    return 0


def _drill(name: str, option: Any, *, dry_run: bool) -> int:
    from .drills import DRILLS, drill_for
    from .runner import Interactive, Rehearsal, Scripted, current_candidate, current_spec, evidence_home, run

    drill = DRILLS.get(name) or drill_for(name)
    candidate = option("--candidate") or current_candidate()
    if dry_run:
        folder = Path(option("--folder") or tempfile.mkdtemp(prefix="jana-dry-run-")).expanduser()
        source: Any = Rehearsal()
    else:
        folder = Path(option("--folder") or evidence_home() / "m24" / candidate[:12]).expanduser()
        answers = option("--answers")
        source = Scripted(json.loads(Path(answers).read_text()), quiet=False) if answers else Interactive()
    result = run(drill, folder, source, candidate=candidate, spec_revision=current_spec())
    print()
    for path in result["written"]:
        print(f"wrote {path}")
    print(f"index: {result['index']}")
    for test, errors in result["verdict"].items():
        if dry_run:
            print(f"{test}: refused by the gate, as a dry run must be ({errors[0] if errors else 'unexpected pass'})")
        elif errors:
            print(f"{test}: the gate would REFUSE this record:")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"{test}: the gate accepts this record")
    if dry_run:
        print("\nDry run only: nothing written here is evidence. Delete the folder when done.")
        return 0 if all(result["verdict"].values()) else 1
    print(f"\nCheck the folder: JANA_M24_EVIDENCE={result['index']} uv run pytest {FIELD_SUITE}")
    return 0 if not any(result["verdict"].values()) else 1


def _status(folder: Path, candidate: str) -> int:
    from ..release.field_evidence import SOURCES
    from .runner import check, index_path

    index_file = index_path(folder)
    if not index_file.is_file():
        print(f"no evidence index at {index_file}")
        return 1
    present = json.loads(index_file.read_text()).get("records", {})
    failing = 0
    for name in SOURCES:
        if name not in present:
            print(f"  missing  {name}")
            failing += 1
            continue
        errors = check(index_file, name, candidate=candidate)
        failing += bool(errors)
        print(f"  {'ok' if not errors else 'REFUSED':<8} {name}" + (f": {'; '.join(errors)}" if errors else ""))
    print(f"\n{len(SOURCES) - failing} of {len(SOURCES)} records would pass for candidate {candidate}")
    return int(bool(failing))
