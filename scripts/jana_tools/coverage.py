"""Acceptance-test coverage report (plan section 7.5): for each requirement of a milestone, the named
acceptance tests found in the code and their results from a JUnit XML run.

Usage: python -m jana_tools coverage M0 [--junit results.xml]... [--cargo cargo-test.txt]...

Results merge across files (pytest and Vitest JUnit, `cargo test` output): a test that fails anywhere fails."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import REPO_ROOT
from .repo import repo_paths
from .spec import DOCS, requirements

_NAME = r"([a-z]{3}\d{2}_[a-z0-9_]*[a-z0-9])"
# Every form the repository's tests are written in (plan Rule 6b): a Python `def`/`async def`; a Vitest title that is
# the name alone or the name then words, `test(`, `it(` and their modifiers (`test.skip(`, `it.skipIf(cond)(`,
# `test.each(rows)(`, with rows over several lines), in any quote; a Rust `fn`, plain or async. The Vitest JUnit report
# names a case by the title's first word (junit_results), so the name ends at a space, a quote, a colon or `%`.
_TS_TITLE = rf"""\(\s*["'`]{_NAME}(?=[\s"'`:%])"""
_TEST_DEF = re.compile(
    rf"^\s*(?:async\s+)?def\s+{_NAME}\s*\("  # Python
    rf"|\b(?:test|it)(?:\s*\.\s*\w+)*(?:\((?:[^()]|\([^()]*\))*\))?{_TS_TITLE}"  # Vitest: test(, test.x(, test.each(r)(
    rf"|\)\s*{_TS_TITLE}"  # Vitest: the title call of a `test.each([...])(` whose rows span lines
    rf"|\b(?:async\s+)?fn\s+{_NAME}\s*\(",  # Rust
    re.MULTILINE,
)
# A test definition in a test file, whatever its name: what the Rule 6b check reads (misnamed_test_errors).
_ANY_TEST = re.compile(
    r"^\s*(?:async\s+)?def\s+(\w+)\s*\("  # Python
    r"""|\b(?:test|it)(?:\s*\.\s*\w+)*(?:\((?:[^()]|\([^()]*\))*\))?\(\s*["'`]([^\s"'`:%]+)"""  # Vitest
    r"""|\)\s*\(\s*["'`]([^\s"'`:%]+)"""  # Vitest each over several lines
    r"|#\[(?:tokio::)?test[^\]]*\]\s*(?:#\[[^\]]*\]\s*)*(?:async\s+)?fn\s+(\w+)\s*\(",  # Rust
    re.MULTILINE,
)
_PREFIX = re.compile(r"^[a-z]{3}\d{2}_")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".rs", ".mjs", ".js"}


@dataclass(frozen=True)
class Row:
    requirement: str
    priority: str
    work_package: str
    tests: dict[str, str]  # test name -> pass | fail | skipped | not run | missing


def primary_requirements(milestone: str, docs: Path = DOCS) -> list[tuple[str, str]]:
    """(work package, requirement ID) for each primary requirement of a milestone, from the plan."""
    plan = (docs / "implementation" / "plan.md").read_text()
    rows = re.findall(rf"^\| ({milestone}\.[a-z]) — [^|]+\| [^|]+\| ([^|]+) \|", plan, re.MULTILINE)
    return [(wp, rid) for wp, ids in rows for rid in re.findall(r"[A-Z0-9]{3}-\d{2}", ids)]


def acceptance_tests(rid: str, docs: Path = DOCS) -> list[str]:
    req = requirements(docs)[rid]
    text = req.file.read_text()
    block = text.split(f"### {rid} — ", 1)[1].split("\n### ", 1)[0]
    acceptance = block.split("\nAcceptance:", 1)[1] if "\nAcceptance:" in block else ""
    prefix = rid.replace("-", "").lower()
    return list(dict.fromkeys(re.findall(rf"`({prefix}_[a-z0-9_]+)`", acceptance)))


def _sources(root: Path) -> list[str]:
    return [r for r in repo_paths(root) if Path(r).suffix in SOURCE_SUFFIXES and not r.startswith("apps/prototype-s0/")]


def defined_test_locations(root: Path = REPO_ROOT) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in _sources(root):
        for match in _TEST_DEF.finditer((root / rel).read_text(errors="replace")):
            name = next(g for g in match.groups() if g)
            if rel not in found.setdefault(name, []):
                found[name].append(rel)
    return found


def defined_tests(root: Path = REPO_ROOT) -> dict[str, str]:
    return {name: locations[-1] for name, locations in defined_test_locations(root).items()}


def _is_test_file(rel: str) -> bool:
    """Where tests live: Python `tests/` folders and `test_*.py`; `*.test.ts(x)` and `test/` folders; Rust anywhere
    (a Rust test is told by its `#[test]` attribute, so `src/` modules count)."""
    path = Path(rel)
    if path.suffix == ".rs":
        return True
    parts = set(path.parts[:-1])
    if path.suffix == ".py":
        return "tests" in parts or path.name.startswith("test_")
    return ".test." in path.name or "test" in parts or "tests" in parts


def all_acceptance_tests(docs: Path = DOCS) -> dict[str, str]:
    """Every acceptance-test name the specification names, with its requirement."""
    return {name: rid for rid in requirements(docs) for name in acceptance_tests(rid, docs)}


def misnamed_test_errors(root: Path = REPO_ROOT, docs: Path = DOCS) -> list[str]:
    """Plan Rule 6b: a test whose name starts with a requirement prefix (`abc12_`) is a specification acceptance test,
    so it must carry one of the names the specification gives. A supplementary test is named `test_<req>_<what>`."""
    named = all_acceptance_tests(docs)
    errors = []
    for rel in _sources(root):
        if not _is_test_file(rel):
            continue
        text = (root / rel).read_text(errors="replace")
        for match in _ANY_TEST.finditer(text):
            name = next(g for g in match.groups() if g)
            if _PREFIX.match(name) and name not in named:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{rel}:{line}: {name} is named like an acceptance test but the specification names no "
                              "such test; use the spec's name or test_<req>_<what> (plan Rule 6b)")  # fmt: skip
    return errors


