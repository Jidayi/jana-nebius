"""UXS-51 worked-solution search on the core, with synthetic items only: the search and the direct item link (an
item's solution on request) leave out the mock-reserved pool and every item of an active protected assessment before
anything is matched or shown; a typed query is answered offline with no model; a match's full worked solution is there
on request with no attempt. Also PRM-03: the open profile's chosen tutor name fills the soul's placeholder."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.security import LaunchSecret
from agent_core.config import Settings
from agent_core.contracts import validator
from agent_core.engine.assessment.service import AssessmentDesk, Refused
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sessions import SessionStore
from agent_core.store.sqlite import open_database

KC = "kc.mth.o.number.add"
TOPIC = "cur.mth.o.number"
WORKED = "wex.mth.o.number.add_carry"
SETTINGS = Settings()
VIEW = validator("api/commands#/$defs/WorkedExampleView")
ITEMS = validator("api/commands#/$defs/PracticeItemList")


def item(n: int, stem: str, *, steps: bool = True, worked: bool = False) -> dict[str, Any]:
    solution: dict[str, Any] = {"worked_example_id": WORKED} if worked else {}
    if steps and not worked:
        solution["steps"] = [
            {"n": 1, "latex": f"{n} + {n}", "reason": "Write the sum", "check_id": "chk_fixture"},
            {"n": 2, "latex": f"= {2 * n}", "reason": "Add", "check_id": "chk_fixture"},
        ]
    return {
        "id": f"itm.mth.o.number.{n:04d}",
        "type": "numeric",
        "stem": stem,
        "kc_ids": [KC],
        "template_id": f"template{n}",
        "review": {"status": "published"},
        "difficulty": {"prior": 0},
        "solution": solution,
        "parts": [
            {
                "id": "a",
                "prompt": "Give the total",
                "marks": 1,
                "answer": {
                    "kind": "numeric",
                    "value": 2 * n,
                    "unit": None,
                    "unit_policy": "none",
                    "check_id": "chk_key",
                },
            }
        ],
    }


# Items 1 and 2 are the mock paper's (reserved), item 3 is held for a mastery check below; every stem names the same
# synthetic topic word, so a search for it would reach all of them without the filter.
BANK = [item(n, f"Synthetic carrying sum {n}: add the two numbers") for n in range(1, 13)]
BANK.append(item(20, "Synthetic carrying sum with a worked example", worked=True))
EXAMPLE = {
    "id": WORKED,
    "kc_ids": [KC],
    "problem": "Synthetic worked example",
    "steps": [
        {"n": 1, "latex": "18 + 25", "reason": "Line up the digits", "check_id": "chk_fixture"},
        {"n": 2, "latex": "= 43", "reason": "Carry the ten", "check_id": "chk_fixture"},
    ],
    "final_answer": {"latex": "43", "check_id": "chk_fixture"},
    "fading_order": [2],
    "version": "1.0.0",
    "review": {"status": "published"},
}
PAPER = {
    "id": "mock.mth.o.fixture",
    "subject": "mth",
    "level": "o",
    "title": "Fixture",
    "duration_minutes": 60,
    "total_marks": 2,
    "calculator": False,
    "blueprint": {"topic_weights": {TOPIC: 1}},
    "sections": [
        {
            "section_id": "s1",
            "title": "One",
            "item_types": ["numeric"],
            "marks": 2,
            "questions": [
                {"question_id": f"q{n}", "item_id": BANK[n - 1]["id"], "marks": 1, "kc_ids": [KC]} for n in (1, 2)
            ],
        }
    ],
}


@pytest.fixture
def desk(tmp_path: Path) -> Iterator[AssessmentDesk]:
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    index = PackIndex.from_tables(
        [
            (
                {"pack_id": "pack.mth.o", "version": "1.0.0", "subject": "mth"},
                {
                    "items": BANK,
                    "worked_examples": [EXAMPLE],
                    "mock_papers": [PAPER],
                    "kcs": [
                        {
                            "id": KC,
                            "statement": "Add",
                            "node_id": TOPIC,
                            "code": "add",
                            "status": "active",
                            "prerequisites": [],
                            "misconception_ids": [],
                        }
                    ],
                    "curriculum_nodes": [
                        {"id": "cur.mth.o", "title": "Math", "kind": "subject"},
                        {"id": TOPIC, "title": "Number", "kind": "topic", "parent_id": "cur.mth.o"},
                    ],
                    "misconceptions": [],
                },
            )
        ]
    )
    wall = [1_800_000_000_000]
    learner = Learner.open(conn, profile_id="0" * 26, device_id="f" * 32, wall_ms=lambda: wall[0],
                           max_skew_ms=SETTINGS.sync_clock_skew_max_ms, params=MasteryParams.from_settings(SETTINGS),
                           content=index)  # fmt: skip
    yield AssessmentDesk(learner, index, SETTINGS, clock_ms=lambda: wall[0], monotonic_ms=lambda: 0)
    conn.close()


@contextmanager
def offline() -> Iterator[list[str]]:
    """Networking blocked: any connection off this machine fails and is recorded."""
    attempts: list[str] = []
    real = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            attempts.append(str(host))
            raise OSError("networking is blocked in this test")
        return real(sock, address)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", guarded)
    try:
        yield attempts
    finally:
        patch.undo()


def api(desk: AssessmentDesk, tmp_path: Path) -> Any:
    """The core's app with no model at all: any attempt to load one fails the test."""
    core = CoreService(SETTINGS, lambda state: (_ for _ in ()).throw(AssertionError("no model")),
                       SessionStore(tmp_path / "sessions"))  # fmt: skip
    core.assessments = lambda: desk
    return create_app(core, LaunchSecret("fixture-token"), lambda: 8911)


