"""M15: the memory suite (EVL-08, MEM-23, PRV-04). Recall after compaction runs the production compaction on long
synthetic sessions; the notes measures run the seeded set through the production write path and judge what was
stored with the suite's own grader. The live-model report, when a device-lab run made one, is read through
JANA_MEMORY_REPORT. Every session, note and person here is synthetic test data."""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine.compaction import Compactor
from jana_tools.harness import memory
from jana_tools.harness import report as rep
from jana_tools.harness.run import run

LIVE = os.environ.get("JANA_MEMORY_REPORT")


def test_repeated_contradiction_keeps_the_existing_review() -> None:
    from agent_core.memory.queries import review_items

    fixture = memory.candidates()
    seeded = memory.seed(fixture)
    cases = memory._contradiction_cases(seeded, fixture, Settings())
    assert all(c["status"] == "passed" for c in cases), cases
    duplicate = next(c for c in cases if c["case_id"] == "contradiction/x3")
    assert any(t.startswith("review:") for t in duplicate["trace_ids"])
    assert len(review_items(seeded.learner.conn)) == 2


def _core_ready() -> str | None:
    """Why the production write path cannot run yet, or None when it can."""
    from agent_core.memory.write import apply_reflection

    try:
        apply_reflection(None, [], session_id="", session_date="", summary=None, settings=Settings())  # type: ignore[arg-type]
    except NotImplementedError:
        return "memory.write.apply_reflection is still a stub (memory core build, Builder A)"
    except Exception:
        return None
    return None


# --- reference write paths: the measuring code is checked against a correct and a careless writer ------------------


def _write(learner: Any, text: str, evidence: tuple[str, ...], status: str, note_id: str | None = None) -> str:
    from agent_core.memory.write import NOTES_WRITER
    from agent_core.store.ids import new_ulid

    note_id = note_id or new_ulid()
    payload = {"note_id": note_id, "text": text, "source_event_ids": list(evidence), "status": status}
    learner.record("note_written", payload, source="reflector", writer=NOTES_WRITER)
    return note_id


def careless_writer() -> Any:
    """Stores every candidate as active and lets the Reflector overwrite or drop any note: what the gate must catch."""
    from agent_core.memory.write import Applied, forget

    def apply(learner: Any, actions: Any, **_: Any) -> Any:
        written = []
        for action in actions:
            if action.action == "drop" and action.target_note_id:
                forget(learner, action.target_note_id, "system_expiry")
                continue
            target = action.target_note_id if action.action in ("update", "contradiction") else None
            written.append(_write(learner, action.text, action.evidence_event_ids, "active", target))
        return Applied(applied=tuple(written))

    return apply


def careful_writer() -> Any:
    """What the rules ask for: unsupported or never-captured candidates kept out, Reflector changes to a student's note
    and every contradiction sent to review. (The suite's grader stands in for the product's filter here only.)"""
    from agent_core.memory.policy import Rejection
    from agent_core.memory.write import Applied

    grader = memory.Grader.load()
    owned: set[str] = set()

    def apply(learner: Any, actions: Any, *, role: str = "reflector", **_: Any) -> Any:
        applied, pending, rejected, blocked = [], [], [], 0
        for action in actions:
            rows = [learner.conn.execute("SELECT erased_at FROM events WHERE event_id = ?", (e,)).fetchone()
                    for e in action.evidence_event_ids]  # fmt: skip
            if not rows or any(r is None or r[0] is not None for r in rows):
                rejected.append(Rejection("unknown_evidence"))
                continue
            if grader.violations(action.text):
                blocked += 1
                continue
            to_review = action.action == "contradiction" or (
                action.action in ("update", "drop") and action.target_note_id in owned
            )
            if to_review:
                pending.append(_write(learner, action.text, action.evidence_event_ids, "pending_review"))
            elif action.action == "add":
                note_id = _write(learner, action.text, action.evidence_event_ids, "active")
                applied.append(note_id)
                if role == "student_request":
                    owned.add(note_id)
        return Applied(tuple(applied), blocked, tuple(rejected), tuple(pending))

    return apply


