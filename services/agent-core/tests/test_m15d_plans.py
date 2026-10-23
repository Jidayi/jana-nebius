"""M15.d: optional daily plans, catch-up caps, exam phases, plan decisions and student choices, streaks, reminders, the
progress view and Keep learning (LRN-28 to LRN-33, LRN-35, UXS-12, UXS-27). Learners, plans and timings are
synthetic."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import random
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.security import LaunchSecret
from agent_core.engine.assessment.service import AssessmentDesk
from agent_core.engine.plans import PlanDesk, reminder_slot
from agent_core.learner import model, planner
from agent_core.learner.mastery import DAY_MS, MasteryParams
from agent_core.learner.planner import KcPlanInfo, PlannerState, SubjectInfo
from agent_core.learner.policies import exam_phase
from agent_core.store.sessions import SessionStore
from api_harness import cli
from m15_harness import SETTINGS, Practice, physics
from memory_harness import PACK

S = SETTINGS
P = MasteryParams()
SPEED = "kc.phy.o.motion.average_speed"


@contextmanager
def offline() -> Iterator[list[Any]]:
    """Networking blocked: any connection off this machine fails and is recorded."""
    attempts: list[Any] = []
    real = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            attempts.append(host)
            raise OSError("networking is blocked in this test")
        return real(sock, address)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", guarded)
    try:
        yield attempts
    finally:
        patch.undo()


def commands_validator(definition: str) -> Any:
    """The generated validator of one definition of the commands contract (D99 adopted the plan and progress shapes)."""
    from agent_core.contracts import validator

    return validator("api/commands#/$defs/" + definition)


PLAN_VIEW = commands_validator("PlanView")
PROGRESS_VIEW = commands_validator("ProgressView")


def valid(check: Any, body: Any) -> None:
    problems = [f"{list(e.absolute_path)}: {e.message}" for e in check.iter_errors(body)]
    assert problems == [], problems[:3]


def complete(practice: Practice, plan: dict[str, Any]) -> None:
    """Work through every block of a started plan with correct answers on its KCs (mocks are submitted)."""
    for block in plan["blocks"]:
        if block["kind"] in ("warmup", "main", "mixed"):
            kcs = block["kc_ids"] or [SPEED]
            for n in range(block["target"]):
                practice.opportunity(kcs[n % len(kcs)], ("correct",), time_ms=60_000)
        elif block["kind"] == "mock":
            practice.learner.record(
                "mock_submitted",
                {"exam_id": "01J9ZZTESTEXAM00000000000A", "answered": 1, "flagged": 0, "time_used_ms": 1000},
                source="student",
            )


# --- LRN-28: the reference planner ---------------------------------------------------------------------------------


def reference_plan(state: PlannerState) -> dict[str, Any]:
    """LRN-28's pseudo-code written out plainly, with the phase rules of TABLE LRN-30a and the caps of LRN-29."""
    days = [x.days_to_exam for x in state.subjects if x.days_to_exam is not None and x.days_to_exam >= 0]
    nearest = min(days) if days else None
    phase = ("normal" if nearest is None or nearest > 56 else "countdown" if nearest > 14
             else "final" if nearest >= 1 else "exam_day")  # fmt: skip

    def weakness(subject: str) -> float:
        rows = [k for k in state.kcs.values() if k.subject == subject]
        total = sum(k.exam_weight for k in rows)
        return sum(k.exam_weight * (1 - k.p_mastery) for k in rows) / total if total else 0.0

    order = sorted(state.subjects, key=lambda x: (x.days_to_exam if x.days_to_exam is not None else 10**9,
                                                  -weakness(x.subject), x.subject))  # fmt: skip
    names = [x.subject for x in order]
    if names:
        k = state.plans_taken_today % len(names)
        names = names[k:] + names[:k]
    if state.chosen_kc in state.kcs:
        own = state.kcs[state.chosen_kc].subject
        names = [own] + [n for n in names if n != own]
    subjects = names[:2]
    due = [(kc, r) for kc, r in state.due if kc in state.kcs and state.kcs[kc].subject in subjects]
    if phase == "exam_day":
        take = due[:15]
        return {"phase": phase, "blocks": [("warmup", tuple(k for k, _ in take), 15, "exam_phase")],
                "deferred": len(due) - len(take)}  # fmt: skip
    secure = {"mastered", "needs_review"}
    pool = [k for k in state.kcs.values() if k.subject in subjects and k.state not in secure and k.state != "moved_on"]
    if phase == "final":
        pool = [k for k in pool if k.failed_recently]
    ranked = []
    if phase != "final":
        ranked += [(kc, "revisit_moved_on") for kc in sorted(k.kc_id for k in state.kcs.values()
                   if k.subject in subjects and k.revisit_due and k.state not in secure)]  # fmt: skip
    for k in sorted(pool, key=lambda k: (-round(k.exam_weight * (1 - k.p_mastery) * (1 + 0.5 * k.failed_recently), 12),
                                         k.kc_id)):  # fmt: skip
        ready = all(state.kcs[j].p_mastery >= 0.6 for j in k.prerequisites if j in state.kcs)
        if ready or phase == "final":
            ranked.append((k.kc_id, "weak_high_value"))
        else:
            weakest = min((state.kcs[j] for j in k.prerequisites if j in state.kcs and state.kcs[j].p_mastery < 0.6),
                          key=lambda j: (j.p_mastery, j.kc_id))  # fmt: skip
            ranked.append((weakest.kc_id, "prerequisite"))
    unique: list[tuple[str, str]] = []
    for kc, why in ranked:
        if kc not in [u[0] for u in unique]:
            unique.append((kc, why))
    blocks: list[tuple[str, tuple[str, ...], int, str]] = []
    mock_due = state.days_since_mock is None or state.days_since_mock >= 7

    def main_of(kc: str, why: str) -> tuple[str, tuple[str, ...], int, str]:
        return ("main", (kc,), 20 if state.kcs[kc].state == "not_started" else 15, why)

    if state.chosen_kc in state.kcs:
        main: tuple[str, tuple[str, ...], int, str] | None = main_of(state.chosen_kc, "weak_high_value")
    elif phase == "countdown" and mock_due:
        main = ("mock", (), 45, "exam_phase")
    elif unique:
        main = main_of(*unique[0])
    else:
        main = None
    if main:
        blocks.append(main)
    focus = main[1][0] if main and main[1] else None
    if phase == "final" and mock_due:
        blocks.append(("mock", (), 45, "exam_phase"))
    elif focus and not state.support_extra:
        mixed = tuple(sorted(k for k in state.kcs[focus].confusable if k in state.kcs and state.kcs[k].state in secure))
        if mixed:
            blocks.append(("mixed", mixed, 5, "interleave"))
    moved = tuple(sorted([k for k in state.moved_today if k in state.kcs][:50]))
    if moved:
        blocks.append(("reflect", moved, 1, ""))
    rest = sum(b[2] for b in blocks)
    if state.support_extra and main and main[0] == "main":
        others = rest - main[2]
        blocks[0] = (main[0], main[1], min(main[2], max(1, 20 - others)), main[3])
        rest = sum(b[2] for b in blocks)
    take = min(len(due), 15)
    while rest and take and math.ceil(take * 0.5) > 0.3 * (math.ceil(take * 0.5) + rest) + 1e-9:
        take -= 1
    if take:
        blocks.insert(0, ("warmup", tuple(k for k, _ in due[:take]), max(1, math.ceil(take * 0.5)), "due_reviews"))
    return {"phase": phase, "blocks": blocks, "deferred": len(due) - take}


