"""M25.a journeys JRN-05 (stuck in practice, persona P3) and JRN-07 (a daily plan taking one KC to mastery,
persona P1), played on the shipped core over its local API (JRN-02 runner). Learners, answers and model replies are
synthetic; items, lessons and misconceptions are the repository's own physics sources."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.engine.events import new_id
from agent_core.learner.projections import local_date
from api_harness import stop_core
from engine_harness import tutor
from jana_tools import REPO_ROOT
from jana_tools.journeys.runner import Probe, Run
from journey_harness import (
    SETTINGS,
    branches,
    core,
    learner,
    play,
    restart,
    scripted,
    start,  # fmt: skip
    turn,
)
from test_g114_s2_engine import diagnosis, guard
from test_m10a_profiles import Api
from test_m13g_learn import Client, item_record, source
from test_m15d_plans import PLAN_VIEW, PROGRESS_VIEW, valid

S = SETTINGS
FLOAT = "kc.phy.o.density.floating_and_sinking"
SAY = "Which part of the question tells you what decides whether it floats?"
TWO_QUESTIONS = "Good, you picked a statement. Why does that one hold? And what would change in salty water?"


class Always(list[Any]):
    """One reply a role gives on every call, however many calls a journey makes."""

    def pop(self, index: Any = -1) -> Any:
        return self[0]


class Replies(dict[str, Any]):
    """The fake model's replies by role, each role the same on every call; an unscripted role fails the call."""

    def get(self, role: Any, default: Any = None) -> Any:
        if role not in self:
            raise LookupError(f"no scripted reply for role {role!r}")
        return dict.get(self, role)

    def say(self, role: str, reply: Any) -> None:
        self[role] = Always([reply])


def replies() -> Replies:
    return Replies(input_guard=Always([guard()]), rule_matcher=Always([guard()]),
                   diagnoser=Always([diagnosis(subject="physics")]), coach=Always([tutor(SAY)]))  # fmt: skip


def wrong_option(item: dict[str, Any]) -> dict[str, Any]:
    """A distractor of the item's first part that its author tied to a misconception (CUR-18)."""
    return next(o for o in item["parts"][0]["answer"]["options"] if not o["correct"] and o.get("misconception_id"))


def right_option(item: dict[str, Any]) -> dict[str, Any]:
    return next(o for o in item["parts"][0]["answer"]["options"] if o["correct"])


def mcq(option_id: str, part_id: str = "a") -> dict[str, Any]:
    return {"parts": [{"part_id": part_id, "kind": "mcq", "option_id": option_id}]}


def misconception(mc_id: str) -> dict[str, Any]:
    return next(m for m in source("phy")["misconceptions"] if m["id"] == mc_id)


def day(ahead: float = 0) -> str:
    """The UTC date `ahead` days from now (the scheduler's dates are UTC days)."""
    return datetime.fromtimestamp(time.time() + ahead * 86_400, UTC).date().isoformat()


def db(r: Any) -> Any:
    """The open profile's learner database, read only where no route shows what a step checks."""
    return r.runtime.learner.conn


def kc_row(r: Any, kc_id: str) -> dict[str, Any]:
    row = db(r).execute("SELECT status, p_mastery, attempts, correct, bottom_outs, stuck_count, mastery_check_state"
                        " FROM kc_mastery WHERE kc_id = ?", (kc_id,)).fetchone()  # fmt: skip
    keys = ("status", "p_mastery", "attempts", "correct", "bottom_outs", "stuck_count", "check_state")
    return dict(zip(keys, row, strict=True)) if row else {"status": "not_started", "attempts": 0}


def coach_inputs(provider: Any, since: int) -> list[str]:
    """What the Coach was actually sent after request `since`: the last message of each Coach call."""
    return [json.dumps(q["messages"][-1]["content"]) for q in provider.requests[since:] if q.get("_role") == "coach"]


def tutor_messages(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in snapshot["messages"] if m["role"] == "tutor"]


def tutor_text(snapshot: dict[str, Any], message: dict[str, Any]) -> str:
    return " ".join(str(snapshot["parts"][p].get("text") or "") for p in message.get("part_ids", [])
                    if snapshot["parts"][p]["kind"] == "text")  # fmt: skip


async def practise(c: Any, set_id: str, item_id: str, answer: dict[str, Any], time_ms: int = 30_000) -> dict[str, Any]:
    body = {"client_attempt_id": new_id("cli"), "item_id": item_id, "answer": answer, "time_ms": time_ms,
            "hints_used": 0}  # fmt: skip
    return await c.ok("POST", f"/v1/practice/sets/{set_id}/answers", body)


async def practice_set(c: Any, kc_ids: list[str], size: int) -> dict[str, Any]:
    body = {"client_set_id": new_id("cli"), "subject": "physics", "size": size, "source": "topic", "kc_ids": kc_ids}
    return await c.ok("POST", "/v1/practice/sets", body)


class Clock:
    """The simulated clock of a multi-day run: the core reads wall time through `time.time`, which this moves on by
    seconds, hours or days while asyncio, the server and every timeout keep the monotonic clock."""

    def __init__(self) -> None:
        self.real = time.time
        self.offset = 0.0

    def __enter__(self) -> Clock:
        time.time = lambda: self.real() + self.offset
        return self

    def __exit__(self, *_: Any) -> None:
        time.time = self.real

    def advance(self, seconds: float) -> None:
        self.offset += seconds

    def days(self, n: float = 1) -> None:
        self.advance(n * 86_400)


def rule_action(rule_id: str) -> str:
    """A soft rule's action as the shipped rule book words it (the Coach is given actions, never ids)."""
    book = yaml.safe_load((REPO_ROOT / "content" / "agent" / "rules" / "core-pedagogy.yaml").read_text())
    rules = book["rules"] if isinstance(book, dict) else book
    return str(next(r for r in rules if r["id"] == rule_id)["action"])