_RANK = {"fail": 3, "skipped": 2, "pass": 1}


def merge(*sets: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for results in sets:
        for name, outcome in results.items():
            if _RANK[outcome] > _RANK.get(merged.get(name, ""), 0):
                merged[name] = outcome
    return merged


def cargo_results(path: Path) -> dict[str, str]:
    """`test module::name ... ok|FAILED|ignored` lines from `cargo test`."""
    results: dict[str, str] = {}
    for line in path.read_text().splitlines():
        found = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if found:
            name = found.group(1).rsplit("::", 1)[-1]
            results[name] = {"ok": "pass", "FAILED": "fail", "ignored": "skipped"}[found.group(2)]
    return results


def junit_results(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    # The JUnit file is written by our own test run in the same job, not external input.
    for case in ET.parse(path).getroot().iter("testcase"):  # noqa: S314
        # pytest names the function; Vitest names "describe > test (detail)": the test id is the first word of the last.
        name = case.get("name", "").split(" > ")[-1].split("[")[0].split(" ")[0].removesuffix(":")
        outcome = "pass"
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "fail"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        # A parametrised test (one case per journey failure branch, say) is as good as its worst case.
        if _RANK[outcome] > _RANK.get(results.get(name, ""), 0):
            results[name] = outcome
    return results


def coverage(milestone: str, junit: Path | list[Path] | None = None, docs: Path = DOCS, root: Path = REPO_ROOT,
             cargo: list[Path] | None = None) -> list[Row]:  # fmt: skip
    defined = defined_tests(root)
    files = [junit] if isinstance(junit, Path) else (junit or [])
    results = merge(*(junit_results(f) for f in files), *(cargo_results(f) for f in cargo or []))
    rows = []
    for wp, rid in primary_requirements(milestone, docs):
        tests = {
            name: (results.get(name, "not run") if name in defined else "missing")
            for name in acceptance_tests(rid, docs)
        }
        rows.append(Row(rid, requirements(docs)[rid].priority, wp, tests))
    return rows


def render(milestone: str, rows: list[Row]) -> str:
    lines = [f"Acceptance-test coverage for {milestone}", "", "| Work package | Requirement | Priority | Tests |",
             "| --- | --- | --- | --- |"]  # fmt: skip
    for row in rows:
        tests = "<br>".join(f"`{n}` → {r}" for n, r in row.tests.items())
        lines.append(f"| {row.work_package} | {row.requirement} | {row.priority} | {tests} |")
    counts: dict[str, int] = {}
    for row in rows:
        for result in row.tests.values():
            counts[result] = counts.get(result, 0) + 1
    total = sum(counts.values())
    lines += ["", f"{len(rows)} requirements, {total} named tests: "
              + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))]  # fmt: skip
    return "\n".join(lines) + "\n"