def fixture_state(rng: random.Random) -> PlannerState:
    subjects = rng.sample(["mathematics", "physics", "chemistry", "biology"], rng.randint(1, 3))
    infos = tuple(SubjectInfo(s, rng.choice((None, 120, 60, 40, 20, 10, 3, 0))) for s in subjects)
    kcs: dict[str, KcPlanInfo] = {}
    for s in subjects:
        ids = [f"kc.{s[:3]}.o.fixture.k{n}" for n in range(rng.randint(3, 8))]
        for i, kc in enumerate(ids):
            kcs[kc] = KcPlanInfo(
                kc, s, rng.choice(("not_started", "learning", "ready_to_check", "mastered", "needs_review",
                                   "moved_on")),
                round(rng.random(), 3), round(rng.uniform(0.02, 0.2), 3),
                tuple(rng.sample(ids[:i], min(i, rng.randint(0, 2)))) if i else (),
                tuple(rng.sample(ids, rng.randint(0, 2))), rng.random() < 0.3, rng.random() < 0.1,
            )  # fmt: skip
    due = sorted(((kc, round(rng.random(), 3)) for kc in rng.sample(sorted(kcs), rng.randint(0, len(kcs)))),
                 key=lambda d: (d[1], d[0]))  # fmt: skip
    chosen = rng.choice((None, None, None, rng.choice(sorted(kcs))))
    return PlannerState(infos, kcs, tuple(due), tuple(rng.sample(sorted(kcs), rng.randint(0, 3))),
                        rng.random() < 0.3, rng.randint(0, 2), rng.choice((None, 2, 9)), chosen)  # fmt: skip


