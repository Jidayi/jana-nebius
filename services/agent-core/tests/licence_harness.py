"""Shared steps for the M20.d and M20.e tests: a core with a development-signed physics pack and one student,
lesson checks answered with the item keys, and licences issued by the test hierarchy (never trusted by pilot or
production builds). Every learner is invented."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.api import licence as licence_routes
from agent_core.config import Settings
from agent_core.store.licence import LicenceDesk
from api_harness import Running, cli, start_core
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from test_m10a_profiles import Api, student
from test_m13g_learn import CHANGE, SPEED, Client, install, item_record, key_answer, mastery

# A patient worker supervisor: on a heavily loaded machine a slow ping must not recycle the worker mid-marking, which
# these tests (about licences, not the supervisor of TOL-26) would read as a wrong answer.
SETTINGS = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), api_command_burst_per_s=1000,
                    worker_ping_interval_s=30.0, worker_missed_pings_recycle=10, worker_warm_target_s=60.0,
                    consent_dpia_ref="dpia-test-1")  # fmt: skip
DAY_MS = 86_400_000


async def core(tmp: Path, *, wall_ms: Callable[[], int] | None = None, worker: bool = True,
               settings: Settings = SETTINGS) -> Running:  # fmt: skip
    """A core over `tmp` (a pack installed once), its licence evaluated with the clock `wall_ms`, and the M16
    assessment desk wired as the app wires it, so a mock sitting is a real one."""
    if not (tmp / "packs").is_dir():
        install(tmp, "phy")
    r = await start_core(tmp, settings=settings, worker=worker, licence=False)
    r.core.assessments = r.runtime.assessments
    r.core.mock_active = lambda: bool((opened := r.runtime.assessments()) and opened.mock_active())
    attach(r, wall_ms=wall_ms)
    return r


def attach(r: Running, *, wall_ms: Callable[[], int] | None = None) -> LicenceDesk:
    """Evaluate the licence again as a fresh start would (PLT-20: once per start)."""
    desk = licence_routes.attach(r.core, r.data_dir, wall_ms=wall_ms, trust=dev_trust())
    assert desk is not None
    return desk


async def learner(r: Running, name: str = "Ama") -> tuple[Api, str, str]:
    """One student, added and opened with a tap (no PIN, D86): (api, profile id, profile token)."""
    api = Api(r)
    profile = await api.add(student(name))
    return api, profile, await api.token(profile)


async def lesson_items(c: Client, subject_id: str = "cur.phy.o") -> list[tuple[str, str]]:
    """(lesson id, item id) for every check item of the subject's lessons, in map order."""
    found = []
    subject_map = await c.ok("GET", f"/v1/curriculum/{subject_id}/map")
    for section in subject_map["sections"]:
        for topic in section["topics"]:
            for lesson in topic["lessons"]:
                view = await c.ok("GET", f"/v1/lessons/{lesson['lesson_id']}")
                found += [(lesson["lesson_id"], i["item_id"]) for b in view["blocks"] for i in b.get("items", [])]
    return found


async def answer(c: Client, lesson_id: str, item_id: str) -> dict[str, Any]:
    body = {"client_attempt_id": cli(), "item_id": item_id, "answer": key_answer(item_record("phy", item_id)),
            "time_ms": 9000}  # fmt: skip
    return await c.ok("POST", f"/v1/lessons/{lesson_id}/checks", body)


def seed_progress(r: Running) -> None:
    """Earlier learning in the open profile's mastery projection: two KCs moved on from not started. (Lesson quick
    checks are marked but not yet recorded as attempts, so they move no mastery; see the M20 report.)"""
    mastery(r, SPEED, "mastered")
    mastery(r, CHANGE, "moved_on")


async def kc_states(c: Client) -> dict[str, str]:
    subject_map = await c.ok("GET", "/v1/curriculum/cur.phy.o/map")
    return {k["kc_id"]: k["state"] for s in subject_map["sections"] for t in s["topics"] for k in t["kcs"]}


NOTICE = "2026-10.d1"  # the shipped cloud_tier notice version (content/agent/notices)


def subscription(profiles: list[str], *, period_end: str = "2099-01-01T00:00:00.000Z") -> dict[str, Any]:
    """A signed cloud tier entitlement as the checkout returns it (D70), from the test hierarchy."""
    document = {"kind": "cloud_tier_subscription", "subscription_id": "sub_test_0001", "licence_id": "lic_test",
                "period_start": "2026-09-01T00:00:00.000Z", "period_end": period_end, "seats": 4,
                "allowance_tokens": 1_800_000, "profile_ids": profiles,
                "plan": "jana_online", "band": "nigeria", "billing": "month", "features": ["cloud_tier"], "limits": {},
                "created_at": "2026-10-01T00:00:00.000Z"}  # fmt: skip
    return dev_signer(Purpose.LICENCE).sign("licence_file", document, now="2026-10-01T00:00:00.000Z")


async def subscribe(api: Api, profiles: list[str], **kwargs: Any) -> Any:
    """The checkout's signed entitlement, with the guardian's consent given there for each profile (D70, PRV-06)."""
    body = {"entitlement": subscription(profiles, **kwargs),
            "consents": [{"profile_id": p, "notice_version": NOTICE} for p in profiles]}  # fmt: skip
    return await api.call("POST", "/v1/subscription", body)