async def get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    return await client.get(path, headers={"authorization": "Bearer fixture-token", "origin": "tauri://localhost"})


def exposed(desk: AssessmentDesk) -> list[tuple[str, str]]:
    return [(e.payload["item_id"], e.payload["surface"]) for e in desk.learner.log.by_seq() if e.type == "item_exposed"]


def uxs51_reserved_items_hidden(desk: AssessmentDesk, tmp_path: Path) -> None:
    reserved = {BANK[0]["id"], BANK[1]["id"]}
    check = desk.start_assessment("mastery_check", "mathematics", KC)
    protected = check["current_item"]["item_id"]
    hidden = reserved | {protected}
    app = api(desk, tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            # A query every hidden stem matches, a query naming one hidden item's own number, and the direct links.
            for q in ("synthetic carrying sum", "sum 1:", "sum 2:", f"sum {protected.rsplit('.', 1)[1].lstrip('0')}:"):
                reply = await get(c, f"/v1/search/items?q={q}")
                assert reply.status_code == 200
                body = reply.json()
                assert [e.message for e in ITEMS.iter_errors(body)] == []
                assert not hidden & {i["item_id"] for i in body}, q
                for shown in body:  # no stem, snippet or step of a hidden item travels in a visible one
                    assert all(BANK[int(h.rsplit(".", 1)[1]) - 1]["stem"] not in json.dumps(shown) for h in reserved)
            for item_id in hidden:
                reply = await get(c, f"/v1/items/{item_id}/solution")
                assert reply.status_code == 404 and "latex" not in reply.text and "Synthetic" not in reply.text

    asyncio.run(scenario())
    searched = {item_id for item_id, surface in exposed(desk) if surface.startswith("search")}
    assert not hidden & searched, "search showed a hidden item"  # the check itself showed its own item
    # The same filter holds on the desk with no API in between, and an ordinary item is still found.
    found = {i["item_id"] for i in desk.search("carrying")}
    assert found and not hidden & found
    for item_id in hidden:
        with pytest.raises(Refused, match="not_found"):
            desk.solution(item_id)
    # A blank query matches nothing and records nothing.
    before = len(exposed(desk))
    assert desk.search("   ") == [] and len(exposed(desk)) == before


def uxs51_search_offline_no_model(desk: AssessmentDesk, tmp_path: Path) -> None:
    app = api(desk, tmp_path)

    async def scenario() -> tuple[list[dict[str, Any]], float]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            started = time.perf_counter()
            reply = await get(c, "/v1/search/items?q=worked example")
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert reply.status_code == 200
            return reply.json(), elapsed_ms

    with offline() as attempts:
        body, elapsed_ms = asyncio.run(scenario())
    assert attempts == [], "the search reached the network"
    # The matching worked example comes back by every word of the query, within the acceptance budget (measured on
    # this machine; the low-class reference laptop run is the release gate's, EVL-14).
    assert [i["item_id"] for i in body] == [BANK[-1]["id"]]
    assert elapsed_ms <= SETTINGS.search_offline_ms, elapsed_ms
    assert exposed(desk) == [(BANK[-1]["id"], "search_preview")], "the preview is recorded as seen before it is shown"


def uxs51_solution_on_request(desk: AssessmentDesk, tmp_path: Path) -> None:
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    # The route is the generated contract's (D101 adopted it): a WorkedExampleView, not_found or tutor_locked.
    route = ENDPOINTS_BY_KEY["GET /v1/items/{item_id}/solution"]
    assert (route["request"], route["response"], route["errors"]) == (None, "WorkedExampleView",
                                                                     ["not_found", "tutor_locked"])  # fmt: skip
    app = api(desk, tmp_path)
    plain, worked = BANK[5]["id"], BANK[-1]["id"]

    async def scenario() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8911") as c:
            listed = (await get(c, "/v1/search/items?q=sum 6:")).json()
            assert [i["item_id"] for i in listed] == [plain]
            assert "solution" not in json.dumps(listed), "a preview carries no solution"
            out = []
            for item_id in (plain, worked):
                reply = await get(c, f"/v1/items/{item_id}/solution")
                assert reply.status_code == 200, reply.text
                out.append(reply.json())
            return out

    solution, example = asyncio.run(scenario())
    for view in (solution, example):
        assert [e.message for e in VIEW.iter_errors(view)] == []
        assert view["faded_steps"] == [], "the full solution: no step left for the student to fill"
    # The item's own steps in order, then its answer; an item solved by a worked example shows that example in full.
    assert [s["latex"] for s in solution["steps"]] == ["6 + 6", "= 12"] and solution["final_answer"]["latex"] == "= 12"
    assert [s["latex"] for s in example["steps"]] == ["18 + 25", "= 43"] and example["final_answer"] == EXAMPLE[
        "final_answer"
    ]
    # No attempt was asked for or recorded; opening the solution recorded the item as seen (ASM-22).
    kinds = {e.type for e in desk.learner.log.by_seq()}
    assert not kinds & {"attempt", "attempt_started", "verdict", "step_checked"}
    assert (plain, "search_open") in exposed(desk) and (worked, "search_open") in exposed(desk)
    # While a mock sitting is open, solutions wait (PED-09: only a running mock blocks a solution).
    exam = desk.create_mock(PAPER["id"])
    desk.transition(exam["exam_id"], "start")
    with pytest.raises(Refused, match="tutor_locked"):
        desk.solution(plain)


def test_prm03_profile_tutor_name_fills_the_soul() -> None:
    """PRM-03, D99: the open profile's chosen tutor name fills the soul's placeholder in place of the identity file's,
    in the prompt the coach is built with; no choice keeps the default, and the soul's sections stay as written."""
    from agent_core.prompts.builder import PromptSession
    from test_m4e_prompts import assets, build

    loaded = assets()
    soul_tier = lambda session: next(t.text for t in build("coach", session, loaded).tiers if t.index == 1)  # noqa: E731
    default = soul_tier(PromptSession())
    assert "Jana" in default
    chosen = soul_tier(PromptSession(tutor_name="Ama"))
    assert "Ama" in chosen and "Jana" not in chosen
    assert soul_tier(PromptSession(tutor_name="Jana")) == default
    named = loaded.soul.named("Ama")
    assert tuple(named.sections) == tuple(loaded.soul.sections) and loaded.soul.named(None) is loaded.soul


def tch13_solution_on_request(desk: AssessmentDesk, tmp_path: Path) -> None:
    """Search previews do not leak answers; an explicit request returns every checked step without an attempt."""
    uxs51_solution_on_request(desk, tmp_path)