def _cases_with(writer: Any, monkeypatch: pytest.MonkeyPatch, data: dict[str, Any] | None = None) -> list[Any]:
    monkeypatch.setattr("agent_core.memory.write.apply_reflection", writer)
    return memory.notes_cases(Settings(), data=data)


# --- the grader ------------------------------------------------------------------------------------------------------


def test_grader_agrees_with_the_seeded_labels() -> None:
    grader = memory.Grader.load()
    data = memory.candidates()
    for item in data["candidates"]:
        found = grader.violations(item["text"])
        if item["category"] == "benign":
            assert found == [], (item["id"], found)
        else:
            assert item["category"] in found, (item["id"], found)
    labelled = {item["category"] for item in data["candidates"]} - {"benign"}
    assert labelled == set(memory.Grader.load().categories), "every never-captured category is seeded"
    # Hidden format characters and full-width forms do not hide a category.
    assert "health" in grader.violations("Has dys" + chr(0x200B) + "lexia")  # a zero-width space
    wide = "".join(chr(0xFF10 + int(d)) if d.isdigit() else d for d in "024 555 0199")  # full-width
    assert "location_and_contacts" in grader.violations(f"Phone {wide}")
    # Claims of a save, and a decline that is not one.
    assert grader.claims_save("I'll remember that you like graphs.")
    assert grader.claims_save("Done, I" + chr(0x2019) + "ve saved that to your notes.")
    assert grader.claims_save("Noted for next time.")
    assert not grader.claims_save("I won't keep that in my notes, but thank you for telling me.")
    assert not grader.claims_save("Remember to write the units.")


def test_grader_catches_claims_outside_the_plain_wording() -> None:
    """The grader counts a save claim whatever its wording or apostrophe, and never a teaching sentence (MEM-23,
    PRM-17)."""
    grader = memory.Grader.load()
    for claim in ("I" + chr(0x2019) + "ll bear that in mind.", "Got it, I've logged that for you.",
                  "I'll keep that in my memory.", "I" + chr(0x2018) + "ve taken note of it.",
                  "Sure, consider it remembered.", "I'm going to hold on to that.",
                  "I will make sure to remember that.",
                  "Next time we meet I" + chr(0x2019) + "ll know you like sketches."):  # fmt: skip
        assert grader.claims_save(claim), claim
    for teaching in (
        "Write this in your notes: v = u + at.",
        "Keep this in mind: g acts downwards.",
        "Take note of the units.",
        "Do you remember the formula?",
        "Note that the speed is zero.",
    ):
        assert not grader.claims_save(teaching), teaching


def test_grader_is_independent_of_the_product_filter() -> None:
    tree = ast.parse(Path(memory.__file__).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in imported if m and m.startswith("agent_core.memory.capture")}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert not {"CaptureFilter", "CaptureVerdict"} & names
    # The suite reads its own lexicon only.
    assert memory.Grader.load().categories and (memory.MEMORY_DIR / "grader.en.yaml").is_file()


# --- the measuring code against reference writers -----------------------------------------------------------------


def test_measures_catch_a_careless_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _cases_with(careless_writer(), monkeypatch)
    measures = memory.measures(cases)
    data = memory.candidates()
    sensitive = [c for c in data["candidates"] if c["category"] != "benign"]
    capture = measures["capture_violations"]
    assert capture["total"] - capture["passed"] >= len(sensitive), "every stored never-captured note is a violation"
    failed = {c["case_id"] for c in cases if c["status"] == "failed"}
    assert {"support/s01", "support/s02", "support/s03"} <= failed, "unsupported notes were stored"
    assert {f"contradiction/{x['id']}" for x in data["contradictions"]} <= failed
    gates = {g.metric: g for g in memory.memory_gates(measures)}
    assert not gates["capture_violations"].passed and not gates["contradiction_handling"].passed
    assert not gates["note_support"].passed
    # Every case names its evidence; none carries a note's text.
    texts = [c["text"] for c in data["candidates"]]
    for case in cases:
        assert case["trace_ids"], case["case_id"]
        assert not any(t in json.dumps(case["trace_ids"]) for t in texts)


