"""Local M23 commands. Evidence validation never constitutes owner approval."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from . import gates, programme, training


def main(args: list[str]) -> int:
    def option(flag: str, default: str = "") -> str:
        return args[args.index(flag) + 1] if flag in args else default

    def load(flag: str) -> dict[str, Any]:
        path = option(flag)
        return dict(json.loads(Path(path).read_text())) if path else {}

    try:
        command = args[0] if args else ""
        errors: list[str] = []
        result: Any = None
        from ..release.stage import undecided_for_gate

        if command == "release-check":
            errors = gates.release_errors(
                load("--evidence"),
                candidate=option("--candidate"),
                stage=option("--stage"),
                gate=option("--gate"),
                today=date.fromisoformat(option("--date", date.today().isoformat())),
            )
            errors += [f"decision {d}" for d in undecided_for_gate(option("--gate"))]  # PRD-11 (c)
        elif command in ("pilot-check", "pilot-start-check"):
            evidence = load("--evidence")
            errors = programme.country_errors(evidence.get("country", {}))
            errors += programme.protocol_errors(evidence.get("protocol", {}))
            errors += programme.wtp_errors(evidence.get("wtp", {}))
            errors += programme.experiment_errors(evidence.get("experiments", []))
            country = evidence.get("country", {}).get("country")
            if any(evidence.get(key, {}).get("country") != country for key in ("protocol", "wtp")):
                errors.append("M23: country differs across the programme records")
            if command == "pilot-start-check":
                errors += [f"decision {d}" for d in undecided_for_gate("pilot_start")]  # PRD-11 (c)
                errors += gates.release_errors(
                    evidence.get("release", {}),
                    candidate=option("--candidate"),
                    stage=option("--stage", "S2"),
                    gate="pilot_start",
                )
                if evidence.get("release", {}).get("counsel", {}).get("country") != country:
                    errors.append("PRV-07: counsel country differs from pilot country")
            if not errors:
                protocol = evidence["protocol"]
                result = {
                    "protocol_id": protocol["id"],
                    "registered_at": protocol["registered_at"],
                    "baseline_at": protocol["baseline_at"],
                    "starts_at": protocol["starts_at"],
                    "analysis_sha256": protocol["analysis_script"]["sha256"],
                }
        elif command == "metrics-catalogue":
            from agent_core.trace.metrics import catalogue

            raw = load("--input")
            result = catalogue(raw.get("traces", []), raw.get("logs", []))
        elif command == "dashboard":
            from .dashboard import dashboard

            result = dashboard(load("--input").get("records", []))
        elif command == "product-report":
            from agent_core.config import Settings

            result = programme.product_report(load("--input"), Settings(**load("--policy")))
        elif command == "business-report":
            raw = load("--input")
            result = programme.business_report(raw.get("metrics", {}), window=raw["window"])
        elif command == "training-authorize":
            if not option("--out"):
                raise ValueError("--out is required for training receipts")
            result = training.authorize_run(
                load("--input"), load("--records"), Path(option("--out")), now=option("--date")
            )
        elif command == "dataset-build":
            if Path(option("--input")).suffix in (".janadiag", ".janaresearch", ".janaprofile"):
                raise ValueError("student_data_refused")
            records = [json.loads(line) for line in Path(option("--input")).read_text().splitlines() if line.strip()]
            result = training.build_dataset(records, Path(option("--out")))
        elif command == "security-release":
            result = gates.security_release(
                Path(option("--update-pack")),
                Path(option("--out")),
                version=option("--version"),
                contacts=load("--contacts").get("contacts", []),
            )
        else:
            errors = [
                "usage: m23 release-check|pilot-check|product-report|business-report|training-authorize|"
                "dataset-build|security-release"
            ]
        print(json.dumps({"errors": errors, "result": result}, indent=2, allow_nan=False))
        return int(bool(errors))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"errors": [str(error)]}))
        return 1