def lrn28_matches_reference() -> None:
    rng = random.Random(28)
    phases = set()
    for _ in range(50):
        state = fixture_state(rng)
        found = planner.plan(state, S)
        expected = reference_plan(state)
        assert found.phase == expected["phase"]
        assert [(b.kind, b.kc_ids, b.minutes, b.reason_code) for b in found.blocks] == expected["blocks"], state
        assert found.deferred_reviews == expected["deferred"]
        assert found.payload("01J9ZZTESTPLAN00000000000A", "2026-10-09")["minutes"] == max(1, found.minutes)
        assert len({x for b in found.blocks if b.kind == "main" for x in b.kc_ids}
                   | {k for a in found.alternatives for k in a.kc_ids}) == len(found.alternatives) + sum(
            1 for b in found.blocks if b.kind == "main"), "alternatives are distinct from the main block"  # fmt: skip
        phases.add(found.phase)
    assert phases == {"normal", "countdown", "final", "exam_day"}


def lrn28_no_daily_time_limit() -> None:
    held, practice, desk = physics()
    midnight = held.clock.now - held.clock.now % DAY_MS
    for hour in (0.5, 3, 12, 22, 23.99):  # any hour, no study window (D53)
        held.clock.now = midnight + int(hour * 3_600_000)
        assert desk.propose()["status"] == "proposed"
    held.clock.now = midnight + 8 * 3_600_000
    done = 0
    while done < 3:  # several plans completed on one date
        plan = desk.propose()
        started = desk.decide(plan["plan_id"], "start")
        complete(practice, started)
        assert desk.view(plan["plan_id"])["status"] == "done"
        done += 1
    practice.end(active_ms=100 * 60_000)  # well past 90 minutes of activity
    after = desk.propose()  # another suggestion, no authorization, nothing locked
    assert after["status"] == "proposed" and after["keep_learning"] and after["card"]["title"] == "Keep learning"
    assert after["minutes"] == sum(b["minutes"] for b in after["blocks"]), "an estimate of this plan, not a budget"
    assessments = AssessmentDesk(held.learner, PACK, S, clock_ms=held.clock)
    assert assessments.create_practice("physics", [SPEED], 1)["items_total"] == 1
    days = {r[0] for r in held.conn.execute("SELECT day FROM study_plans")}
    assert (
        len(days) == 1
        and held.conn.execute("SELECT count(*) FROM study_plans WHERE status = 'done'").fetchone()[0] == 3
    )
    card_text = json.dumps(after["card"]).lower()
    assert not re.search(r"\b(daily|limit|pin|quota|left|remaining)\b", card_text), "estimates, never a countdown"


# --- LRN-29: catch-up caps ----------------------------------------------------------------------------------------


def lrn29_spread_backlog() -> None:
    held, practice, desk = physics(exam=None)
    kcs = sorted(PACK.kcs)[:60]
    for kc in kcs:
        practice.opportunity(kc, ("correct",), time_ms=30_000)
    practice.end()
    practice.day(12)  # ten and more missed days: every card is overdue
    due = model.due_cards(held.conn, P, held.clock.now, {}, S.fsrs_exam_window_days)
    overdue = {d.kc_id for d in due}
    assert len(overdue) == 60
    first = desk.propose()
    warmup = next(b for b in first["blocks"] if b["kind"] == "warmup")
    assert len(warmup["kc_ids"]) <= S.review_cap_items
    assert warmup["minutes"] <= S.review_cap_share * first["minutes"] + 1e-9
    assert "deferred" not in json.dumps(first["card"]), "the backlog count is never shown"
    retrievability = {d.kc_id: d.retrievability for d in due}
    taken = [retrievability[k] for k in warmup["kc_ids"]]
    assert taken == sorted(taken) and max(taken) <= min(
        v for k, v in retrievability.items() if k not in warmup["kc_ids"]
    ), "lowest retrievability first"
    # Choosing more review serves the deferred cards at once, with no cap (D54).
    more = desk.propose(all_reviews=True)
    warmups = [b for b in more["blocks"] if b["kind"] == "warmup"]
    assert set().union(*(b["kc_ids"] for b in warmups)) == overdue & set(kcs)
    assert len(warmups) == 2 and all(len(b["kc_ids"]) <= planner.BLOCK_KCS_MAX for b in warmups), "split, not capped"
    assert PLAN_VIEW.is_valid(more)
    # Accepting each day's suggested reviews serves every overdue card within the spread window.
    served: set[str] = set()
    for _ in range(S.review_backlog_days):
        plan = desk.propose()
        warm = next((b for b in plan["blocks"] if b["kind"] == "warmup"), None)
        if warm is not None:
            desk.decide(plan["plan_id"], "start")
            for kc in warm["kc_ids"]:
                practice.opportunity(kc, ("correct",), time_ms=20_000)
                served.add(kc)
        practice.end()
        practice.day(1)
        if overdue <= served:
            break
    assert overdue <= served, sorted(overdue - served)[:5]