async def help_session(c: Any, kc_id: str, size: int = 3) -> tuple[dict[str, Any], dict[str, Any], str]:
    """A practice set on one KC, its first item answered with a misconception's distractor, then "Help me" on it:
    (the set, the item's source record, the tutor session id)."""
    made = await practice_set(c, [kc_id], size)
    record = item_record("phy", made["current_item"]["item_id"])
    await practise(c, made["set_id"], record["id"], mcq(wrong_option(record)["id"]))
    opened = await c.ok("POST", f"/v1/practice/sets/{made['set_id']}/help", {"item_id": record["id"]})
    return made, record, str(opened["session_id"])


# --- JRN-05: stuck in practice ---------------------------------------------------------------------------------------


def _stuck(tmp_path: Path) -> Probe:
    async def probe(run: Run) -> None:
        said = replies()
        provider = scripted(said)
        async with core(tmp_path, provider=provider) as r:
            c, _ = await learner(r, "Kofi")
            made = await practice_set(c, [FLOAT], 3)
            first = made["current_item"]
            record = item_record("phy", first["item_id"])
            wrong, right = wrong_option(record), right_option(record)
            with run.step(1):  # ASM-03, ASM-13, CUR-18, LRN-04
                calls = len(provider.requests)
                marked = await practise(c, made["set_id"], first["item_id"], mcq(wrong["id"]))
                assert len(provider.requests) == calls, "practice is marked by code, with no model call"
                assert marked["verdict"] == "incorrect" and marked["marks_awarded"] == 0, marked
                assert marked["reflection"]["card_type"] == "reflection" and marked["mastery_change"]["kc_id"] == FLOAT
                attempt = db(r).execute("SELECT outcome, misconception_id FROM attempts WHERE item_ref = ?",
                                        (first["item_id"],)).fetchall()  # fmt: skip
                assert attempt == [("incorrect", wrong["misconception_id"])], "the distractor's misconception is kept"
                held = (
                    db(r)
                    .execute(
                        "SELECT kc_id, evidence_count FROM learner_misconceptions WHERE misconception_id = ?",
                        (wrong["misconception_id"],),
                    )
                    .fetchone()
                )
                assert held is not None and held[0] in record["kc_ids"] and held[1] >= 1
                assert kc_row(r, FLOAT)["attempts"] == 1, "the attempt is evidence on the item's KC (LRN-04)"
            with run.step(2):  # AGT-23, LRN-18: "Help me" opens the tutor on this item
                opened = await c.ok("POST", f"/v1/practice/sets/{made['set_id']}/help", {"item_id": first["item_id"]})
                sid = opened["session_id"]
                snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
                assert snap["session"]["origin"] == "practice_item" and snap["session"]["mode"] == "guided"
                state = r.core.sessions[sid].engine_state
                assert state.practice["item"]["id"] == first["item_id"] and state.problem.problem_id == first["item_id"]
                assert state.attempts[state.step] == 1, "the submitted answer counts as the attempt (UXS-24, PED-05)"
                p_k = kc_row(r, FLOAT)["p_mastery"]
                since = len(provider.requests)
                await turn(c, sid, "I am not sure how to start this one", "stuck")
                snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
                hinted = tutor_messages(snap)[-1]
                start = 2 if p_k < S.hint_concept_below else 1  # LRN-18: no hint history yet on this KC
                assert hinted["intent"] == "stuck" and hinted["hint_rung"] == start, (hinted, p_k)
                run.note(f"start rung {start} at P_k {p_k:.2f}")
            with run.step(3):  # PED-22, CUR-18: the Coach is given the matched misconception and its targeted fix
                sent = coach_inputs(provider, since)
                fix = misconception(wrong["misconception_id"])["fix"]["text"]["en"]
                assert sent and wrong["misconception_id"] in sent[-1] and json.dumps(fix)[1:-1] in sent[-1], sent[-1:]
                assert FLOAT in misconception(wrong["misconception_id"])["kc_ids"], "the fix is one of the KC's"
            with run.step(4):  # VER-06, AGT-23: each line marked by code; one short question per Coach turn
                said.say("coach", tutor(TWO_QUESTIONS))
                await turn(
                    c, sid, "Show this step", "show_step"
                )  # the full step after an attempt: the bottom-out rung (PED-07)
                engine = await turn(c, sid, right["id"], "answer")
                snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
                lines = [
                    b["steps"][i]
                    for b in snap["boards"].values()
                    for i in b["order"]
                    if b["steps"][i]["owner"] == "student"
                ]
                assert lines and lines[-1]["status"] == "correct", lines
                assert engine.state.solved
                for message in tutor_messages(snap)[-2:]:
                    assert tutor_text(snap, message).count("?") == 1, tutor_text(snap, message)
                assert tutor_messages(snap)[-2]["hint_rung"] == 5
            with run.step(5):  # UXS-24, PED-07: back to the same set at the same place; a similar item scheduled
                back = await c.ok("GET", f"/v1/practice/sets/{made['set_id']}")
                assert back["current_item"]["item_id"] == marked["next_item"]["item_id"], "help never moved the set"
                again = await c.ok("POST", f"/v1/practice/sets/{made['set_id']}/help", {"item_id": first["item_id"]})
                assert r.core.sessions[again["session_id"]].engine_state.practice["item"]["id"] == first["item_id"]
                row = kc_row(r, FLOAT)
                assert row["attempts"] >= 2 and row["bottom_outs"] >= 1, "mastery updated, the bottom-out kept (LRN-06)"
                scheduled = engine.state.scheduled  # held by the session's engine: no route shows it
                assert scheduled and list(scheduled[-1]["kc_ids"]) == [FLOAT], scheduled
                assert [scheduled[-1]["earliest"], scheduled[-1]["latest"]] == [
                    day(days) for days in S.bottom_out_review_days
                ]

    return probe