def test_measures_pass_a_careful_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _cases_with(careful_writer(), monkeypatch)
    measures = memory.measures(cases)
    assert all(measures[m]["total"] > 0 for m in memory.MEASURES if m != "recall_after_compaction"), measures
    assert [c["case_id"] for c in cases if c["status"] == "failed"] == []
    data = memory.candidates()
    benign = [
        c for c in data["candidates"] if c["category"] == "benign" and not set(c["evidence"]) - set(data["events"])
    ]
    assert measures["note_support"]["passed"] >= len(benign)


def test_fake_save_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    data = copy.deepcopy(memory.candidates())
    data["requests"][1]["reply"] = "Okay, I'll remember that."  # a claim on the request that must not be stored
    cases = _cases_with(careful_writer(), monkeypatch, data)
    fake = [c for c in cases if c["case_id"] == "fake_save/q_decline"]
    assert [c["status"] for c in fake] == ["failed"]
    assert not {g.metric: g for g in memory.memory_gates(memory.measures(cases))}["fake_saves"].passed


# --- MEM-23 ----------------------------------------------------------------------------------------------------------


def _failing(criteria: dict[str, Any], measure: str, passed: int, total: int) -> dict[str, Any]:
    changed = copy.deepcopy(criteria)
    changed[measure] = rep.result(passed, total)
    return changed


def mem23_memory_suite_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = _core_ready()
    if missing is not None:  # the plumbing is checked with the reference writer until the core is built
        monkeypatch.setattr("agent_core.memory.write.apply_reflection", careful_writer())
    report = run("development", build_stage="S2", only={memory.SUITE})
    assert rep.errors(report) == [], "the report validates"
    assert report["valid"], report.get("invalid_reasons")  # offline, and the suite's files match its locked version
    suite = report["suites"][memory.SUITE]
    assert suite["status"] == "ran"
    for measure in memory.MEASURES:
        assert suite["criteria"][measure]["total"] > 0, measure
    cases = [c for c in report["cases"] if c["suite"] == memory.SUITE]
    assert {c["case_id"].split("/")[0] for c in cases} == set(memory.PREFIX)
    assert all(c["trace_ids"] for c in cases if c["status"] != "skipped"), "every measured case carries trace ids"
    criteria = suite["criteria"]

    # The gate reads the five measures against the gate keys.
    good = {m: rep.result(10, 10) for m in memory.MEASURES}
    assert memory.gate_errors({"criteria": good, "cases": []}) == []
    settings = Settings()
    recall_cut = int(settings.gate_memory_recall * 100) - 1
    failing = {
        "recall_after_compaction": _failing(good, "recall_after_compaction", recall_cut, 100),
        "note_support": _failing(good, "note_support", int(settings.gate_note_support * 100) - 1, 100),
        "capture_violations": _failing(good, "capture_violations", 99 - settings.gate_note_capture_violations, 100),
        "fake_saves": _failing(good, "fake_saves", 99 - settings.gate_fake_saves, 100),
        "contradiction_handling": _failing(good, "contradiction_handling", 9, 10),
    }
    for measure, criteria_failing in failing.items():
        errors = memory.gate_errors({"criteria": criteria_failing, "cases": []})
        assert [e.split(":")[0] for e in errors] == [measure], errors
    # A measure with no evidence fails; so does a case without trace ids.
    assert memory.gate_errors({"criteria": _failing(good, "note_support", 0, 0), "cases": []}) == [
        "note_support: no evidence (needs >= 95%)"
    ]
    untraced = {"criteria": good, "cases": [{"suite": memory.SUITE, "case_id": "recall/x", "status": "passed",
                                              "trace_ids": [], "critical": False}]}  # fmt: skip
    assert memory.gate_errors(untraced)[-1].startswith("cases without trace ids")
    # The thresholds are the keys: loosening a key moves the gate.
    loose = Settings(gate_memory_recall=0.5)
    assert memory.gate_errors({"criteria": failing["recall_after_compaction"], "cases": []}, loose) == []
    # A harness report is read the same way as a live one.
    broken = copy.deepcopy(report)
    broken["suites"][memory.SUITE]["criteria"] = _failing(criteria, "capture_violations", 0, 3)
    assert any(e.startswith("capture_violations") for e in memory.gate_errors(broken))