# --- LRN-30: exam phases -----------------------------------------------------------------------------------------


def lrn30_phase_transitions() -> None:
    rng = random.Random(30)
    base = fixture_state(rng)
    kcs = {
        k: KcPlanInfo(
            v.kc_id,
            "physics",
            v.state,
            v.p_mastery,
            v.exam_weight,
            v.prerequisites,
            v.confusable,
            v.failed_recently or n % 2 == 0,
            False,
        )
        for n, (k, v) in enumerate(sorted(base.kcs.items()))
    }
    since_mock: int | None = None
    mocks: list[int] = []
    for days in range(120, -1, -1):
        state = PlannerState((SubjectInfo("physics", days),), kcs, tuple((k, 0.5) for k in sorted(kcs)[:3]),
                             days_since_mock=since_mock)  # fmt: skip
        plan = planner.plan(state, S)
        expected = "normal" if days > 56 else "countdown" if days > 14 else "final" if days >= 1 else "exam_day"
        assert plan.phase == expected == exam_phase(days, S), days
        kinds = [b.kind for b in plan.blocks]
        if expected == "normal":
            assert "mock" not in kinds
        elif expected == "countdown":
            assert kinds.count("main") + kinds.count("mock") <= 1, "the timed paper replaces the main block"
        elif expected == "final":
            new = [b for b in plan.blocks if b.kind == "main" and kcs[b.kc_ids[0]].state == "not_started"
                   and not kcs[b.kc_ids[0]].failed_recently]  # fmt: skip
            assert new == [], "no new KC in the final phase"
            assert all(kcs[b.kc_ids[0]].failed_recently for b in plan.blocks if b.kind == "main")
        else:
            assert kinds == ["warmup"] and plan.blocks[0].minutes == S.exam_day_review_minutes, "light review, no mock"
        if "mock" in kinds:
            mocks.append(days)
            since_mock = 0
        elif since_mock is not None:
            since_mock += 1
    countdown = [d for d in mocks if 14 < d <= 56]
    assert countdown and all(a - b >= S.phase_mock_every_days for a, b in itertools.pairwise(countdown))
    assert any(d <= 14 for d in mocks), "full mocks in the final phase"


# --- LRN-31: decisions, Keep learning, stop and resume ---------------------------------------------------------------


def _api(desk: PlanDesk, tmp_path: Path) -> tuple[Any, CoreService]:
    core = CoreService(desk.settings, lambda state: (_ for _ in ()).throw(AssertionError("no model")),
                       SessionStore(tmp_path / "sessions"))  # fmt: skip
    core.planner = lambda: desk
    return create_app(core, LaunchSecret("fixture-token"), lambda: 8911), core


async def _send(client: httpx.AsyncClient, method: str, path: str, body: Any = None, key: str | None = None) -> Any:
    headers = {"authorization": "Bearer fixture-token", "origin": "tauri://localhost"}
    if method != "GET":
        headers["idempotency-key"] = key or cli()
    reply = await client.request(method, path, json=body, headers=headers)
    assert reply.status_code == 200, reply.text
    return reply.json()