def _f1_offer(tmp_path: Path) -> Probe:
    """F1: two wrong attempts in a row on the step (or the idle time with the window focused): a hint is offered, not
    shown, once on the step (LRN-20)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        async with core(tmp_path, provider=provider) as r:
            c, _ = await learner(r, "Kofi")
            _, record, sid = await help_session(c, FLOAT)
            since = len(provider.requests)
            for _ in range(S.offer_after_wrong - 1):  # the practice answer was the first wrong attempt on the step
                await turn(c, sid, wrong_option(record)["id"], "answer")
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            offered = [p for p in snap["parts"].values()  # the quiet hint-offer line (D112)
                       if p["kind"] == "notice" and p["notice"]["code"] == "hint_offer"]  # fmt: skip
            told = [x for x in coach_inputs(provider, since) if rule_action("unprompted_offer_when_idle") in x]
            assert offered or told, "an unprompted hint offer after the repeated wrong attempts"
            assert not tutor_messages(snap)[-1].get("hint_rung"), "offered, never shown"

    return probe


def _f2_hint_burst(tmp_path: Path) -> Probe:
    """F2: two hint requests inside the gaming gap pause hints; the tutor asks for an attempt in one line of
    help-seeking coaching; the next attempt lifts the pause (LRN-19)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            async with core(tmp_path, provider=provider) as r:
                c, _ = await learner(r, "Kofi")
                _, record, sid = await help_session(c, FLOAT)
                started = time.time()
                engine = await turn(c, sid, "Can I have a hint?", "stuck")
                rung = engine.state.rung
                since = len(provider.requests)
                engine = await turn(c, sid, "Another hint please", "stuck")
                assert time.time() - started < S.gaming_hint_gap_s, "both requests inside the gap"
                snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
                paused = tutor_text(snap, tutor_messages(snap)[-1]).strip()
                assert engine.state.rung == rung, "no higher rung inside the gap"
                assert paused and "\n" not in paused, "one line of help-seeking coaching"
                assert not coach_inputs(provider, since), "the pause is the engine's line, not a model's"
                flags = db(r).execute("SELECT count(*) FROM events WHERE type = 'integrity_signal'"
                                      " AND json_extract(payload, '$.kind') = 'hint_burst'").fetchone()[0]  # fmt: skip
                assert flags >= 1, "the gaming signal is kept (never shown as an accusation)"
                await turn(c, sid, "Please just one more hint", "stuck")
                assert engine.state.rung == rung, "still paused until an attempt arrives"
                clock.advance(S.gaming_hint_gap_s + 1)  # the student takes a while over the attempt
                await turn(c, sid, wrong_option(record)["id"], "answer")
                engine = await turn(c, sid, "Now can I have a hint?", "stuck")
                assert engine.state.rung == rung + 1, "an attempt resumes the ladder at the next rung"

    return probe


DENSITY = "kc.phy.o.density.density_calculation"  # the floating KC's prerequisite


async def weaken(c: Any, r: Any, kc_id: str) -> None:
    """The prerequisite made weak: practice on it answered wrong until its P is under the detour bar (LRN-23)."""
    for _ in range(6):
        if kc_row(r, kc_id).get("p_mastery", 1.0) < S.detour_prereq_below:
            return
        made = await practice_set(c, [kc_id], 2)
        item = made["current_item"]
        while item is not None:
            record = item_record("phy", item["item_id"])
            key = record["parts"][0]["answer"]
            off = (mcq(next(o["id"] for o in key["options"] if not o["correct"])) if key["kind"] == "mcq"
                   else wrong(record))  # fmt: skip
            item = (await practise(c, made["set_id"], record["id"], off))["next_item"]
    raise AssertionError(f"{kc_id} stayed at P {kc_row(r, kc_id)}")


def _f3_detour(tmp_path: Path) -> Probe:
    """F3: failing twice on a KC whose prerequisite is weak: a short detour to the weakest prerequisite is offered,
    and after it the item resumes at the same step (LRN-23)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        async with core(tmp_path, provider=provider) as r:
            c, _ = await learner(r, "Kofi")
            await weaken(c, r, DENSITY)
            _, record, sid = await help_session(c, FLOAT)
            since = len(provider.requests)
            for _ in range(S.detour_failures - 1):  # the practice answer was the first failure on the KC
                await turn(c, sid, wrong_option(record)["id"], "answer")
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            state = r.core.sessions[sid].engine_state  # the open offers are the session engine's: no route shows them
            offered = [q for q in snap["open_requests"] if q["card"].get("card_type") in ("question", "confirm")
                       and state.offers.get(q["request_id"], {}).get("prerequisite_kc_id") == DENSITY]  # fmt: skip
            told = [x for x in coach_inputs(provider, since) if rule_action("detour_offer") in x]
            assert offered or told, "a prerequisite detour offered after the second failure"
            # Taken: the prerequisite's short items, then the item again at the same step with its board.
            step, board = state.step, [s.step_id for s in state.board.steps]
            card = offered[0]
            body = {"client_answer_id": new_id("cli"),
                    "answer": {"option_ids": [state.offers[card["request_id"]]["detour"]]}}  # fmt: skip
            await c.ok("POST", f"/v1/cards/{card['request_id']}/answer", body)
            await r.wait_idle(sid, 60)
            state = r.core.sessions[sid].engine_state
            assert state.detour is not None and state.detour["kc_id"] == DENSITY and state.detour_stack
            for _ in range(len(state.detour["items"])):
                assert state.problem is not None
                await turn(c, sid, typed_key(item_record("phy", state.problem.problem_id)), "answer")
                state = r.core.sessions[sid].engine_state
            assert state.detour is None and not state.detour_stack and state.practice is not None
            assert state.practice["item"]["id"] == record["id"] and state.step == step
            assert [s.step_id for s in state.board.steps] == board, "the item resumes with its board"

    return probe


def typed_key(record: dict[str, Any]) -> str:
    """An item's key as the student types it in the tutor: the right option's id, or the value with its unit."""
    key = record["parts"][0]["answer"]
    if key["kind"] == "mcq":
        return str(right_option(record)["id"])
    return f"{key['value']} {key.get('unit') or ''}".strip()


def _f4_stuck_cap(tmp_path: Path) -> Probe:
    """F4: the stuck cap on one KC: the KC is parked (`moved_on`), no further item on it is served, the question is
    saved for help, and the plan brings it back first on its revisit date (LRN-26)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            async with core(tmp_path, provider=provider) as r:
                c, _ = await learner(r, "Kofi")
                made = await practice_set(c, [FLOAT], S.stuck_cap_opportunities)
                current = made["current_item"]
                answered = []
                while current is not None and len(answered) < S.stuck_cap_opportunities:
                    record = item_record("phy", current["item_id"])
                    answered.append(record["id"])
                    current = (await practise(c, made["set_id"], record["id"],
                                              mcq(wrong_option(record)["id"])))["next_item"]  # fmt: skip
                assert len(answered) == S.stuck_cap_opportunities, answered
                assert kc_row(r, FLOAT)["status"] == "moved_on", kc_row(r, FLOAT)
                asked = {"client_set_id": new_id("cli"), "subject": "physics", "size": 1, "source": "topic",
                         "kc_ids": [FLOAT]}  # fmt: skip
                refused = await c.send("POST", "/v1/practice/sets", asked)
                assert refused.status_code != 200, "no further item on the parked KC"
                opened = await c.ok("POST", f"/v1/practice/sets/{made['set_id']}/help", {"item_id": answered[-1]})
                since = len(provider.requests)
                await turn(c, opened["session_id"], wrong_option(item_record("phy", answered[-1]))["id"], "answer")
                saved = await c.ok("GET", "/v1/saved-questions")
                assert saved, "the stuck question is kept for a person to help with (PED-24)"
                assert coach_inputs(provider, since), "the Coach moves the student on"
                plan = await c.ok("POST", "/v1/plans", {"client_request_id": new_id("cli")})
                assert all(FLOAT not in b.get("kc_ids", []) for b in plan["blocks"] if b["kind"] != "reflect"), plan[
                    "blocks"
                ]
                clock.days(S.stuck_revisit_days)
                later = await c.ok("POST", "/v1/plans", {"client_request_id": new_id("cli")})
                main = next(b for b in later["blocks"] if b["kind"] == "main")
                assert main["kc_ids"] == [FLOAT] and main.get("reason_code") == "revisit_moved_on", later["blocks"]

    return probe