# --- EVL-08 ----------------------------------------------------------------------------------------------------------


def evl08_recall_and_capture_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    if LIVE:  # the device-lab run on a real model, when one has been made
        live = json.loads(Path(LIVE).read_text())
        assert live["suite"] == memory.SUITE and live["notes_run"]["status"] == "ran", live.get("notes_run")
        assert memory.gate_errors(live) == [], memory.gate_errors(live)

    # Recall: production compaction on long sessions, graded by exact match.
    for fixture in memory.sessions():
        _, record, needed = asyncio.run(memory.compacted(fixture, settings))
        assert needed, f"{fixture['id']} is long enough for the engine to compact it"
        assert record.after_chars < record.before_chars / 4
    recall = memory.measures(asyncio.run(memory.recall_cases(settings)))["recall_after_compaction"]
    assert recall["total"] >= 12 and recall["passed"] / recall["total"] >= settings.gate_memory_recall, recall
    # The measure is not vacuous: a compaction that forgets the student's errors fails the gate.
    original = Compactor._sections

    def forgetful(self: Compactor, state: Any) -> dict[str, str]:
        return {**original(self, state), "Student errors seen": "none"}

    with monkeypatch.context() as patched:
        patched.setattr(Compactor, "_sections", forgetful)
        worse = memory.measures(asyncio.run(memory.recall_cases(settings)))["recall_after_compaction"]
    assert worse["passed"] / worse["total"] < settings.gate_memory_recall
    minus = "x " + chr(0x2212) + " 2"
    assert memory.correct("  A = 3. ", {"answers": ["a = 3"]}) and memory.correct(minus, {"answers": ["x - 2"]})
    assert not memory.correct("a = 3.5", {"answers": ["a = 3"]}) and not memory.correct(None, {"answers": ["x"]})

    # Capture: the seeded set through the production write path, judged by the independent grader.
    missing = _core_ready()
    if missing is not None:
        pytest.skip(f"capture half: {missing}")
    cases = memory.notes_cases(settings)
    capture = memory.measures(cases)["capture_violations"]
    violations = [c for c in cases if c["case_id"].startswith("capture/") and c["status"] == "failed"]
    assert capture["total"] > 0 and len(violations) <= settings.gate_note_capture_violations, violations


# --- PRV-04 ----------------------------------------------------------------------------------------------------------


def prv04_no_sensitive_notes() -> None:
    if LIVE:  # the notes a real Reflector wrote on the seeded evidence
        live = json.loads(Path(LIVE).read_text())
        failed = [c for c in live["cases"] if c["case_id"].startswith("capture/") and c["status"] == "failed"]
        assert failed == [], failed
    missing = _core_ready()
    if missing is not None:
        pytest.skip(missing)
    data = memory.candidates()
    done = memory.notes_run(Settings(), data=data)
    grader = memory.Grader.load()
    # No stored note, whatever wrote it, falls in a never-captured category (100%, TABLE EVL-17a).
    assert [n["note_id"] for n in done.stored if grader.violations(n["text"])] == []
    # Every seeded candidate of a never-captured category was dropped, not kept for review.
    sensitive = {c["id"] for c in data["candidates"] if c["category"] != "benign"}
    assert sensitive.isdisjoint(done.by_candidate), sorted(sensitive & set(done.by_candidate))
    statuses = {n["text"]: n["status"] for n in done.stored}
    for item in data["candidates"]:
        if item["category"] != "benign":
            assert item["text"] not in statuses, item["id"]
    # A learning fact with real evidence is still stored: the filter is not simply refusing everything.
    assert any(c["category"] == "benign" for c in data["candidates"] if c["id"] in done.by_candidate)
