"""ARC-17: one pipeline; a release fails if any required stage was skipped."""

import copy

from jana_tools import REPO_ROOT
from jana_tools.stages import REQUIRED_STAGES, load_workflow, needs_errors, workflow_errors

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def arc17_release_requires_all_stages():
    workflow = load_workflow(WORKFLOW)
    assert workflow_errors(workflow) == []

    # The gate job refuses a run in which any stage was skipped, cancelled, failed or absent.
    passed = {stage: {"result": "success"} for stage in REQUIRED_STAGES}
    assert needs_errors(passed) == []
    for result in ("skipped", "cancelled", "failure"):
        run = copy.deepcopy(passed)
        run["offline"]["result"] = result
        assert needs_errors(run) == [f"required stage offline did not succeed: {result}"]
    run = copy.deepcopy(passed)
    del run["security-scans"]
    assert needs_errors(run) == ["required stage security-scans did not succeed: missing"]

    # The workflow cannot be edited to skip, reorder or soften a stage without failing the check.
    skipped = copy.deepcopy(workflow)
    skipped["jobs"]["offline"]["if"] = "github.event_name == 'push'"
    assert workflow_errors(skipped) == ["required stage offline has a condition that can skip it"]
    removed = copy.deepcopy(workflow)
    del removed["jobs"]["codegen-check"]
    assert "required stage codegen-check is not defined" in workflow_errors(removed)
    soft = copy.deepcopy(workflow)
    soft["jobs"]["security-scans"]["steps"][-1]["continue-on-error"] = True
    assert workflow_errors(soft) == ["required stage security-scans has a step that may fail silently"]
    ungated = copy.deepcopy(workflow)
    ungated["jobs"]["stages-complete"]["needs"].remove("gallery")
    del ungated["jobs"]["stages-complete"]["if"]
    assert workflow_errors(ungated) == [
        "gate job stages-complete does not need: gallery",
        "gate job stages-complete must run with if: always() so a skipped stage fails it",
    ]
    unguarded = copy.deepcopy(workflow)
    unguarded["jobs"]["release"]["needs"] = "offline"
    assert workflow_errors(unguarded) == ["release job release must need stages-complete"]
