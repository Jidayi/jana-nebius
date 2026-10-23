"""D94: a session started by asking follows the subject of its first question (AGT-15, TABLE API-41a, PED-24).

The real S2 engine, registry, router and worker with scripted providers, and the core for the session list. The
installed packs are the repository's physics and mathematics O-level sources; questions and replies are synthetic."""

from __future__ import annotations

import asyncio
import json
from functools import cache
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.state import BoardStep
from agent_core.retrieval.index import KnowledgeIndex
from api_harness import ask, cli, start_core, stop_core
from api_harness import scripted as scripted_provider
from engine_harness import STATEMENT, close, reply, solver_steps, tutor
from engine_harness import make_engine as harness_engine
from jana_tools import REPO_ROOT
from pack_builder.build import load_source

LOOP = asyncio.new_event_loop()
CURRICULUM = REPO_ROOT / "content" / "curriculum"
SAFE = "Which quantities does the question give you, and which one does it ask for?"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def settings() -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0,
                    worker_call_cpu_ms=30000)  # fmt: skip


@cache
def knowledge(*codes: str) -> KnowledgeIndex:
    """The installed packs: the O-level sources of the subjects named by code."""
    sources = [load_source(CURRICULUM / code / "o") for code in codes]
    return KnowledgeIndex.from_tables([(dict(s.pack), {t: list(rows) for t, rows in s.tables.items()})
                                       for s in sources])  # fmt: skip


def structured(payload: dict[str, Any]) -> dict[str, Any]:
    return reply(json.dumps(payload))


def guard() -> dict[str, Any]:
    return structured({"class": "in_scope", "confidence": 0.9})


def diagnosis(subject: str, **fields: Any) -> dict[str, Any]:
    out = {"in_scope": True, "subject": subject, "topic_ref": None, "kc_refs": [], "question_kind": "calculation",
           "knowns": [], "unknowns": ["height"], "clarifying_question": None, "misconception_ref": None,
           "evidence": [], "inference": "", "prerequisite_gap_refs": [], "confidence": "medium"}  # fmt: skip
    out.update(fields)
    return structured(out)


async def make_engine(tmp: Path, script: dict[str, Any], subject: str, origin: str = "ask",
                      packs: tuple[str, ...] = ("phy", "mth")) -> tuple[Any, Any, list[str]]:  # fmt: skip
    engine, provider = await harness_engine(tmp, script, settings=settings(), stage="S2")
    engine.state.subject, engine.state.origin = subject, origin
    engine.bind_knowledge(knowledge(*packs))
    saved: list[str] = []
    engine.save_question = lambda state, reason: saved.append(reason)
    return engine, provider, saved


def events(engine: Any, kind: str) -> list[dict[str, Any]]:
    return [f["event"] for f in engine.events.frames if f["event"]["type"] == kind]


def roles(provider: Any) -> list[str]:
    return [str(r.get("_role")) for r in provider.requests]


def diagnoser_tasks(provider: Any) -> list[str]:
    return [json.dumps(r["messages"]) for r in provider.requests if r.get("_role") == "diagnoser"]


def subject_cards(engine: Any) -> list[dict[str, Any]]:
    return [e["card"] for e in events(engine, "card.open") if e["card"].get("subject") is not None]


def taught(engine: Any, provider: Any) -> bool:
    """The problem went on in the session: the Solver planned it and the Coach opened it."""
    return engine.state.plan is not None and "solver" in roles(provider) and "coach" in roles(provider)


def agt15_first_question_sets_subject(tmp_path: Path) -> None:
    """The first question of a session started by asking, placed by the Diagnoser in another subject whose pack is
    installed: the candidates and the Diagnoser run again on that subject, then one `session.updated` carries the new
    subject and topic before the Solver runs; no card is offered and nothing is saved as outside the content."""
    script = {"input_guard": [guard()],
              "diagnoser": [diagnosis("physics", in_scope=False), diagnosis("physics", topic_ref=1)],
              "solver": solver_steps(), "coach": [tutor(SAFE)]}  # fmt: skip
    engine, provider, saved = run(make_engine(tmp_path, script, "mathematics"))
    try:
        run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    tasks = diagnoser_tasks(provider)
    assert len(tasks) == 2
    assert "Subject: mathematics" in tasks[0] and "Subject: physics" in tasks[1]
    physics_topics = [t for t, _ in knowledge("phy", "mth").topic_scores(STATEMENT, subjects=["phy"],
                                                                               limit=6)]  # fmt: skip
    assert physics_topics and all(t.startswith("cur.phy.o.") for t in physics_topics)
    updates = [e for e in events(engine, "session.updated") if "subject" in e]
    assert updates == [{"type": "session.updated", "subject": "physics", "topic_id": physics_topics[0]}]
    assert engine.state.subject == "physics" and engine.state.topic_id == physics_topics[0]
    assert engine.diagnosis is not None and engine.diagnosis.topic_id == physics_topics[0]
    order = roles(provider)
    assert order.index("solver") > max(i for i, r in enumerate(order) if r == "diagnoser")
    frames = [f["event"]["type"] for f in engine.events.frames]
    switched = next(i for i, f in enumerate(engine.events.frames) if f["event"].get("subject") == "physics")
    assert "board.reset" not in frames[:switched], "the switch comes before any board work"
    assert subject_cards(engine) == [] and "outside_content" not in saved
    assert taught(engine, provider)
    assert all(contract_errors("api/events#/$defs/ev_session_updated", e) == [] for e in updates)