def lrn31_decisions_logged(tmp_path: Path) -> None:
    held, practice, desk = physics()
    app, _ = _api(desk, tmp_path)

    def decisions() -> list[dict[str, Any]]:
        return [e.payload for e in held.learner.log.by_seq() if e.type == "plan_decision"]

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            first = await _send(c, "POST", "/v1/plans", {"client_request_id": cli()})
            valid(PLAN_VIEW, first)
            assert len(first["alternatives"]) == S.planner_alternatives
            # Change through the card: the main block swaps for an alternative; a new proposal, the old one changed.
            answer = {"client_answer_id": cli(), "answer": {"action": "change", "option_ids": ["alt_1"]}}
            assert (await _send(c, "POST", f"/v1/cards/{first['request_id']}/answer", answer))["status"] == "accepted"
            assert decisions() == [{"plan_id": first["plan_id"], "decision": "change", "alternative_index": 1}]
            changed = await _send(c, "GET", "/v1/plans/current")
            valid(PLAN_VIEW, changed)
            main = next(b for b in changed["blocks"] if b["kind"] == "main")
            assert main["kc_ids"] == first["alternatives"][1]["kc_ids"] and changed["plan_id"] != first["plan_id"]
            again = {"client_answer_id": cli(), "answer": {"action": "start"}}
            late = await _send(c, "POST", f"/v1/cards/{first['request_id']}/answer", again)
            assert late["status"] == "already_answered", "the replaced card is not answered twice"
            # Not today on the changed plan: no alternative is named.
            skip = {"client_answer_id": cli(), "answer": {"skipped": True}}
            await _send(c, "POST", f"/v1/cards/{changed['request_id']}/answer", skip)
            assert decisions()[-1] == {"plan_id": changed["plan_id"], "decision": "not_today"}
            # Start a fresh plan, finish it, then Keep learning exactly once even after a retry.
            fresh = await _send(c, "POST", "/v1/plans", {"client_request_id": cli()})
            start = {"client_answer_id": cli(), "answer": {"action": "start"}}
            await _send(c, "POST", f"/v1/cards/{fresh['request_id']}/answer", start)
            assert decisions()[-1] == {"plan_id": fresh["plan_id"], "decision": "start"}
            complete(practice, desk.view(fresh["plan_id"]))
            key, request = cli(), {"client_request_id": cli()}
            generated = sum(1 for e in held.learner.log.by_seq() if e.type == "plan_generated")
            keep = await _send(c, "POST", "/v1/plans", request, key=key)
            retry = await _send(c, "POST", "/v1/plans", request, key=key)
            assert keep == retry and keep["keep_learning"] and keep["card"]["title"] == "Keep learning"
            assert sum(1 for e in held.learner.log.by_seq() if e.type == "plan_generated") == generated + 1
            assert keep["date"] == fresh["date"] and keep["plan_id"] != fresh["plan_id"]
            assert decisions()[-1]["plan_id"] == fresh["plan_id"], "no start until Keep learning is accepted"
            await _send(
                c,
                "POST",
                f"/v1/cards/{keep['request_id']}/answer",
                {"client_answer_id": cli(), "answer": {"action": "start"}},
            )
            assert decisions()[-1] == {"plan_id": keep["plan_id"], "decision": "start"}

    asyncio.run(scenario())


def lrn31_stop_resume_progress() -> None:
    held, practice, desk = physics()
    for kc in sorted(PACK.kcs)[:4]:
        practice.opportunity(kc, ("correct",))
    practice.end()
    practice.day(5)
    plan = desk.decide(desk.propose()["plan_id"], "start")
    warm = next(b for b in plan["blocks"] if b["kind"] == "warmup")
    main = next(b for b in plan["blocks"] if b["kind"] == "main")
    for kc in warm["kc_ids"]:
        practice.opportunity(kc, ("correct",))
    for _ in range(2):
        practice.opportunity(main["kc_ids"][0], ("correct",))
    practice.end("student_left")  # stopping mid-activity
    # Restart: a fresh desk over the same database, and a full rebuild of the projections.
    held.learner.projector.rebuild()
    resumed = PlanDesk(held.learner, PACK, S, clock_ms=held.clock).current()
    assert resumed is not None and resumed["plan_id"] == plan["plan_id"] and resumed["status"] == "started"
    blocks = {b["kind"]: b for b in resumed["blocks"]}
    assert blocks["warmup"]["status"] == "done", "completed work is kept"
    assert blocks["main"]["status"] == "in_progress" and blocks["main"]["done"] == 2, "nothing marked done early"
    assert resumed["next_block"] == blocks["main"]["index"], "resumes at the saved position"
    # Shortening changes only this proposal: the next proposal is what it would have been without it.
    practice.day(1)
    practice.opportunity(SPEED, ("correct",))  # a bar moved today: the plan has a reflection block too
    proposal = desk.propose()
    before = planner.plan(desk.state(held.clock.now), S)
    short = desk.change(proposal["plan_id"], shorten=True)
    assert len(short["blocks"]) == 1 and short["minutes"] == short["blocks"][0]["minutes"]
    assert len(proposal["blocks"]) > 1, "there was something to shorten"
    shortened = [e.payload for e in held.learner.log.by_seq() if e.type == "plan_decision"][-1]
    assert shortened["decision"] == "change" and shortened["new_minutes"] == short["minutes"]
    assert "alternative_index" not in shortened
    later = desk.propose()
    assert [(b["kind"], b["kc_ids"], b["minutes"]) for b in later["blocks"]] == [
        (b.kind, list(b.kc_ids), b.minutes) for b in before.blocks]  # fmt: skip