# --- JRN-07: a daily plan to fix a weak topic ------------------------------------------------------------------------

SPEED = "kc.phy.o.motion.average_speed"
LESSON = "les.phy.o.motion.speed_and_acceleration"
SCRIPT = ("prior_knowledge", "idea", "worked_example", "guided_step", "quick_check", "common_mistakes", "exit_check")
ORDER = ("warmup", "main", "mixed", "reflect")
RECOGNITION = ("mcq", "mcq_diagnostic", "multi_select")  # choosing from shown options, not recalling
SUNDAY_KC = "kc.phy.o.measurement.si_prefixes"
SATURDAY_KCS = ("kc.phy.o.density.density_calculation", "kc.phy.o.measurement.scalars_and_vectors")
# Numeric-only KCs of the physics pack (recall items only), for a backlog of reviews.
BACKLOG = ("kc.phy.o.atom.atomic_structure", "kc.phy.o.circuits.mixed_circuits", "kc.phy.o.density.density_calculation",
           "kc.phy.o.electrical_quantities.current_and_charge", "kc.phy.o.electrical_quantities.resistance",
           "kc.phy.o.electrical_quantities.resistance_of_wires", "kc.phy.o.em_spectrum.em_wave_calculations",
           "kc.phy.o.energy.efficiency", "kc.phy.o.energy.energy_conversion", "kc.phy.o.energy.kinetic_energy",
           "kc.phy.o.energy.potential_energy", "kc.phy.o.forces.force_mass_acceleration",
           "kc.phy.o.mass_weight.weight_from_mass", "kc.phy.o.measurement.measuring_techniques",
           "kc.phy.o.measurement.resultant_vectors", "kc.phy.o.measurement.si_prefixes",
           "kc.phy.o.momentum.momentum_calculation", "kc.phy.o.motion.speed_unit_conversion",
           "kc.phy.o.radioactivity.half_life", "kc.phy.o.wave_properties.describing_waves")  # fmt: skip
FORBIDDEN = re.compile(r"\b(pin|quota|limit|remaining|left today|approv\w*|authori[sz]\w*)\b", re.IGNORECASE)


def correct(record: dict[str, Any]) -> dict[str, Any]:
    """The item's own key as the student's answer (read from the source record; replies never carry it)."""
    parts = []
    for part in record["parts"]:
        key = part["answer"]
        if key["kind"] == "numeric":
            parts.append({"part_id": part["id"], "kind": "numeric", "value": key["value"], "unit": key.get("unit")})
        elif key["kind"] == "mcq":
            parts.append({"part_id": part["id"], "kind": "mcq",
                          "option_id": next(o["id"] for o in key["options"] if o["correct"])})  # fmt: skip
        elif key["kind"] == "multi_select":
            parts.append({"part_id": part["id"], "kind": "multi_select",
                          "option_ids": [o["id"] for o in key["options"] if o["correct"]]})  # fmt: skip
        else:
            raise AssertionError(f"{record['id']}: no synthetic answer for a {key['kind']} part")
    return {"parts": parts}


def wrong(record: dict[str, Any]) -> dict[str, Any]:
    """A numeric answer far from the key, in the key's unit (no misconception signature fits it)."""
    part = record["parts"][0]
    assert part["answer"]["kind"] == "numeric", record["id"]
    value = str(Decimal(part["answer"]["value"]) * 7 + 3)
    return {"parts": [{"part_id": part["id"], "kind": "numeric", "value": value, "unit": part["answer"].get("unit")}]}


