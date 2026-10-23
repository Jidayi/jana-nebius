"""Reassess only the documented osmosis keyword-oracle correction; preserve original model observations."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .m42 import read, sha, write_new

CASE = "bio-osmosis-chat"


def reassess(
    report: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    before_sha: str,
    after_sha: str,
    report_sha: str,
) -> dict[str, Any]:
    allowed = copy.deepcopy(before)
    allowed["version"] = 2
    next(c for c in allowed["cases"] if c["id"] == CASE)["concepts"] = ["metabolic", "energy"]
    if after != allowed or report.get("corpus_sha256") != before_sha:
        raise ValueError("not the documented concepts-only oracle correction")
    expected = {c["id"] for c in after["cases"]}
    actual = [c["id"] for c in report.get("cases", [])]
    if not report.get("complete") or set(actual) != expected or len(actual) != len(expected):
        raise ValueError("a complete original run is required; no selective replacement of failures")
    revised = copy.deepcopy(report)
    row = next(c for c in revised["cases"] if c["id"] == CASE)
    if not row["passed"]:
        if (
            row.get("http_status") != 200
            or row.get("cleanup_ack") is not True
            or not row.get("failure", "").startswith("AssertionError: assert False")
        ):
            raise ValueError("not a keyword-oracle failure; model refusals cannot be rescored as passing")
        traces = row.get("synthetic_provider_trace", [])
        verdict = json.loads(traces[-1]["choices"][0]["message"]["content"]) if traces else {}
        if verdict.get("supported") is not True or verdict.get("answerable") is not True:
            raise ValueError("independent gateway support/answerability evidence absent")
        source = next(c for c in after["cases"] if c["id"] == CASE)["sources"][0]
        claims = row["response"]["claims"]
        if not claims or not any("energy" in c["text"].lower() for c in claims):
            raise ValueError("the requested energy answer is absent")
        for claim in claims:
            if not claim["citations"]:
                raise ValueError("uncited answer")
            for citation in claim["citations"]:
                if source[citation["start"] : citation["end"]] != citation["quote"]:
                    raise ValueError("citation not exact")
        row["original_passed"] = False
        row["original_failure"] = row.pop("failure")
        row["passed"] = True
        row["oracle_reassessment"] = "Only energy/metabolic anchors corrected; source, request and support unchanged."
    revised["original_report_sha256"] = report_sha
    revised["original_corpus_sha256"] = before_sha
    revised["corpus_sha256"] = after_sha
    revised["passed"] = all(c["passed"] for c in revised["cases"])
    revised["evaluation_note"] = (
        "Reviewed development oracle amendment; original run retained. No new model run claimed."
    )
    return revised


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "before", "after", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = reassess(
        read(args.report),
        read(args.before),
        read(args.after),
        before_sha=sha(args.before),
        after_sha=sha(args.after),
        report_sha=sha(args.report),
    )
    write_new(args.out, result)
    print(f"M42 reassessment: {sum(c['passed'] for c in result['cases'])}/{len(result['cases'])}; original retained")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
