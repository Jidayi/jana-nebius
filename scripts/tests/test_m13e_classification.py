"""EVL-13: top-1 topic classification, retrieval proposing and the Diagnoser choosing (M13.e).

The gate reads a classification report from a real local model run (`eval classify`, nightly), or runs one when a
labelled question set and a local model are both at hand. The set is evaluation data and lives outside the
repository: JANA_CLASSIFICATION_SET names it, JANA_CLASSIFICATION_REPORT a report already written, JANA_MODEL_URL and
JANA_MODEL the model (default http://127.0.0.1:8089, gemma-4-12b). The other tests here need no model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.retrieval.classify import Case, TopicCandidate, diagnoser_task, summary, topic_candidates, topic_of
from jana_tools import REPO_ROOT
from jana_tools.harness.classification import content_index, gate_errors, load_set

REPORT = os.environ.get("JANA_CLASSIFICATION_REPORT")
QUESTIONS = os.environ.get("JANA_CLASSIFICATION_SET")
MODEL_URL = os.environ.get("JANA_MODEL_URL", "http://127.0.0.1:8089")
MODEL = os.environ.get("JANA_MODEL", "gemma-4-12b")


def _model_up() -> bool:
    import httpx

    try:
        reply = httpx.get(f"{MODEL_URL}/v1/models", timeout=3)
    except httpx.HTTPError:
        return False
    return reply.status_code == 200 and any(m.get("id") == MODEL for m in reply.json().get("data", []))


def _outside_repository(path: Path) -> bool:
    return not path.resolve().is_relative_to(REPO_ROOT.resolve())


def evl13_topic_top1_gate(tmp_path: Path) -> None:
    if REPORT:
        report: dict[str, Any] = json.loads(Path(REPORT).read_text())
    elif QUESTIONS and _model_up():
        from jana_tools.harness.classification import run_live

        questions = Path(QUESTIONS)
        assert _outside_repository(questions), "the classification set is evaluation data: keep it out of the repo"
        report = run_live(MODEL_URL, os.environ.get("JANA_MODEL_KEY", "none"), MODEL, questions, tmp_path)
    else:
        missing = [] if QUESTIONS else ["the labelled question set (JANA_CLASSIFICATION_SET)"]
        missing += [] if _model_up() else [f"the local model {MODEL} at {MODEL_URL}"]
        pytest.skip("needs a classification report (JANA_CLASSIFICATION_REPORT) or a labelled question set kept "
                    f"outside the repository (JANA_CLASSIFICATION_SET) with a local model {MODEL} at {MODEL_URL}; "
                    f"missing here: {' and '.join(missing)}; run `python -m jana_tools eval classify` on the device "
                    "lab or nightly")  # fmt: skip
    assert report["suite"] == "classification" and report["total"] > 0
    assert report["top1"] >= Settings().gate_topic_top1, report.get("gate_errors")


# --- without a model ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def index() -> Any:
    return content_index()


def test_candidates_hold_the_topic_of_each_kc(index: Any) -> None:
    """Retrieval proposes the right topic for the words of each KC of the four packs (recall within the candidate
    list), within the session's subject as the app asks."""
    settings = Settings()
    kcs = list(index.kcs.values())
    found = 0
    for kc in kcs:
        subject = kc.id.split(".")[1]
        candidates = topic_candidates(index, kc.statement, settings, subjects={subject})
        assert len(candidates) <= settings.classify_topic_candidates
        assert all(c.topic_id.split(".")[1] == subject for c in candidates)
        found += kc.topic_id in [c.topic_id for c in candidates]
    assert found / len(kcs) >= 0.95, f"{found}/{len(kcs)}"


def test_diagnoser_task_and_choice() -> None:
    candidates = [
        TopicCandidate(1, "cur.acc.o.costing", "Costs", "accounting", ((1, "kc.acc.o.costing.a", "Break even"),)),
        TopicCandidate(2, "cur.acc.o.ratios", "Ratios", "accounting", ((2, "kc.acc.o.ratios.b", "Current ratio"),)),
    ]
    task = diagnoser_task("Is <b>rent</b> fixed?", candidates)
    assert "<student-message>\nIs &lt;b&gt;rent&lt;/b&gt; fixed?\n</student-message>" in task
    assert "1. Costs (accounting)" in task and "2. Current ratio (topic 2)" in task
    assert topic_of({"topic_ref": 2, "kc_refs": []}, candidates) == "cur.acc.o.ratios"
    assert topic_of({"topic_ref": None, "kc_refs": [1]}, candidates) == "cur.acc.o.costing"
    assert topic_of({"topic_ref": 9, "kc_refs": [7]}, candidates) is None  # never a topic outside the list


def test_gate_and_set_checks(tmp_path: Path) -> None:
    number, calculus = "cur.mth.o.number", "cur.mth.o.calculus"
    cases = [Case("a", number, (number,), number), Case("b", calculus, (number, calculus), number)]
    report = summary(cases)
    assert report["top1"] == 0.5 and report["retrieval_recall"] == 1.0 and report["retrieval_top1"] == 0.5
    assert gate_errors(report) and not gate_errors({**report, "top1": Settings().gate_topic_top1})
    bad = tmp_path / "set.yaml"
    bad.write_text("- {id: a, subject: mathematics, topic: cur.mth.o.number}\n")
    with pytest.raises(ValueError, match="needs id, subject, topic, text"):
        load_set(bad)
    assert not _outside_repository(REPO_ROOT / "evals" / "anything.yaml") and _outside_repository(tmp_path)
