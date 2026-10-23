"""G113 (M13): misconception signatures reach every marking caller from the verified packs' records (CUR-18), a match
appends the ASM-13 `misconception_evidence` event, the `pack.ref` chart of accounts decides `wrong_account_class`
(CUR-07; the chart table is the proposed contract addition, D72) and `sign_of_g_flipped` stays undecided (CUR-28).

Items come from the pack sources or are invented here; every answer and learner is synthetic test data."""

from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import document, validate
from agent_core.engine.learn import LearnDesk
from agent_core.engine.marking import mark
from agent_core.engine.signatures import (
    UNDECIDED_RULES,
    SignatureContext,
    evidence,
    pack_context,
    step_error_match,
    verdict_source,
)
from agent_core.store.pack_index import MisconceptionInfo, PackIndex
from engine_harness import checker_steps, close, make_engine, tutor
from jana_tools import REPO_ROOT
from jana_tools import marking_golden as golden
from memory_harness import PACK, SAFE, item, store
from pack_builder.build import charts_of, load_source

SETTINGS = Settings()
CORE = REPO_ROOT / "services" / "agent-core" / "agent_core"
STUDIO = REPO_ROOT / "services" / "pack-builder" / "pack_builder" / "studio.py"
ACC = REPO_ROOT / "content" / "curriculum" / "acc" / "o"
PAYLOAD = "learning/learning-event#/$defs/payload_misconception_evidence"
OWNER = "kc.acc.o.double_entry.record_owner_transactions"


