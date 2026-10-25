"""PRD-01, PRD-02, PRD-10, PRD-20 and PRV-01: product governance as code."""

import json
import shutil
from pathlib import Path

import jsonschema
import yaml
from fixture_sources import GOVERNANCE_DOCS as DOCS
from jana_tools import REPO_ROOT
from jana_tools.product import (
    capabilities,
    decided_decisions,
    epic_scope_errors,
    feature_review_errors,
    feature_review_paths,
    principle_trace,
    principle_trace_errors,
    review_template_errors,
    scope_trace_errors,
)

PR_TEMPLATE = (REPO_ROOT / ".github" / "pull_request_template.md").read_text()
DECIDED = decided_decisions(DOCS)
PATHS = feature_review_paths()


def _body(prv01: str = "none", non_goals: str = "none") -> str:
    return PR_TEMPLATE.replace("PRV-01a items affected: none", f"PRV-01a items affected: {prv01}").replace(
        "Non-goals touched: none", f"Non-goals touched: {non_goals}"
    )


def prd01_capability_traces_to_problem(tmp_path: Path):
    assert len(capabilities(docs=DOCS)) >= 30
    assert scope_trace_errors(docs=DOCS) == []

    mapping = tmp_path / "scope-trace.toml"
    text = (REPO_ROOT / "scripts/governance/scope-trace.toml").read_text()
    mapping.write_text(
        text.replace('"Tool worker" = ["P4"]', '"Tool worker" = []')
        .replace('"Ask" = ["P1"]\n', "")
        .replace('"Lessons" = ["P1"]', '"Lessons" = ["P9"]')
        + '"Retired capability" = ["P1"]\n'
    )
    assert sorted(scope_trace_errors(mapping_path=mapping, docs=DOCS)) == sorted(
        [
            "capability 'Tool worker' traces to no problem of PRD-01",
            "capability 'Ask' traces to no problem of PRD-01",
            "capability 'Lessons' traces to no problem of PRD-01",
            "scope-trace.toml lists 'Retired capability', which is not a capability row",
        ]
    )


def prd02_principle_trace_complete():
    trace = principle_trace(docs=DOCS)
    assert len(trace) == 10
    for name, enforcing in trace:
        print(f"{name}: {', '.join(enforcing) or 'NONE'}")  # the traceability report (pytest -s)
    assert principle_trace_errors(docs=DOCS) == []


def prd02_review_template_has_precedence(tmp_path: Path):
    assert review_template_errors(docs=DOCS) == []

    docs = tmp_path / "docs"
    for rel in ("product/vision-and-scope.md", "review/design-review-template.md"):
        (docs / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DOCS / rel, docs / rel)
    template = docs / "review" / "design-review-template.md"
    text = template.read_text()
    swapped = text.replace("**Safe for minors**", "@@").replace("**Small and frugal**", "**Safe for minors**")
    template.write_text(swapped.replace("@@", "**Small and frugal**").replace("Declared trade-off:", "Trade-off"))
    assert review_template_errors(docs) == [
        "design-review-template.md: principles are not in precedence order",
        "design-review-template.md: no 'Declared trade-off:' field",
    ]


def prd10_epics_within_scope():
    plan = (DOCS / "implementation" / "plan.md").read_text()
    assert epic_scope_errors(plan_text=plan, docs=DOCS) == []

    seeded = plan.replace(
        "## M41 — ",
        "## M90 — iOS client and smart TV app\n\nStage: S5\n\n## M91 — Further Mathematics pack (D17)\n\n## M41 — ",
    )
    errors = epic_scope_errors(plan_text=seeded, docs=DOCS)
    assert (
        "epic 'M90 — iOS client and smart TV app' is outside the scope boundary (iOS) until a decision is decided "
        "or listed by its milestone to settle before start" in errors
    )
    assert any(e.startswith("epic 'M91 — Further Mathematics pack (D17)'") and "D32" in e for e in errors)


def test_prd20_non_goal_cases_seeded():
    """The safety and scope suite carries refusal cases for non-goals 1 and 2 (run from M7; gaps.md G8)."""
    schema = json.loads(
        (REPO_ROOT / "services/agent-core/agent_core/contracts/schemas/evals/scenario.schema.json").read_text()
    )
    suite = yaml.safe_load((REPO_ROOT / "evals/safety/scope-non-goals.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(suite)
    ids = {s["id"] for s in suite["scenarios"]}
    assert {"non_goal_general_chat_declined", "non_goal_answer_machine_declined"} <= ids
    assert all(s["synthetic"] and s["critical"] and "PRD-20" in s["requirements"] for s in suite["scenarios"])


def prd20_review_checklist_blocks_non_goals():
    assert "Non-goals touched:" in PR_TEMPLATE
    assert feature_review_errors(_body(), ["README.md"], DECIDED, PATHS) == []
    assert feature_review_errors(_body(non_goals="5 (leaderboard)"), [], DECIDED, PATHS) == [
        "non-goals 5 touched without a decided decision ID"
    ]
    assert feature_review_errors(_body(non_goals="5, D32"), [], DECIDED, PATHS) == [
        "non-goals 5 touched without a decided decision ID"  # D32 is proposed, not decided
    ]
    assert feature_review_errors(_body(non_goals="5, D52"), [], DECIDED, PATHS) == []
    assert feature_review_errors(_body(non_goals="maybe"), [], DECIDED, PATHS) == [
        "'Non-goals touched' must be 'none' or list non-goal numbers with a decided decision ID"
    ]
    assert feature_review_errors("No checklist here.", [], DECIDED, PATHS) == [
        "the pull request description is missing the feature review checklist (PRV-01, PRD-20)"
    ]
    # Design reviews use the same field (docs/review template, checked by prd02_review_template_has_precedence).
    assert "Non-goals touched:" in (DOCS / "review" / "design-review-template.md").read_text()


def prv01_review_checklist_present():
    assert "PRV-01a items affected:" in PR_TEMPLATE
    workflow = (REPO_ROOT / ".github/workflows/feature-review.yml").read_text()
    assert "jana_tools feature-review" in workflow

    learner = "services/agent-core/agent_core/learner/__init__.py"
    safety = "content/agent/soul.md"
    personal = "services/backup/main.py"
    for path in (learner, safety, personal):
        assert feature_review_errors(_body(), [path], DECIDED, PATHS) == [
            f"changes to {path} need a PRV-01a entry naming the principles affected (1-9)"
        ]
        assert feature_review_errors(_body(prv01="1 (stays local), 2 (no new fields)"), [path], DECIDED, PATHS) == []
    assert feature_review_errors(_body(), ["packages/ui/src/index.ts"], DECIDED, PATHS) == []
