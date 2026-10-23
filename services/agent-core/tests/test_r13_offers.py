"""LRN-20 and LRN-23 on the live turn loop (the engine's own offers, `agent_core.engine.offers`), over the core's local
API as the client drives it: the hint offer after wrong answers in a row (one quiet line, never a hint and never a
card, D112; the hint the student then pulls has trigger `offer_accepted`), once per step across both triggers, the
prerequisite detour declined (logged and not offered again; JRN-05 F3 plays it accepted, to the problem back at the
same step with its board), the preference that switches the hint offer off, and the idle trigger the client reports
(`POST /v1/sessions/{session_id}/idle`, D104). Learners and replies are synthetic; items are the repository's own
physics sources."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.engine.events import new_id
from journey_harness import SETTINGS, core, learner, scripted, turn
from test_m13g_learn import Client
from test_m25a_practice_and_plan import DENSITY, FLOAT, help_session, replies, weaken, wrong_option

S = SETTINGS


def offer_cards(snap: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for q in snap["open_requests"] if q["card"].get("card_type") == "question"]


def hint_offers(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """The quiet hint-offer lines in the session's snapshot (LRN-20, D112): `notice` parts with code `hint_offer`."""
    return [p for p in snap["parts"].values() if p["kind"] == "notice" and p["notice"]["code"] == "hint_offer"]


def hint_options(snap: dict[str, Any]) -> list[str]:
    return [o["label"] for q in offer_cards(snap) for o in q["card"]["options"] if "hint" in o["label"].lower()]


async def answer(c: Client, request_id: str, option_id: str) -> None:
    body = {"client_answer_id": new_id("cli"), "answer": {"option_ids": [option_id]}}
    await c.ok("POST", f"/v1/cards/{request_id}/answer", body)


async def idle(r: Any, sid: str) -> None:
    entry = r.core.sessions[sid]
    while entry.task is not None and not entry.task.done():
        await asyncio.sleep(0.02)
    await r.wait_idle(sid, 60)


def option(card: dict[str, Any], words: str) -> str:
    return next(o["id"] for o in card["options"] if words in o["label"])


def hint_events(r: Any) -> list[dict[str, Any]]:
    rows = r.runtime.learner.conn.execute("SELECT payload FROM events WHERE type = 'hint' ORDER BY seq").fetchall()
    return [json.loads(p) for (p,) in rows]


def test_lrn20_live_offer_once_and_accepted(tmp_path: Path) -> None:
    """Two wrong answers in a row on the step: one quiet hint-offer line (a `hint_offer` notice, D112), no card to
    answer and no hint shown; the hint the student then pulls (the chip, intent `stuck`) is recorded with trigger
    `offer_accepted`; a third wrong answer on the same step brings no second offer."""

    async def scenario() -> None:
        async with core(tmp_path, provider=scripted(replies())) as r:
            c, _ = await learner(r, "Kofi")
            _, record, sid = await help_session(c, FLOAT)
            await turn(c, sid, wrong_option(record)["id"], "answer")
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            (line,) = hint_offers(snap)
            assert line["notice"]["message_key"] == "notice.hint_offer" and line["notice"]["action"] is None
            assert not hint_options(snap), "the offer is not a card to answer"
            state = r.core.sessions[sid].engine_state
            assert state.offered_steps == [state.step] and state.rung == 0, "offered, never shown"
            await turn(c, sid, "I'm stuck", "stuck")
            assert hint_events(r)[-1]["trigger"] == "offer_accepted"
            first = len(hint_events(r))
            await turn(c, sid, "I'm stuck", "stuck")
            assert all(h["trigger"] == "student_request" for h in hint_events(r)[first:]), "the offer is answered once"
            await turn(c, sid, wrong_option(record)["id"], "answer")
            assert len(hint_offers(await c.ok("GET", f"/v1/sessions/{sid}/snapshot"))) == 1, "once per step"

    asyncio.run(scenario())


def test_lrn20_live_offer_suppressed_by_preference(tmp_path: Path) -> None:
    """With `unprompted_help` switched off, no hint is offered after the wrong answers."""

    async def scenario() -> None:
        async with core(tmp_path, provider=scripted(replies())) as r:
            c, _ = await learner(r, "Kofi")
            conn = r.runtime.learner.conn
            conn.execute("INSERT OR REPLACE INTO preferences (key, value, confidence, last_event_seq)"
                         " VALUES ('unprompted_help', 'false', 1.0, 0)")  # fmt: skip
            _, record, sid = await help_session(c, FLOAT)
            await turn(c, sid, wrong_option(record)["id"], "answer")
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            assert not hint_offers(snap) and not hint_options(snap)

    asyncio.run(scenario())