async def work(c: Any, kc_id: str, n: int, time_ms: int = 60_000) -> list[dict[str, Any]]:
    """`n` practice answers on one KC, all correct: the source records of the items served."""
    made = await practice_set(c, [kc_id], n)
    served, item = [], made["current_item"]
    while item is not None:
        record = item_record("phy", item["item_id"])
        served.append(record)
        marked = await practise(c, made["set_id"], record["id"], correct(record), time_ms)
        assert marked["verdict"] == "correct", (record["id"], marked)
        item = marked["next_item"]
    return served


def saturday_morning() -> float:
    """The next Saturday, 09:00 at the learner's local day boundary (the configured offset is UTC by default)."""
    today = datetime.fromtimestamp(time.time(), UTC).date()
    ahead = (5 - today.weekday()) % 7 or 7
    start = datetime.combine(today + timedelta(days=ahead), dtime(9), UTC).timestamp()
    return start - S.learner_day_offset_minutes * 60


def now_ms() -> int:
    return int(time.time() * 1000)


async def home(c: Any, **asked: Any) -> dict[str, Any]:
    """Home asks for the next activity (`POST /v1/plans`); the reply is a contract `PlanView`."""
    plan = await c.ok("POST", "/v1/plans", {"client_request_id": new_id("cli"), **asked})
    valid(PLAN_VIEW, plan)
    return plan