def test_agt15_first_question_candidates_span_installed_subjects(tmp_path: Path) -> None:
    """The first question of a session started by asking is shown topic candidates from every installed subject, so a
    physics question in a session that opened on mathematics can be placed in physics (D94). A later problem keeps to
    the session's subject."""
    from agent_core.engine import team

    engine, _, _ = run(make_engine(tmp_path, {}, "mathematics"))
    try:
        assert team.first_asked(engine)
        topics, _, _ = team.candidates(engine, STATEMENT)
        assert any(t.startswith("cur.phy.o.") for t in topics), topics
        engine.state.transcript.extend([{"kind": "problem"}, {"kind": "problem"}])
        later, _, _ = team.candidates(engine, STATEMENT)
        assert later and all(t.startswith("cur.mth.o.") for t in later), later
    finally:
        run(close(engine))


def agt15_other_subject_offers_a_card(tmp_path: Path) -> None:
    """The same kind of question keeps the session's subject and opens one confirm card naming the other subject when
    the session was opened from a lesson, practice or review, when it is a later problem, when the board already holds
    a step, and when no pack for that subject is installed at the level; only the last is saved as outside the
    content. The problem goes on in the session's subject every time."""

    def check(engine: Any, provider: Any, saved: list[str], subject: str, other: str, outside: bool) -> None:
        assert engine.state.subject == subject
        assert not [e for e in events(engine, "session.updated") if "subject" in e]
        cards = subject_cards(engine)
        assert len(cards) == 1, cards
        card = cards[0]
        assert card["card_type"] == "confirm" and card["purpose"] == "other" and card["subject"] == other
        assert card["confirm_label_key"] == "card.new_subject.start"
        assert card["cancel_label_key"] == "card.new_subject.stay"
        assert other.capitalize() in card["title"] and subject.capitalize() in card["body"]
        assert contract_errors("api/events#/$defs/card", card) == []
        assert ("outside_content" in saved) is outside
        assert taught(engine, provider)

    def script(*diagnoses: dict[str, Any]) -> dict[str, Any]:
        n = len(diagnoses)
        return {"input_guard": [guard()] * n, "diagnoser": list(diagnoses), "solver": solver_steps() * n,
                "coach": [tutor(SAFE)] * n}  # fmt: skip

    # Opened from a lesson, practice or a mock review: the session's subject stays.
    for origin in ("lesson", "practice_item", "exam_review"):
        engine, provider, saved = run(make_engine(tmp_path / origin, script(diagnosis("physics")), "mathematics",
                                                  origin))  # fmt: skip
        try:
            run(engine.start_problem(STATEMENT))
        finally:
            run(close(engine))
        check(engine, provider, saved, "mathematics", "physics", outside=False)

    # A later problem of a session started by asking.
    later = script(diagnosis("mathematics"), diagnosis("physics"))
    engine, provider, saved = run(make_engine(tmp_path / "later", later, "mathematics"))
    try:
        run(engine.start_problem("Solve 3x + 5 = 20 for x."))
        assert not subject_cards(engine)
        run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    check(engine, provider, saved, "mathematics", "physics", outside=False)

    # Work already on the board.
    engine, provider, saved = run(make_engine(tmp_path / "board", script(diagnosis("physics")), "mathematics"))
    engine.state.board.steps.append(BoardStep("stp_working", 1, "x = 5", None, "student", "unchecked"))
    try:
        run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    check(engine, provider, saved, "mathematics", "physics", outside=False)

    # No pack for the question's subject at the level: the card, and the question saved for human help (PED-24).
    engine, provider, saved = run(make_engine(tmp_path / "nopack", script(diagnosis("chemistry", in_scope=False)),
                                              "physics", packs=("phy",)))  # fmt: skip
    try:
        run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    check(engine, provider, saved, "physics", "chemistry", outside=True)


def api41_session_topic_from_diagnosis(tmp_path: Path) -> None:
    """A new problem whose diagnosed topic differs from the session's emits `session.updated` with that `topic_id`
    once, and the session list carries it; the same topic again emits nothing."""
    script = {"input_guard": [guard()] * 2, "diagnoser": [diagnosis("physics", topic_ref=1)] * 2,
              "solver": solver_steps() * 2, "coach": [tutor(SAFE)] * 2}  # fmt: skip
    provider = scripted_provider(script)

    async def scenario() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        running = await start_core(tmp_path, provider, settings=settings(), stage="S2")
        try:
            core = running.core
            body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                    "origin": {"kind": "ask", "ref": None}}  # fmt: skip
            session = core.create_session(body)["session_id"]
            engine = core._engine(core.sessions[session])
            engine.bind_knowledge(knowledge("phy", "mth"))
            core.start_turn(session, ask(STATEMENT))
            await running.wait_idle(session)
            core.start_turn(session, ask(STATEMENT))
            await running.wait_idle(session)
            updates = [f["event"] for f in engine.events.frames
                       if f["event"]["type"] == "session.updated" and "topic_id" in f["event"]]  # fmt: skip
            listed = next(s for s in core.list_sessions()["sessions"] if s["session_id"] == session)
            return updates, listed
        finally:
            await stop_core(running)

    updates, listed = run(scenario())
    topic = next(t for t, _ in knowledge("phy", "mth").topic_scores(STATEMENT, subjects=["phy"], limit=6))
    assert updates == [{"type": "session.updated", "topic_id": topic}]
    # The list names the topic, and where the session was opened from (API-23, D94).
    assert listed["topic_id"] == topic and listed["subject"] == "physics" and listed["origin"] == "ask"
    assert contract_errors("api/commands#/$defs/Session", listed) == []