# --- LRN-32: student choices -------------------------------------------------------------------------------------


def lrn32_override_precedence() -> None:
    held, practice, desk = physics()
    for kc in sorted(PACK.kcs)[:3]:
        practice.opportunity(kc, ("correct",))
    practice.end()
    practice.day(4)
    proposal = desk.propose()
    assert len(proposal["blocks"]) >= 2
    order = list(range(len(proposal["blocks"])))[::-1]
    reordered = desk.change(proposal["plan_id"], order=order)
    assert [b["kind"] for b in reordered["blocks"]] == [proposal["blocks"][i]["kind"] for i in order]
    topic = "kc.phy.o.motion.acceleration_from_change"
    chosen = desk.change(reordered["plan_id"], kc_id=topic)
    assert next(b for b in chosen["blocks"] if b["kind"] == "main")["kc_ids"] == [topic]
    shortened = desk.change(chosen["plan_id"], shorten=True)
    assert len(shortened["blocks"]) == 1
    # None of it reaches the next proposal: no persistent preference, no setting.
    fresh = desk.propose()
    assert [(b["kind"], b["kc_ids"]) for b in fresh["blocks"]] == [
        (b.kind, list(b.kc_ids)) for b in planner.plan(desk.state(held.clock.now), S).blocks]  # fmt: skip
    assert held.conn.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
    # Skipping leaves lessons, practice and the tutor available, and asks nothing.
    skipped = desk.decide(fresh["plan_id"], "not_today")
    assert skipped["status"] == "not_today"
    assessments = AssessmentDesk(held.learner, PACK, S, clock_ms=held.clock)
    assessments.guard_tutor()  # the tutor is not locked
    assert assessments.create_practice("physics", [topic], 1)["items_total"] == 1
    assert desk.propose()["status"] == "proposed", "another suggestion whenever asked"
    with pytest.raises(Exception, match="already_decided"):
        desk.change(fresh["plan_id"], shorten=True)


def lrn32_offline_plan() -> None:
    held, practice, desk = physics()
    for kc in sorted(PACK.kcs)[:5]:
        practice.opportunity(kc, ("incorrect", "correct"), rung=1)
    practice.end()
    practice.day(3)
    state = desk.state(held.clock.now)
    online = planner.plan(state, S)
    with offline() as attempts:
        blocked = planner.plan(desk.state(held.clock.now), S)
        proposed = desk.propose()
        started = desk.decide(proposed["plan_id"], "start")
        keep = desk.propose()
    assert attempts == []
    assert blocked == online
    assert [(b["kind"], b["kc_ids"]) for b in proposed["blocks"]] == [(b.kind, list(b.kc_ids)) for b in online.blocks]
    assert started["status"] == "started" and keep["status"] == "proposed"


# --- LRN-33: streaks with freeze ----------------------------------------------------------------------------------


def _work(practice: Practice, minutes: float) -> None:
    practice.opportunity(SPEED, ("correct",), time_ms=int(minutes * 60_000))
    practice.end()


def lrn33_streak_rules() -> None:
    held, practice, desk = physics(day="2026-10-10")  # a Saturday
    weekly = S.streak_weekly_freezes

    def streak() -> model.Streak:
        return model.streak(held.conn, P, held.clock.now, weekly)

    _work(practice, S.streak_min_minutes)
    assert streak().days == 1 and streak().counted_today
    practice.day()
    _work(practice, S.streak_min_minutes - 1)  # less than the minimum of checked work does not count
    assert streak().days == 1 and not streak().counted_today
    _work(practice, 1)
    assert streak().days == 2, "the day's checked work adds up"
    practice.day()  # Monday: a freeze is earned this week
    _work(practice, 6)
    assert streak().days == 3 and streak().freezes_left == min(S.streak_max_freezes, weekly)
    practice.day()  # Tuesday: the app is opened, nothing is checked
    practice.start()
    practice.end(active_ms=120_000)
    assert not streak().counted_today and streak().days == 3
    practice.day()  # Wednesday: the missed Tuesday is covered by the freeze
    _work(practice, 6)
    assert streak().days == 4 and streak().freezes_left == 0
    frozen = held.conn.execute("SELECT freeze_used FROM engagement_daily WHERE day = '2026-10-13'").fetchone()
    assert frozen == (1,)
    practice.day(3)  # two missed days with no freeze left
    assert streak().days == 0, "shown neutrally as a new streak to start"
    _work(practice, 6)
    assert streak().days == 1, "New streak: day 1"
    # A completed plan block counts, even with little checked time.
    practice.day()
    plan = desk.decide(desk.propose()["plan_id"], "start")
    block = plan["blocks"][0]
    for n in range(block["target"]):
        practice.opportunity((block["kc_ids"] or [SPEED])[n % max(1, len(block["kc_ids"]))], ("correct",),
                             time_ms=5_000)  # fmt: skip
    assert streak().days == 2 and streak().counted_today


