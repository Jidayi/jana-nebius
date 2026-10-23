"""The hand-off's first-session interview (UXS-10, JRN-03 step 3; TOL-20, LRN-04) over the core's local API: one
question per card, answered in order only, merged into the profile's goals by schema with the student's own words
redacted (PRV-20) and screened like a note (STU-11), a low confidence adding its goal, and skipping leaving the goals
empty. Every learner and answer is synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.contracts import errors
from agent_core.learner.profile import stored_profile
from agent_core.providers.scripted import ScriptedProvider
from api_harness import cli
from journey_harness import core, learner, scripted


def goals(r: Any) -> list[str] | None:
    found = stored_profile(r.runtime.learner.conn).get("goals")
    return None if found is None else list(found)


async def say(c: Any, question: str, **answer: Any) -> Any:
    return await c.send("POST", f"/v1/interview/{question}/answer", {"client_answer_id": cli(), "answer": answer})


def test_uxs10_interview_merges_goals_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with core(tmp_path, provider=scripted({})) as r:
            c, _ = await learner(r, "Esi")
            view = await c.ok("GET", "/v1/interview")
            assert (view["total"], view["answered"], view["done"]) == (2, 0, False)
            first = view["question"]
            assert first["question_id"] == "goals" and first["card"]["multi"] and first["card"]["allow_free_text"]
            early = await say(c, "confidence", option_ids=["opt_0"])
            assert early.status_code == 422 and early.json()["error"]["details"]["reason"] == "not_current"
            options = [o["id"] for o in first["card"]["options"]]
            reply = await say(c, "goals", option_ids=options[:2], text="Get better at moles, call me on 0244 123 4567")
            assert reply.status_code == 200, reply.text
            kept = goals(r)
            assert kept is not None and len(kept) == 3 and "0244" not in json.dumps(kept), kept
            second = reply.json()["question"]
            assert second["question_id"] == "confidence" and not second["card"]["multi"]
            low = second["card"]["options"][2]["id"]  # "Not very confident"
            done = await say(c, "confidence", option_ids=[low])
            assert done.json()["done"] and done.json()["question"] is None
            assert len(goals(r) or []) == 4, "a low confidence adds its goal"
            events = r.runtime.learner.conn.execute(
                "SELECT payload FROM events WHERE type = 'profile_updated'").fetchall()  # fmt: skip
            assert events and all(json.loads(p) == {"changed_fields": ["goals"]} for (p,) in events), "names only"
            assert (await c.ok("GET", "/v1/interview"))["done"]

    asyncio.run(scenario())


def test_uxs10_interview_skipped_and_screened(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with core(tmp_path, provider=scripted({})) as r:
            c, _ = await learner(r, "Esi")
            refused = await say(c, "goals", text="How to make a bomb at home")
            assert refused.status_code == 422 and refused.json()["error"]["details"]["reason"] == "safety_template"
            assert goals(r) is None, "nothing kept"
            assert (await say(c, "goals", skipped=True)).status_code == 200
            assert goals(r) == []
            assert (await say(c, "confidence", skipped=True)).json()["done"]
            assert goals(r) == []

    asyncio.run(scenario())


def uxs10_scripted_interview_no_model(tmp_path: Path) -> None:
    """UXS-10, D104: with no tutor model installed the hand-off still shows the two scripted questions one at a time,
    each skippable, in the InterviewView shape, and the answers land in the profile's goals with no model call."""
    no_model = ScriptedProvider({}, kind="local", installed_models=[])

    async def scenario() -> None:
        async with core(tmp_path, provider=no_model) as r:
            c, _ = await learner(r, "Esi")
            view = await c.ok("GET", "/v1/interview")
            assert not errors("api/commands#/$defs/InterviewView", view)
            assert (view["total"], view["answered"], view["question"]["question_id"]) == (2, 0, "goals")
            first = view["question"]["card"]["options"][0]["id"]
            after = (await say(c, "goals", option_ids=[first])).json()
            assert not errors("api/commands#/$defs/InterviewView", after)
            assert (after["answered"], after["question"]["question_id"]) == (1, "confidence"), "one card at a time"
            done = (await say(c, "confidence", skipped=True)).json()
            assert not errors("api/commands#/$defs/InterviewView", done)
            assert done["done"] and done["question"] is None
            assert len(goals(r) or []) == 1, "the chosen goal is in the profile; the skipped question added nothing"
            assert no_model.requests == [], "no model was called"

    asyncio.run(scenario())
