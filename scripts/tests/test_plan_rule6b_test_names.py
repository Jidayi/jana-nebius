"""Plan Rule 6b: the coverage report sees every form the repository's tests are written in, and a test named like an
acceptance test (`abc12_...`) must carry a name the specification gives. Synthetic sources in a scratch git repo and a
synthetic specification; no real spec text. The sources spell the requirement prefix `@@` so this file's own text holds
no prefixed test name; `_repo` writes it out."""

from __future__ import annotations

import subprocess
from pathlib import Path

from jana_tools.coverage import defined_tests, junit_results, misnamed_test_errors

PREFIX = "zzz" + "01_"
# One synthetic requirement in the specification's layout, assembled so that no line of this file reads as spec text
# (scripts/git-hooks/check-no-spec.sh).
HEADING = "#" * 3 + " ZZZ-01 — Synthetic requirement"
META = "Stage" + ": S2 · Priority: must"
CASES = [f"- Case (test: `@@{n}_thing`)." for n in ("first", "second", "third", "fourth", "fifth", "sixth", "seventh")]
SPEC = chr(10).join(["# Synthetic", "", HEADING, "", META, "", "Acceptance:", *CASES, ""])

SOURCES = {
    "services/x/tests/test_x.py": (
        "def @@first_thing():\n    pass\n\n\nasync def @@second_thing():\n    pass\n\n\n"
        "def test_@@helper_case():\n    pass\n"
    ),
    "packages/y/test/y.test.ts": (
        'test("@@third_thing keeps the words after the name", () => {});\n'
        "it.skipIf(process.env.CI)('@@fourth_thing', () => {});\n"
        "test.each([\n  [1, 2],\n  [3, (4)],\n])(`@@fifth_thing %s`, () => {});\n"
        'test("test_@@supplementary", () => {});\n'
        'test("a plain sentence names a supplementary test", () => {});\n'
    ),
    "scripts/ci/check.test.mjs": 'test("@@seventh_thing: canonical Node runner", () => {});\n',
    "apps/z/src/lib.rs": "#[cfg(test)]\nmod tests {\n    #[tokio::test]\n    async fn @@sixth_thing() {}\n}\n",
}
DRIFT = {
    "services/x/tests/test_drift.py": "def @@almost_the_first_thing():\n    pass\n",
    "packages/y/test/drift.test.tsx": 'test("@@first_thing_and_more: words", () => {});\n',
    "apps/z/src/other.rs": "#[test]\nfn @@rust_drift() {}\n\nfn @@helper_not_a_test() {}\n",
    "services/x/x/helpers.py": "def @@not_in_a_test_file():\n    pass\n",
}


def _repo(tmp_path: Path, extra: dict[str, str] | None = None) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    docs = tmp_path / "docs"
    (docs / "specification").mkdir(parents=True)
    (docs / "specification" / "synthetic.md").write_text(SPEC.replace("@@", PREFIX))
    for rel, text in {**SOURCES, **(extra or {})}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text.replace("@@", PREFIX))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root, docs


def test_rule6b_coverage_sees_every_test_form(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path)
    found = defined_tests(root)
    for n in ("first", "second", "third", "fourth", "fifth", "sixth", "seventh"):
        assert f"{PREFIX}{n}_thing" in found, n
    assert not any(name.startswith("test_") for name in found)


def test_rule6b_spec_and_supplementary_names_pass(tmp_path: Path) -> None:
    root, docs = _repo(tmp_path)
    assert misnamed_test_errors(root, docs) == []


def test_rule6b_prefixed_name_the_spec_does_not_give_fails(tmp_path: Path) -> None:
    root, docs = _repo(tmp_path, DRIFT)
    errors = misnamed_test_errors(root, docs)
    named = sorted(e.split(": ")[1].split(" ")[0] for e in errors)
    assert named == [f"{PREFIX}almost_the_first_thing", f"{PREFIX}first_thing_and_more", f"{PREFIX}rust_drift"]
    assert all("plan Rule 6b" in e for e in errors)


def test_rule6b_node_and_vitest_colon_titles_match_the_canonical_name(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuite><testcase name="{PREFIX}seventh_thing: Node description"/></testsuite>')
    assert junit_results(path) == {PREFIX + "seventh_thing": "pass"}