# --- LRN-35: reminders ---------------------------------------------------------------------------------------------


def lrn35_notification_limits() -> None:
    start, end = (h * 60 for h in S.notify_quiet_hours)
    for minute in range(0, 24 * 60, 7):
        slot = reminder_slot(True, minute, 0, minute, S)
        if slot is not None:
            assert end <= slot < start, "never between 21:00 and 07:00 local"
    assert reminder_slot(True, 6 * 60, 0, 6 * 60, S) == end, "a reminder asked for at 06:00 waits for 07:00"
    assert reminder_slot(True, 22 * 60, 0, 22 * 60, S) is None
    assert reminder_slot(True, 18 * 60, 0, 21 * 60 + 30, S) is None
    assert reminder_slot(True, 12 * 60, S.notify_max_per_day, 12 * 60, S) is None, "at most one a day"
    assert reminder_slot(False, 12 * 60, 0, 12 * 60, S) is None, "never while reminders are off"
    held, _, desk = physics()
    assert desk.next_reminder(12 * 60, 0, preferred_minute=18 * 60) is None, "the notifications preference is off"
    held.conn.execute("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at) VALUES"
                      " ('notifications', 'true', 'student', NULL, '0', 0)")  # fmt: skip
    assert desk.next_reminder(12 * 60, 0, preferred_minute=18 * 60) == 18 * 60
    assert desk.next_reminder(12 * 60, 1, preferred_minute=18 * 60) is None


# --- UXS-27: the grade band gate; UXS-12: Keep learning without a time limit ---------------------------------------


# Letters invented for the tests, not a board's: D27 shows a band only in the letters a pack sets for its board.
LETTERS = ["P", "Q", "R", "S", "T"]


def lettered(pack: Any = PACK) -> Any:
    """The physics pack with one grade scale set in every mock paper, as a pack for a chosen board would carry."""
    import dataclasses

    scale = {"boundaries": list(S.grade_boundaries), "labels": LETTERS}
    papers = {k: {**v, "grade_config": scale} for k, v in pack.records.get("mock_papers", {}).items()}
    return dataclasses.replace(pack, records={**pack.records, "mock_papers": papers})


def uxs27_grade_band_gate(tmp_path: Path) -> None:
    held, practice, _ = physics()
    desk = PlanDesk(held.learner, lettered(), S, clock_ms=held.clock)
    kcs = sorted(PACK.kcs)
    for kc in kcs[:12]:
        practice.opportunity(kc, ("correct",))
    progress = desk.progress("physics")
    valid(PROGRESS_VIEW, progress)
    grade = progress["subjects"][0]["grade"]
    assert grade == {"status": "hidden", "checked": 12, "needed": S.grade_min_checked}
    assert "p_mastery" not in json.dumps(progress) and "0." not in json.dumps(progress["subjects"][0]["bands"])
    for kc in kcs[12:90]:
        practice.opportunity(kc, ("correct",))
    progress = desk.progress("physics")
    valid(PROGRESS_VIEW, progress)
    grade = progress["subjects"][0]["grade"]
    assert grade["status"] == "shown" and grade["checked"] >= S.grade_min_checked
    assert len(grade["range"]) == 2 and grade["confidence"] == S.grade_interval_share
    assert {grade["band"], *grade["range"]} <= set(LETTERS)  # the board's letters, never "1" to "5" (D27)
    subject = progress["subjects"][0]
    assert sum(subject["bands"].values()) == len(kcs) and subject["history"][-1]["learning"] == 90
    app, _ = _api(desk, tmp_path)

    async def over_http() -> Any:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            return await _send(c, "GET", "/v1/progress")

    assert asyncio.run(over_http()) == desk.progress()