async def card(c: Any, plan: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    body = {"client_answer_id": new_id("cli"), "answer": answer}
    return await c.ok("POST", f"/v1/cards/{plan['request_id']}/answer", body)


def block(plan: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(b for b in plan["blocks"] if b["kind"] == kind)


def decisions(r: Any) -> list[dict[str, Any]]:
    rows = db(r).execute("SELECT payload FROM events WHERE type = 'plan_decision' ORDER BY seq").fetchall()
    return [json.loads(p) for (p,) in rows]


async def scheduled_check(c: Any, kc_id: str, wait_s: float = 10.0) -> dict[str, Any]:
    """The mastery check the core's assessment clock schedules once the KC is ready (ASM-14)."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        for found in await c.ok("GET", "/v1/assessments"):
            if found["kind"] == "mastery_check" and found["kc_id"] == kc_id:
                return dict(found)
        await asyncio.sleep(0.1)
    raise AssertionError(f"no mastery check was scheduled for {kc_id}")


async def check_answer(c: Any, check: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    body = {"client_answer_id": new_id("cli"), "item_id": check["current_item"]["item_id"], "action": "answer",
            "answer": answer}  # fmt: skip
    return await c.ok("POST", f"/v1/assessments/{check['assessment_id']}/answers", body)


async def reopen(r: Any, profile: str) -> Client:
    """The student taps their name again after the app restarted (no PIN, D86)."""
    return Client(r, await Api(r).token(profile))


async def finish(c: Any, plan: dict[str, Any], time_ms: int = 60_000) -> None:
    """Work through every unfinished practice block of a started plan with correct answers on its KCs."""
    for b in plan["blocks"]:
        if b["kind"] in ("warmup", "main", "mixed"):
            for n in range(b["done"], b["target"]):
                await work(c, b["kc_ids"][n % len(b["kc_ids"])], 1, time_ms)


def _plan_to_mastery(tmp_path: Path) -> Probe:
    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            clock.advance(saturday_morning() - time.time())
            r = await start(tmp_path, provider=provider)
            try:
                c, profile = await learner(r, "Ama")
                # Saturday and Sunday: checked work on three other KCs (their review cards start); Monday is missed.
                seen = {i["id"] for kc in SATURDAY_KCS for i in await work(c, kc, 2, 150_000)}
                clock.days(1)
                seen |= {i["id"] for i in await work(c, SUNDAY_KC, 2, 180_000)}
                clock.days(2)  # Tuesday morning
                with run.step(1):  # LRN-28, UXS-12: the next activity first, with an estimate, and an optional plan
                    assert (await c.get("/v1/plans/current")).json() is None, "nothing is planned until asked"
                    plan = await home(c)
                    kinds = [b["kind"] for b in plan["blocks"]]
                    assert plan["status"] == "proposed" and plan["next_block"] == 0 and not plan["keep_learning"]
                    assert kinds[0] == "warmup" and "main" in kinds and kinds == sorted(kinds, key=ORDER.index), kinds
                    assert all(b["minutes"] >= 1 for b in plan["blocks"])
                    assert plan["minutes"] == sum(b["minutes"] for b in plan["blocks"]), "an estimate, not a budget"
                    assert plan["card"]["card_type"] == "plan" and {"start", "change"} <= set(plan["card"]["actions"])
                    first = plan["card"]["items"][0]["text"]
                    assert str(plan["blocks"][0]["minutes"]) in first and "min" in first, first
                with run.step(2):  # LRN-31, LRN-32: skip, shorten or choose the topic; then start
                    assert (await card(c, plan, {"skipped": True}))["status"] == "accepted"
                    other = await home(c)  # another suggestion whenever asked, nothing locked
                    short = await c.ok("POST", f"/v1/plans/{other['plan_id']}/change", {"shorten": True})
                    valid(PLAN_VIEW, short)
                    assert len(short["blocks"]) == 1 and short["minutes"] == short["blocks"][0]["minutes"]
                    assert (await card(c, short, {"skipped": True}))["status"] == "accepted"
                    offered = await home(c)
                    assert len(offered["alternatives"]) == S.planner_alternatives
                    chosen = await c.ok("POST", f"/v1/plans/{offered['plan_id']}/change", {"kc_id": SPEED})
                    valid(PLAN_VIEW, chosen)
                    assert block(chosen, "main")["kc_ids"] == [SPEED] and block(chosen, "warmup")
                    assert (
                        "lesson" in chosen["card"]["items"][[b["kind"] for b in chosen["blocks"]].index("main")]["text"]
                    ), "a KC not started yet begins with its lesson"
                    assert (await card(c, chosen, {"action": "start"}))["status"] == "accepted"
                    current = await c.ok("GET", "/v1/plans/current")
                    assert current["plan_id"] == chosen["plan_id"] and current["status"] == "started"
                    made = [(d["plan_id"], d["decision"]) for d in decisions(r)]
                    assert made == [(plan["plan_id"], "not_today"), (other["plan_id"], "change"),
                                    (short["plan_id"], "not_today"), (offered["plan_id"], "change"),
                                    (chosen["plan_id"], "start")], made  # fmt: skip
                with run.step(3):  # LRN-13, LRN-14: the due reviews, as unseen recall items, each rated
                    warm = block(current, "warmup")
                    due = {k for (k,) in db(r).execute("SELECT kc_id FROM review_cards WHERE due_at <= ?",
                                                       (now_ms(),))}  # fmt: skip
                    assert warm["kc_ids"] and set(warm["kc_ids"]) <= due, (warm, due)
                    assert len(warm["kc_ids"]) == min(len(due), S.review_cap_items)
                    before = dict(db(r).execute("SELECT kc_id, due_at FROM review_cards").fetchall())
                    reviewed = [i for kc in warm["kc_ids"] for i in await work(c, kc, 1)]
                    assert not {i["id"] for i in reviewed} & seen, "a review is an unseen variant, never the same item"
                    assert all(i["type"] not in RECOGNITION for i in reviewed), [i["type"] for i in reviewed]
                    after = dict(db(r).execute("SELECT kc_id, due_at FROM review_cards").fetchall())
                    assert all(after[k] > max(before[k], now_ms()) for k in warm["kc_ids"]), "rated Good: due later"
                    current = await c.ok("GET", "/v1/plans/current")
                    assert (
                        block(current, "warmup")["status"] == "done"
                        and current["next_block"] == block(current, "main")["index"]
                    )
                with run.step(4):  # CUR-11, UXS-23, AGT-22: the lesson player, then the lesson in the tutor
                    gate = (await c.get(f"/v1/lessons/{LESSON}/probe")).json()
                    if gate:  # the first lesson's entry probe (ASM-13)
                        record = item_record("phy", gate["current_item"]["item_id"])
                        await c.ok("POST", f"/v1/probes/{gate['probe_id']}/answers",
                                   {"option_id": right_option(record)["id"]})  # fmt: skip
                    tutored = {"client_session_id": new_id("cli"), "mode": "guided", "subject": "physics",
                               "level": "O", "origin": {"kind": "lesson", "ref": LESSON}}  # fmt: skip
                    sid = (await c.ok("POST", "/v1/sessions", tutored))["session_id"]
                    engine = await turn(c, sid, "next", "next_step")
                    assert engine.lesson.index == 0 and engine.state.practice is not None, "the check opens its item"
                    engine = await turn(c, sid, "next", "next_step")
                    assert engine.lesson.index == 1, "the tutor plays the lesson's blocks in order (AGT-22)"
                    lesson = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
                    assert lesson["position"]["block_index"] == 1, "the block index is kept"
                    types = [b["type"] for b in lesson["blocks"]]
                    assert [t for t in types if t in SCRIPT] == list(SCRIPT), types
                    blocks = {b["type"]: b for b in lesson["blocks"]}
                    example = blocks["worked_example"]["worked_example"]
                    assert example["steps"] and all(s["reason"] for s in example["steps"])
                    assert all(m["name"] and m["fix"] for m in blocks["common_mistakes"]["mistakes"])
                    shown = len(example["steps"]) - len(example["faded_steps"])
                    for index, b in enumerate(lesson["blocks"]):
                        for item in b.get("items", []):
                            key = correct(item_record("phy", item["item_id"]))
                            body = {"client_attempt_id": new_id("cli"), "item_id": item["item_id"], "answer": key,
                                    "time_ms": 60_000}  # fmt: skip
                            marked = await c.ok("POST", f"/v1/lessons/{LESSON}/checks", body, "LessonCheckResult")
                            assert marked["verdict"] == "correct", marked
                        await c.ok("PUT", f"/v1/lessons/{LESSON}/position",
                                   {"block_index": index, "lesson_version": lesson["version"]})  # fmt: skip
                    again = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
                    assert again["position"]["block_index"] == len(lesson["blocks"]) - 1, "the position is saved"
                with run.step(5):  # LRN-16, LRN-17: practice near the target success; examples fade with mastery
                    desk = r.runtime.assessments()
                    for _ in range(15):
                        if kc_row(r, SPEED)["status"] == "ready_to_check":
                            break
                        made = await practice_set(c, [SPEED], 1)
                        for decision in [d for d in desk.policy_decisions if d.policy == "difficulty_targeting"]:
                            target, (low, high) = decision.inputs["target"], decision.inputs["band"]
                            assert target == S.adapt_target and (low, high) == tuple(S.adapt_band)
                            inside = [p for _, p, _, _ in decision.inputs["candidates"] if low <= p <= high]
                            if inside:
                                picked = decision.output["p_hat"]
                                assert (
                                    low <= picked <= high
                                    and abs(picked - target) <= min(abs(p - target) for p in inside) + 1e-12
                                ), decision.entry()
                        item = made["current_item"]
                        while item is not None:
                            record = item_record("phy", item["item_id"])
                            item = (await practise(c, made["set_id"], record["id"], correct(record)))["next_item"]
                    assert kc_row(r, SPEED)["status"] == "ready_to_check", kc_row(r, SPEED)
                    faded = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
                    example = next(b for b in faded["blocks"] if b["type"] == "worked_example")["worked_example"]
                    assert len(example["steps"]) - len(example["faded_steps"]) < shown, "the example fades (LRN-17)"
                with run.step(6):  # ASM-14, LRN-09: three varied unseen items, no hints, one a day later
                    check = await scheduled_check(c, SPEED)
                    if check["current_item"] is None:
                        check = await c.ok("GET", f"/v1/assessments/{check['assessment_id']}")
                    asking = {**tutored, "client_session_id": new_id("cli"), "origin": {"kind": "ask", "ref": None}}
                    locked = await c.send("POST", "/v1/sessions", asking)
                    assert locked.status_code == 423, "no tutor (and so no hint) while a check item is open"
                    served = []
                    first_served = now_ms()
                    for _ in range(S.mastery_check_items - 1):
                        served.append(item_record("phy", check["current_item"]["item_id"]))
                        check = await check_answer(c, check, correct(served[-1]))
                    assert check["state"] == "waiting" and check["current_item"] is None, check
                    spacing = S.mastery_check_min_spacing_hours * 3_600_000
                    waits = datetime.fromisoformat(check["available_at"].replace("Z", "+00:00")).timestamp() * 1000
                    assert waits >= first_served + spacing - 1000, (check["available_at"], first_served)
                    clock.advance(S.mastery_check_min_spacing_hours * 3600)  # Wednesday morning
                    check = await c.ok("GET", f"/v1/assessments/{check['assessment_id']}")
                    served.append(item_record("phy", check["current_item"]["item_id"]))
                    check = await check_answer(c, check, correct(served[-1]))
                    assert check["state"] == "completed" and kc_row(r, SPEED)["status"] == "mastered", check
                    surfaces = {i.get("template_id") or i["stem"] for i in served}
                    assert len(surfaces) == S.mastery_check_items, "varied in surface"
                with run.step(7):  # UXS-24, LRN-31, LRN-33, LRN-34: stop, restart, resume; bars and streak
                    today = await home(c)
                    assert (await card(c, today, {"action": "start"}))["status"] == "accepted"
                    opening = today["blocks"][0]
                    assert opening["target"] >= 2 and opening["kc_ids"], opening
                    await work(c, opening["kc_ids"][0], 1, 6 * 60_000)  # one item, then the student stops
                    r = await restart(r, provider=provider)  # the app is closed and opened again
                    c = await reopen(r, profile)
                    resumed = await c.ok("GET", "/v1/plans/current")
                    valid(PLAN_VIEW, resumed)
                    assert resumed["plan_id"] == today["plan_id"] and resumed["status"] == "started"
                    assert resumed["blocks"][0]["done"] == 1 and resumed["blocks"][0]["status"] == "in_progress"
                    assert resumed["next_block"] == opening["index"], "resumes at the unfinished activity"
                    progress = await c.ok("GET", "/v1/progress")
                    valid(PROGRESS_VIEW, progress)
                    states = {k["kc_id"]: k for t in progress["subjects"][0]["topics"] for k in t["kcs"]}
                    assert states[SPEED]["band"] == "secure" and SPEED in progress["moved_today"]
                    streak = progress["streak"]
                    assert streak == {"days": 4, "freezes_left": 0, "counted_today": True}, streak
                    monday = local_date(r.runtime.mastery_params().local_day(now_ms()) - 2)
                    frozen = db(r).execute("SELECT freeze_used FROM engagement_daily WHERE day = ?",
                                           (monday,)).fetchone()  # fmt: skip
                    assert frozen == (1,), "the missed Monday was covered by the week's freeze"
                with run.step(8):  # LRN-28, LRN-31, LRN-32, UXS-12: Keep learning, same day, offline, no limit
                    await finish(c, resumed)
                    done = await c.ok("GET", "/v1/plans/current")
                    assert done["status"] == "done", done
                    keep = await home(c)
                    assert keep["keep_learning"] and keep["card"]["title"] == "Keep learning"
                    assert keep["date"] == done["date"] and keep["plan_id"] != done["plan_id"]
                    assert (await card(c, keep, {"action": "start"}))["status"] == "accepted"
                    current = await c.ok("GET", "/v1/plans/current")
                    assert current["plan_id"] == keep["plan_id"] and current["status"] == "started"
                    more = await home(c)
                    for reply in (keep, current, more):
                        assert not FORBIDDEN.search(json.dumps(reply["card"])), reply["card"]
                    assert more["status"] == "proposed", "another suggestion still, with no daily cap"
                    run.note("offline: every online feature off, the runner's egress monitor saw nothing")
            finally:
                await stop_core(r)

    return probe


def _f1_backlog(tmp_path: Path) -> Probe:
    """F1: after missed days the first suggestion takes a capped share of the overdue reviews; accepting each day's
    suggestion serves the rest within the spread window; asking for more serves them at once (LRN-29)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            async with core(tmp_path, provider=provider) as r:
                c, _ = await learner(r, "Ama")
                for kc in BACKLOG:
                    await work(c, kc, 1, 30_000)
                clock.days(12)  # ten and more missed days
                overdue = {k for (k,) in db(r).execute("SELECT kc_id FROM review_cards WHERE due_at <= ?",
                                                       (now_ms(),))}  # fmt: skip
                assert len(overdue) > S.review_cap_items, overdue
                first = await home(c)
                warm = block(first, "warmup")
                assert len(warm["kc_ids"]) <= S.review_cap_items
                assert warm["minutes"] <= S.review_cap_share * first["minutes"] + 1e-9, first["blocks"]
                shown = re.sub(r"about \d+ min", "", json.dumps(first["card"]))  # durations are estimates
                for hidden in {len(overdue) - len(warm["kc_ids"]), len(overdue)}:
                    assert not re.search(rf"\b{hidden}\b", shown), ("the backlog count is never shown", shown)
                everything = await home(c, all_reviews=True)
                assert set(block(everything, "warmup")["kc_ids"]) == overdue, "more reviews on request, uncapped"
                served: set[str] = set()
                for _ in range(S.review_backlog_days):
                    plan = await home(c)
                    warm = next((b for b in plan["blocks"] if b["kind"] == "warmup"), None)
                    if warm is not None:
                        await card(c, plan, {"action": "start"})
                        for kc in warm["kc_ids"]:
                            await work(c, kc, 1, 20_000)
                            served.add(kc)
                    if overdue <= served:
                        break
                    clock.days(1)
                assert overdue <= served, sorted(overdue - served)

    return probe


def _f2_failed_check(tmp_path: Path) -> Probe:
    """F2: a failed mastery check lowers the estimate, returns the KC to learning with a retry no sooner than the
    configured days, and the KC is back in the plan (ASM-14)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            async with core(tmp_path, provider=provider) as r:
                c, _ = await learner(r, "Ama")
                for _ in range(12):
                    if kc_row(r, SPEED)["status"] == "ready_to_check":
                        break
                    await work(c, SPEED, 3)
                assert kc_row(r, SPEED)["status"] == "ready_to_check"
                check = await scheduled_check(c, SPEED)
                if check["current_item"] is None:
                    check = await c.ok("GET", f"/v1/assessments/{check['assessment_id']}")
                estimate = kc_row(r, SPEED)["p_mastery"]
                failed = await check_answer(c, check, wrong(item_record("phy", check["current_item"]["item_id"])))
                assert failed["state"] == "failed", failed
                retry = datetime.fromisoformat(failed["retry_at"].replace("Z", "+00:00")).timestamp() * 1000
                assert retry >= now_ms() + S.mastery_check_retry_days * 86_400_000 - 5_000, failed["retry_at"]
                row = kc_row(r, SPEED)
                assert row["status"] == "learning" and row["p_mastery"] < estimate, (row, estimate)
                early = await c.send("POST", "/v1/assessments", {"kind": "mastery_check", "subject": "physics",
                                                                  "kc_id": SPEED})  # fmt: skip
                assert early.status_code == 422 and "retry_not_due" in early.text, early.text
                back = None
                for day in range(math.ceil(S.mastery_check_retry_days) + 1):  # by the retry date at the latest
                    plan = await home(c)
                    work_kcs = {k for b in [*plan["blocks"], *plan["alternatives"]] if b["kind"] != "reflect"
                                for k in b["kc_ids"]}  # fmt: skip
                    if SPEED in work_kcs:
                        back = day
                        break
                    clock.days(1)
                assert back is not None, "the KC is back in the plan by its retry date"
                run.note(f"back in the plan after {back} day(s)")
                clock.advance(max(0, retry - now_ms()) / 1000 + 1)
                again = await c.ok("POST", "/v1/assessments", {"kind": "mastery_check", "subject": "physics",
                                                                "kc_id": SPEED})  # fmt: skip
                assert again["kc_id"] == SPEED and again["state"] != "failed", "a new check from the retry date"

    return probe


def _f3_late_evening(tmp_path: Path) -> Probe:
    """F3: at 22:30 the tutor and the planner answer as at any hour (no study hours, D53), and no reminder is ever
    scheduled inside the quiet hours (LRN-28, LRN-35)."""

    async def probe(run: Run) -> None:
        provider = scripted(replies())
        with Clock() as clock:
            late = saturday_morning() + (22.5 - 9) * 3600
            clock.advance(late - time.time())
            async with core(tmp_path, provider=provider) as r:
                c, profile = await learner(r, "Ama")
                await c.ok("PATCH", f"/v1/profiles/{profile}/settings", {"notifications": True})
                _, _, sid = await help_session(c, FLOAT)
                await turn(c, sid, "Can you help me with this one?", "stuck")
                snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
                assert tutor_text(snap, tutor_messages(snap)[-1]), "the tutor answers late in the evening"
                plan = await home(c)
                assert plan["status"] == "proposed" and (await card(c, plan, {"action": "start"}))["status"] == (
                    "accepted"
                )
                desk = r.runtime.planner()  # the reminder slot has no route: the plan desk decides it
                start, end = (h * 60 for h in S.notify_quiet_hours)
                local = int((time.time() // 60 + S.learner_day_offset_minutes) % (24 * 60))
                assert local >= start, "the run is inside the evening's quiet hours"
                for preferred in range(0, 24 * 60, 15):
                    assert desk.next_reminder(local, 0, preferred_minute=preferred) is None, preferred
                for minute in range(0, 24 * 60, 5):
                    for preferred in range(0, 24 * 60, 30):
                        slot = desk.next_reminder(minute, 0, preferred_minute=preferred)
                        assert slot is None or end <= slot < start, (minute, preferred, slot)

    return probe


# --- the cases (replayed by prd03_core_journeys_offline) and the tests -----------------------------------------------

CASES: dict[tuple[str, str], Callable[[Path], Probe]] = {
    ("JRN-05", "main"): _stuck,
    ("JRN-05", "F1"): _f1_offer,
    ("JRN-05", "F2"): _f2_hint_burst,
    ("JRN-05", "F3"): _f3_detour,
    ("JRN-05", "F4"): _f4_stuck_cap,
    ("JRN-07", "main"): _plan_to_mastery,
    ("JRN-07", "F1"): _f1_backlog,
    ("JRN-07", "F2"): _f2_failed_check,
    ("JRN-07", "F3"): _f3_late_evening,
}
GAPS: dict[tuple[str, str], str] = {}


def cases(journey: str) -> list[Any]:
    """The journey's failure branches, each a case; a branch the product cannot pass yet is a strict xfail."""
    return [pytest.param(b, marks=pytest.mark.xfail(strict=True, reason=GAPS[(journey, b)]))
            if (journey, b) in GAPS else b for b in branches(journey)]  # fmt: skip


def jrn05_stuck_in_practice(tmp_path: Path) -> None:
    play("JRN-05", "main", CASES[("JRN-05", "main")](tmp_path))


@pytest.mark.parametrize("branch", cases("JRN-05"))
def jrn05_failure_branches(branch: str, tmp_path: Path) -> None:
    play("JRN-05", branch, CASES[("JRN-05", branch)](tmp_path))


def jrn07_plan_to_mastery(tmp_path: Path) -> None:
    """Every step must pass, the worked example fading with mastery at step 5 included (LRN-17)."""
    play("JRN-07", "main", CASES[("JRN-07", "main")](tmp_path))


@pytest.mark.parametrize("branch", cases("JRN-07"))
def jrn07_failure_branches(branch: str, tmp_path: Path) -> None:
    play("JRN-07", branch, CASES[("JRN-07", branch)](tmp_path))