LOOP = asyncio.new_event_loop()  # one loop for the engines and their worker processes


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def learned(held: Any, kind: str) -> list[dict[str, Any]]:
    rows = held.conn.execute("SELECT payload FROM events WHERE type = ? ORDER BY seq", (kind,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def status_of(held: Any, misconception_id: str) -> str | None:
    row = held.conn.execute("SELECT status FROM learner_misconceptions WHERE misconception_id = ?",
                            (misconception_id,)).fetchone()  # fmt: skip
    return row[0] if row else None


# --- every caller passes the library (CUR-18) ----------------------------------------------------------------------


def _mark_calls(path: Path) -> list[tuple[int, bool]]:
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if name in ("mark", "mark_structured"):
            out.append((node.lineno, any(k.arg == "signatures" for k in node.keywords)))
    return out


def test_every_app_marking_caller_passes_signatures() -> None:
    """Practice, lesson checks, the tutor's attempt marking and the studio's preview mark with the misconception
    library; a marking path added later (mock papers, M16) fails here until it does too."""
    files = [*sorted(CORE.rglob("*.py")), STUDIO]
    calls = {str(p.relative_to(REPO_ROOT)): _mark_calls(p) for p in files}
    calls = {path: found for path, found in calls.items() if found}
    assert {"services/agent-core/agent_core/engine/learn.py", "services/agent-core/agent_core/engine/slice.py",
            "services/pack-builder/pack_builder/studio.py"} <= set(calls)  # fmt: skip
    missing = [f"{path}:{line}" for path, found in calls.items() for line, passed in found if not passed]
    assert missing == [], f"mark() without signatures= at {missing}"


# --- the evidence event (ASM-13) -----------------------------------------------------------------------------------


def test_evidence_payload_follows_the_contract() -> None:
    library = [{"id": "mc.phy.o.ke_without_square", "kc_ids": ["kc.phy.o.energy.other", "kc.phy.o.energy.kinetic"],
                "signatures": []}]  # fmt: skip
    tagged = {"id": "itm.phy.o.energy.9001", "type": "numeric", "kc_ids": ["kc.phy.o.energy.kinetic"]}
    payload = evidence(tagged, "mc.phy.o.ke_without_square", library, "signature", "01J9ZZTESTATTEMPT000000000")
    assert payload == {
        "misconception_id": "mc.phy.o.ke_without_square",
        "kc_id": "kc.phy.o.energy.kinetic",
        "evidence_source": "signature",
        "weight": 1.0,
        "attempt_id": "01J9ZZTESTATTEMPT000000000",
    }
    validate(PAYLOAD, payload)
    # A distractor's misconception the library does not hold counts against the item's KC; no KC, no event.
    assert evidence(tagged, "mc.phy.o.unknown", [], "probe")["kc_id"] == "kc.phy.o.energy.kinetic"  # type: ignore[index]
    assert evidence({"id": "x", "kc_ids": []}, "mc.phy.o.unknown", [], "probe") is None
    assert verdict_source({"type": "mcq_diagnostic"}) == "probe" and verdict_source({"type": "mcq"}) == "signature"


def test_practice_probe_choice_records_evidence_and_activates(tmp_path: Path) -> None:
    """A distractor chosen on a diagnostic practice item is a probe: one evidence event, and the misconception is
    active at once (ASM-13, the learner projection)."""
    held = store()
    probe = item("itm.phy.o.motion.0320")
    engine, _ = run(make_engine(tmp_path, {"coach": [tutor(SAFE), tutor("Not quite yet. What does distance count?")]}))
    engine.deps.misconception_context = lambda record: pack_context(PACK, record)
    engine.learning = held.learner.record_batch
    try:
        run(engine.start_practice(probe))
        run(engine.student_turn("B"))
    finally:
        run(close(engine))
    [found] = learned(held, "misconception_evidence")
    [attempt] = learned(held, "attempt")
    assert found == {"misconception_id": "mc.phy.o.displacement_for_distance",
                     "kc_id": "kc.phy.o.motion.distance_or_displacement", "evidence_source": "probe", "weight": 1.0,
                     "attempt_id": attempt["attempt_id"]}  # fmt: skip
    assert status_of(held, "mc.phy.o.displacement_for_distance") == "active"
    assert engine.state.practice["misconception_id"] == "mc.phy.o.displacement_for_distance"


def test_practice_signature_match_records_evidence(tmp_path: Path) -> None:
    """A numeric answer matched by a structural signature of the pack's library (speed inverted) is one piece of
    signature evidence: suspected until a second match (ASM-13)."""
    held = store()
    coach = [tutor(SAFE), tutor("Not quite yet. Which quantity goes on top?"), tutor("Look again at the ratio.")]
    engine, _ = run(make_engine(tmp_path, {"coach": coach}))
    engine.deps.misconception_context = lambda record: pack_context(PACK, record)
    engine.learning = held.learner.record_batch
    try:
        run(engine.start_practice(item()))
        run(engine.student_turn("0.125"))
        first = status_of(held, "mc.phy.o.time_over_distance")
        run(engine.student_turn("0.125"))
    finally:
        run(close(engine))
    found = learned(held, "misconception_evidence")
    assert [f["evidence_source"] for f in found] == ["signature", "signature"]
    assert {f["misconception_id"] for f in found} == {"mc.phy.o.time_over_distance"}
    assert {f["kc_id"] for f in found} == {"kc.phy.o.motion.average_speed"}
    assert (first, status_of(held, "mc.phy.o.time_over_distance")) == ("suspected", "active")
    for payload in found:
        validate(PAYLOAD, payload)


def test_no_library_no_signature_evidence(tmp_path: Path) -> None:
    """Without the verified packs' library (no misconception context) a numeric answer matches nothing."""
    held = store()
    engine, _ = run(make_engine(tmp_path, {"coach": [tutor(SAFE), tutor("Not quite yet.")]}))
    engine.learning = held.learner.record_batch
    try:
        run(engine.start_practice(item()))
        run(engine.student_turn("0.125"))
    finally:
        run(close(engine))
    assert learned(held, "misconception_evidence") == [] and len(learned(held, "verdict")) == 1


def test_check_working_step_error_records_evidence(tmp_path: Path) -> None:
    """Check my working on a practice item: the first wrong step's category names the misconception whose
    `step_error` signature has it, recorded as `check_working` evidence for the Coach (CUR-18, ASM-13)."""
    dropped = item("itm.phy.o.motion.0004")
    library = [{"id": "mc.phy.o.fall_arithmetic_slip", "kc_ids": ["kc.phy.o.motion.free_fall"],
                "signatures": [{"kind": "step_error", "error_category": "arithmetic"}]}]  # fmt: skip
    held = store()
    coach = [tutor(SAFE), tutor("Look again at your second line. Check the multiplication there.")]
    engine, _ = run(make_engine(tmp_path, {"checker": checker_steps(), "coach": coach}))
    engine.deps.misconception_context = lambda record: SignatureContext(misconceptions=library)
    engine.learning = held.learner.record_batch
    statement = " ".join([dropped["stem"], dropped["parts"][0]["prompt"]]).strip()
    try:
        run(engine.start_practice(dropped))
        run(engine.check_working(statement, "s = 0.5*9.8*2.0^2\ns = 4.9*4.0\ns = 18.6"))
    finally:
        run(close(engine))
    student = [f["event"] for f in engine.events.frames
               if f["event"]["type"] == "board.step" and f["event"]["owner"] == "student"]  # fmt: skip
    assert "incorrect" in [e["status"] for e in student]
    [found] = learned(held, "misconception_evidence")
    assert found == {"misconception_id": "mc.phy.o.fall_arithmetic_slip", "kc_id": "kc.phy.o.motion.free_fall",
                     "evidence_source": "check_working", "weight": 1.0}  # fmt: skip
    assert engine.state.practice["misconception_id"] == "mc.phy.o.fall_arithmetic_slip"


def test_step_error_match_reads_only_step_signatures() -> None:
    library = [{"id": "mc.phy.o.a", "kc_ids": ["kc.phy.o.motion.free_fall"],
                "signatures": [{"kind": "structural", "rule": "ratio_inverted"}]},
               {"id": "mc.phy.o.b", "kc_ids": ["kc.phy.o.motion.free_fall"],
                "signatures": [{"kind": "step_error", "error_category": "sign"}]}]  # fmt: skip
    dropped = item("itm.phy.o.motion.0004")
    assert step_error_match(dropped, "a", SignatureContext(library, step_error="sign")) == "mc.phy.o.b"
    assert step_error_match(dropped, "a", SignatureContext(library, step_error="arithmetic")) is None
    assert step_error_match(dropped, "a", SignatureContext(library)) is None


def test_lesson_check_records_evidence() -> None:
    """A lesson's quick check that names a misconception records its evidence (no attempt), through the learner
    database the desk was opened on."""
    data = golden.load_signatures()
    # A quick check is marked only when it can be shown (CUR-11), and an Item has a stem (content-pack contract).
    seeded = {**data["items"]["ke_trolley"], "stem": "A trolley rolls along a level track."}
    lesson_id = "les.phy.o.energy.kinetic_energy"
    library = {m["id"]: m for m in data["misconceptions"]}
    content = PackIndex(records={"items": {seeded["id"]: seeded}, "misconceptions": library,
                                 "lessons": {lesson_id: {"blocks": [{"type": "quick_check",
                                                                     "item_ids": [seeded["id"]]}]}}})  # fmt: skip
    content.misconceptions = {m["id"]: MisconceptionInfo(m["id"], "A synthetic misconception", tuple(m["kc_ids"]))
                              for m in library.values()}  # fmt: skip
    written: list[Any] = []
    with sqlite3.connect(":memory:") as conn:
        desk = LearnDesk(content, conn, SETTINGS, run_tool=golden.run_tool, record=written.extend)
        answer = [{"part_id": "a", "kind": "numeric", "value": "3", "unit": "J"}]
        result = run(desk.check(lesson_id, seeded["id"], answer))
        right = run(desk.check(lesson_id, seeded["id"], [{**answer[0], "value": "9"}]))
    assert result is not None and right is not None and right["verdict"] == "correct"
    [event] = written
    assert (event.type, event.source) == ("misconception_evidence", "engine")
    assert event.payload == {"misconception_id": "mc.phy.o.ke_without_square", "kc_id": "kc.phy.o.energy.kinetic",
                             "evidence_source": "signature", "weight": 1.0}  # fmt: skip
    validate(PAYLOAD, event.payload)


# --- the chart of accounts (CUR-07, CUR-18; D90) -------------------------------------------------------------------


def _accounting_index(with_chart: bool) -> PackIndex:
    source = load_source(ACC)
    tables = dict(source.tables)
    if not with_chart:  # an installed pack without its chart table (an older build)
        tables.pop("charts_of_accounts", None)
    assert with_chart == bool(charts_of(source) and "charts_of_accounts" in tables)
    return PackIndex.from_tables([({"pack_id": "pack.acc.o", "version": "0.2.0", "subject": "acc"}, tables)])


def _journal() -> dict[str, Any]:
    lines = [{"account_id": "drawings", "account_name": "Drawings", "accepted_names": ["Drawings"], "debit": "300",
              "credit": "0"},
             {"account_id": "cash", "account_name": "Cash", "accepted_names": ["Cash", "Cash in hand"], "debit": "0",
              "credit": "300"}]  # fmt: skip
    return {"id": "itm.acc.o.double_entry.9901", "type": "journal_entry", "subject": "acc", "kc_ids": [OWNER],
            "parts": [{"id": "a", "prompt": "The owner takes 300 cash for personal use. Write the journal entry.",
                       "marks": 2, "misconception_ids": ["mc.acc.o.de_drawings_as_expense"],
                       "answer": {"kind": "journal_entry", "chart_of_accounts": "coa.acc.o.standard.v1",
                                  "currency": "USD", "lines": lines, "check_id": "chk_build_test_9901"}}]}  # fmt: skip


def test_runtime_chart_decides_wrong_account_class() -> None:
    """With the pack's chart of accounts installed, wages debited for the owner's drawings is the pack's
    drawings-as-expense misconception; without a chart no class is known and nothing is named."""
    journal = _journal()
    with_chart, without = _accounting_index(True), _accounting_index(False)
    context = pack_context(with_chart, journal)
    assert context.chart is not None and context.chart["id"] == "coa.acc.o.standard.v1"
    assert with_chart.chart_of_accounts("acc") == context.chart  # the conventions name the same chart
    named = run(mark(journal, "a", "Dr Wages 300; Cr Cash 300", golden.convert, SETTINGS, golden.run_tool,
                     signatures=context))  # fmt: skip
    assert named.outcome in ("incorrect", "partial") and named.misconception_id == "mc.acc.o.de_drawings_as_expense"
    plain = run(mark(journal, "a", "Dr Wages 300; Cr Cash 300", golden.convert, SETTINGS, golden.run_tool,
                     signatures=pack_context(without, journal)))  # fmt: skip
    assert pack_context(without, journal).chart is None and plain.misconception_id is None
    right = run(mark(journal, "a", "Dr Drawings 300; Cr Cash 300", golden.convert, SETTINGS, golden.run_tool,
                     signatures=context))  # fmt: skip
    assert right.outcome == "correct" and right.misconception_id is None


def test_ref_chart_fits_the_contract() -> None:
    """The pack.ref chart validates against the contract's `ChartOfAccounts` record, and the manifest can list its
    table (CUR-07)."""
    [chart] = charts_of(load_source(ACC))
    validate("content/content-pack#/$defs/ChartOfAccounts", chart)
    pack = document("content/content-pack")
    names = pack["$defs"]["Manifest"]["properties"]["tables"]["items"]["properties"]["name"]["enum"]
    assert "charts_of_accounts" in names and "charts_of_accounts" in pack["properties"]


# --- sign_of_g_flipped stays undecided (CUR-28) --------------------------------------------------------------------


def test_sign_of_g_flipped_never_labels_a_direction_choice() -> None:
    """For a stone dropped from rest the "flipped" answer is the key negated, which is also right with downwards
    taken as negative: the g convention gives a size, not a sign, so the rule must not name it (see signatures.py)."""
    dropped = item("itm.phy.o.motion.0004")
    library = [{"id": "mc.phy.o.gravity_sign_flipped", "kc_ids": ["kc.phy.o.motion.free_fall"],
                "signatures": [{"kind": "structural", "rule": "sign_of_g_flipped"}]}]  # fmt: skip
    context = SignatureContext(misconceptions=library, conventions={"phy.g": "9.8"})
    for answer in ("-19.6 m", "19.6 m", "-39.2 m"):
        verdict = run(mark(dropped, "a", answer, golden.convert, SETTINGS, golden.run_tool, signatures=context))
        assert verdict.misconception_id is None, answer
    assert UNDECIDED_RULES == frozenset({"sign_of_g_flipped"})