def test_progress_shows_no_band_without_board_letters(tmp_path: Path) -> None:
    """ASM-19, D27: a subject whose pack sets no board grade letters shows no band at all, however much is checked;
    the status says so (`no_scale`, adopted in D101), never a numeric band."""
    _, practice, desk = physics()
    for kc in sorted(PACK.kcs)[:90]:
        practice.opportunity(kc, ("correct",))
    progress = desk.progress("physics")
    valid(PROGRESS_VIEW, progress)
    grade = progress["subjects"][0]["grade"]
    assert grade == {"status": "no_scale", "checked": 90, "needed": S.grade_min_checked}


def uxs12_keep_learning_without_time_limit(tmp_path: Path) -> None:
    """The core side of Home's Keep learning (the screen's side is the desktop app's
    test_uxs12_keep_learning_on_home): after several finished plans and more than 90 minutes of activity, another plan
    starts, offline, with no limit and no PIN; stopping part way keeps what was done, resumes at the next activity, and
    a further plan can still be asked for."""
    held, practice, desk = physics()
    app, _ = _api(desk, tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            for _ in range(3):
                plan = await _send(c, "POST", "/v1/plans", {"client_request_id": cli()})
                await _send(c, "POST", f"/v1/cards/{plan['request_id']}/answer",
                            {"client_answer_id": cli(), "answer": {"action": "start"}})  # fmt: skip
                complete(practice, desk.view(plan["plan_id"]))
            practice.end(active_ms=95 * 60_000)
            keep = await _send(c, "POST", "/v1/plans", {"client_request_id": cli()})
            valid(PLAN_VIEW, keep)
            assert keep["keep_learning"] and keep["status"] == "proposed"
            started = await _send(c, "POST", f"/v1/cards/{keep['request_id']}/answer",
                                  {"client_answer_id": cli(), "answer": {"action": "start"}})  # fmt: skip
            assert started["status"] == "accepted"
            current = await _send(c, "GET", "/v1/plans/current")
            assert current["plan_id"] == keep["plan_id"] and current["status"] == "started"
            # Stop part way through the first activity: what was done is kept, nothing is marked done early, and the
            # plan resumes at the same activity.
            first = current["blocks"][0]
            assert first["target"] >= 2, first
            kcs = first["kc_ids"] or [SPEED]
            for n in range(first["target"] - 1):
                practice.opportunity(kcs[n % len(kcs)], ("correct",), time_ms=60_000)
            practice.end("student_left")
            resumed = await _send(c, "GET", "/v1/plans/current")
            valid(PLAN_VIEW, resumed)
            assert resumed["plan_id"] == keep["plan_id"] and resumed["status"] == "started"
            assert resumed["blocks"][0]["done"] == first["target"] - 1, "stopping keeps the work done"
            assert resumed["blocks"][0]["status"] == "in_progress" and resumed["next_block"] == first["index"]
            # Still no limit: one more plan is proposed on request, and no reply asks for a PIN or anyone's approval.
            more = await _send(c, "POST", "/v1/plans", {"client_request_id": cli()})
            assert more["status"] == "proposed" and more["plan_id"] != keep["plan_id"]
            for reply in (keep, started, current, resumed, more):
                assert not re.search(r"\bpin\b|approv|authori[sz]", json.dumps(reply), re.IGNORECASE)

    with offline() as attempts:
        asyncio.run(scenario())
    assert attempts == []
    minutes = held.conn.execute("SELECT sum(minutes_active) FROM engagement_daily").fetchone()[0]
    assert minutes > 90


def test_reflect_block_keeps_the_latest_fifty_kcs_within_the_contract():
    """A day that moved more KCs than a plan block may name (PlanBlock.kc_ids, at most 50) reflects on its latest."""
    from agent_core.config import Settings
    from agent_core.contracts import errors

    kcs = {f"kc.mth.o.fixture.k{n:03d}": KcPlanInfo(f"kc.mth.o.fixture.k{n:03d}", "mathematics", "learning", 0.5, 0.1,
                                                    (), (), False, False) for n in range(94)}  # fmt: skip
    latest_first = tuple(reversed(sorted(kcs)))
    state = PlannerState((SubjectInfo("mathematics", None),), kcs, (), latest_first)
    reflect = next(b for b in planner.plan(state, Settings()).blocks if b.kind == "reflect")
    assert reflect.kc_ids == tuple(sorted(latest_first[: planner.BLOCK_KCS_MAX]))
    block = {"index": 0, "kind": "reflect", "kc_ids": list(reflect.kc_ids), "minutes": 1, "status": "pending",
             "done": 0, "target": 0}  # fmt: skip
    assert errors("api/commands#/$defs/PlanBlock", block) == []