def test_lrn20_idle_report_opens_the_offer_once(tmp_path: Path) -> None:
    """LRN-20, API 1.10 (D104): the client's idle report answers 204; a step idle past `offer_idle_s` with the window
    focused brings the same quiet hint-offer line, from an engine-written turn with no model call, at most once per
    step; an unfocused or short idle, and a second report on the step, bring nothing."""
    provider = scripted(replies())

    async def scenario() -> None:
        async with core(tmp_path, provider=provider) as r:
            c, _ = await learner(r, "Kofi")
            _, _, sid = await help_session(c, FLOAT)
            await idle(r, sid)
            state = r.core.sessions[sid].engine_state
            assert state.problem is not None and state.step not in state.offered_steps
            calls = len(provider.requests)
            long_ms = int(S.offer_idle_s * 1000)
            for body in ({"idle_ms": long_ms, "focused": False}, {"idle_ms": long_ms // 2, "focused": True}):
                reply = await c.send("POST", f"/v1/sessions/{sid}/idle", body)
                assert reply.status_code == 204 and not reply.content, reply.text
                await idle(r, sid)
            assert not hint_offers(await c.ok("GET", f"/v1/sessions/{sid}/snapshot")), "nothing offered"
            reply = await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": long_ms, "focused": True})
            assert reply.status_code == 204, reply.text
            await idle(r, sid)
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            assert len(hint_offers(snap)) == 1 and not hint_options(snap) and not offer_cards(snap)
            assert state.offered_steps == [state.step] and len(provider.requests) == calls, "no model call"
            await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": long_ms, "focused": True})
            await idle(r, sid)
            assert len(hint_offers(await c.ok("GET", f"/v1/sessions/{sid}/snapshot"))) == 1, "once per step"
            refused = await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": -1, "focused": True})
            assert refused.status_code == 422

    asyncio.run(scenario())


def test_lrn20_offer_once_per_step_across_triggers(tmp_path: Path) -> None:
    """The 2026-10-19 report of the offer shown twice in a row: the idle offer, the wrong answers that follow and a
    later idle report on the same step bring one offer between them, and nothing about it waits for an answer, so
    the conversation and the question dock above the composer never both show it (the dock mirrors open question
    cards, UIA; the offer card used to be one)."""

    async def scenario() -> None:
        async with core(tmp_path, provider=scripted(replies())) as r:
            c, _ = await learner(r, "Kofi")
            _, record, sid = await help_session(c, FLOAT)
            await idle(r, sid)
            long_ms = int(S.offer_idle_s * 1000)
            await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": long_ms, "focused": True})
            await idle(r, sid)
            for _ in range(2):
                await turn(c, sid, wrong_option(record)["id"], "answer")
                await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": long_ms, "focused": True})
                await idle(r, sid)
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            assert len(hint_offers(snap)) == 1, hint_offers(snap)
            assert not snap["open_requests"], "no offer left open for the dock to mirror"

    asyncio.run(scenario())


def test_lrn23_live_detour_declined_not_offered_again(tmp_path: Path) -> None:
    """A declined detour is not offered again for that KC in the session."""

    async def scenario() -> None:
        async with core(tmp_path, provider=scripted(replies())) as r:
            c, _ = await learner(r, "Kofi")
            await weaken(c, r, DENSITY)
            _, record, sid = await help_session(c, FLOAT)
            await turn(c, sid, wrong_option(record)["id"], "answer")
            (card,) = offer_cards(await c.ok("GET", f"/v1/sessions/{sid}/snapshot"))
            await answer(c, card["request_id"], option(card["card"], "Not now"))
            state = r.core.sessions[sid].engine_state
            assert state.detour_declined == [FLOAT] and state.detour is None
            await turn(c, sid, wrong_option(record)["id"], "answer")
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            later = [o["label"] for q in offer_cards(snap) for o in q["card"]["options"]]
            assert not any("earlier idea" in label for label in later), later

    asyncio.run(scenario())


def test_d112_reply_above_an_idle_offer_can_be_saved(tmp_path: Path) -> None:
    """D112 follow-up (UXS-42): the idle offer is an engine-written turn holding only the quiet line, not a reply, so
    the tutor's reply above it can still be saved for later."""
    provider = scripted(replies())

    async def scenario() -> None:
        async with core(tmp_path, provider=provider) as r:
            c, _ = await learner(r, "Kofi")
            _, _, sid = await help_session(c, FLOAT)
            await turn(c, sid, "I'm stuck", "stuck")  # a reply from the tutor
            await idle(r, sid)
            await c.send("POST", f"/v1/sessions/{sid}/idle", {"idle_ms": int(S.offer_idle_s * 1000), "focused": True})
            await idle(r, sid)
            snap = await c.ok("GET", f"/v1/sessions/{sid}/snapshot")
            assert len(hint_offers(snap)) == 1
            tutor = [m for m in snap["messages"] if m["role"] == "tutor"]
            assert not tutor[-1]["part_ids"], "the newest tutor turn is the offer alone"
            reply = next(m for m in reversed(tutor) if m["part_ids"])
            saved = await c.send("POST", "/v1/saved-questions", {"session_id": sid, "turn_id": reply["turn_id"]})
            assert saved.status_code == 200, saved.text

    asyncio.run(scenario())
