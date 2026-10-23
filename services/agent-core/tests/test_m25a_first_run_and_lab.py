"""M25.a, JRN-03 and JRN-11: first run to a first plan (persona P1) and a school lab install with its licence file
(persona P7), played on the shipped core over its local API (JRN-02 runner, offline, deterministic fake model).

Step 1 of both journeys is the native installer (`runs_on: device_lab`); the core's part of an install (the signed
packs and model of the USB kit verified offline, PLT-12, CUR-09; the free-disk check, PLT-06, PLT-23) is played in the
steps and branches that follow. Every learner, licence, kit and reply here is synthetic."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agent_core.api.packs import PackDesk
from agent_core.config.environments import Environment
from agent_core.engine.runtime_link import write_launch_plan
from agent_core.learner.profile import stored_profile
from agent_core.providers.scripted import ScriptedProvider
from agent_core.router.probe import Probe
from agent_core.store.events import iso_ms
from agent_core.store.packs import TABLES
from api_harness import Running, cli, stop_core
from engine_harness import STATEMENT, checker_steps, solver_steps, tutor
from jana_tools.fakes import models as fake_models
from jana_tools.journeys.runner import Probe as JourneyProbe
from jana_tools.journeys.runner import Run
from journey_harness import MODELS, branches, play, restart, session, start, turn
from licence_harness import DAY_MS, attach, lesson_items, subscribe
from m20_fixtures import content_pack, model_pack
from signing_service.hierarchy import dev_trust
from signing_service.licences import issue_licence_file
from signing_service.service import sign_kit
from test_g114_s2_engine import diagnosis, guard
from test_m10a_profiles import Api, code
from test_m10d_deletion_export import PASSPHRASE, _export
from test_m13g_learn import Client, source
from test_m20e_licensing import EN, FRESH_OFFLINE, offline_part, practice_key

PROBES = Path(__file__).parent / "fixtures" / "probe"
SAFE = "Which quantities does the question give you, and which one does it ask for?"
MODEL_PACK = "mp.synth.8b.q4_k_m.low"
SUBJECTS = {"phy": "physics", "mth": "mathematics", "chm": "chemistry", "acc": "accounting"}
# Words no learning flow may show: a purchase or activation prompt (LRN-35, UXS-47, D84).
SELLING = re.compile(r"\b(buy|purchase|price|pay(ment)?|subscribe|subscription|activat\w*|licen[cs]e key|upgrade)\b",
                     re.IGNORECASE)  # fmt: skip
# Keys no diagnostic reply may carry: a score, a percentage or a mark (UXS-40, ASM-10).
SCORED = ("score", "percent", "verdict", "marks_awarded", "correct")
INSTALLER = ("the native installer from the USB kit or the download: signatures and free disk checked before copying, "
             "with no network (PLT-06, PLT-12, SEC-15); the core's part of the kit is played in JRN-11")  # fmt: skip


# --- helpers over the client's API -----------------------------------------------------------------------------------


def reference(name: str) -> tuple[Probe, dict[str, float] | None]:
    """A synthetic reference laptop of EVL-14: its probe and the generation speeds its runtime reports."""
    data = json.loads((PROBES / f"{name}.json").read_text())
    assert data["synthetic"] is True
    return Probe.from_json(data["probe"]), data["benchmark"]


@dataclass
class TimedScripted(ScriptedProvider):
    """The deterministic fake model, whose runtime also answers the PLT-08 probe generation at the reference laptop's
    recorded speed (as the loopback stand-in for llama-server does in test_m11a_classes)."""

    timings: dict[str, float] = field(default_factory=dict)

    async def benchmark(self, model: str, prompt: str, generate: int, timeout_s: float) -> dict[str, float]:
        return {k: float(self.timings[k]) for k in ("prompt_tokens_s", "generation_tokens_s", "seconds")}


def timed(script: dict[str, list[Any]], laptop: str = "low") -> TimedScripted:
    _, bench = reference(laptop)
    return TimedScripted(script, kind="local", installed_models=list(MODELS), timings=dict(bench or {}))


def question_script(turns: int = 1) -> dict[str, list[Any]]:
    """The S2 turn path for `turns` questions on the scripted model (input guard, Diagnoser, Solver, Checker, Coach)."""
    return {"input_guard": [guard() for _ in range(turns)], "diagnoser": [diagnosis() for _ in range(turns)],
            "solver": [s for _ in range(turns) for s in solver_steps()],
            "checker": [s for _ in range(turns) for s in checker_steps()],
            "coach": [tutor(SAFE) for _ in range(turns)]}  # fmt: skip


def launch(r: Running, laptop: str) -> dict[str, Any]:
    """What the app's start does before `control.ready` (agent_core.api.__main__): the machine probed once, offline
    (MDL-16), and the runtime's launch plan written from the models the installer copied."""
    probe, _ = reference(laptop)
    r.runtime.probe, r.runtime.epoch = probe, r.core.epoch
    plan: dict[str, Any] = write_launch_plan(r.data_dir, r.core.settings, False, r.core.epoch, False, probe)
    r.runtime.plan = plan
    return plan


def by_name(name: str, packs: list[dict[str, Any]]) -> dict[str, Any]:
    """What "Who's learning?" sends for a student added by name: the name and the defaults of TABLE PLT-17b (every
    installed subject at its level, a minor age band, no exam month)."""
    names = sorted({SUBJECTS[p["subject"]] for p in packs if p["subject"] in SUBJECTS and p["signature_ok"]})
    return {"display_name": name, "avatar": "avatar-1", "level": "O", "age_band": "13_15", "subjects": names}


async def add_by_name(r: Running, name: str) -> str:
    api = Api(r)
    packs = (await api.call("GET", "/v1/packs")).json()["packs"]
    return await api.add(by_name(name, packs))


async def first_run(r: Running, name: str = "Ama") -> tuple[Client, str]:
    """ "Who's learning?" (the one step of TABLE PLT-17a), then "Start learning"; the student opened with a tap."""
    api = Api(r)
    assert (await api.call("GET", "/v1/setup")).json()["step"] == "students"
    profile = await add_by_name(r, name)
    done = await api.call("PUT", "/v1/setup", {"step": "done"})
    assert done.status_code == 200 and done.json()["step"] == "done", done.text
    return Client(r, await api.token(profile)), profile


async def opened(r: Running, profile: str) -> Client:
    """A profile opened with a tap: no PIN or code (D86, D87)."""
    reply = await Api(r).unlock(profile)
    assert reply.status_code == 200, reply.text
    return Client(r, reply.json()["profile_token"])


async def job_end(c: Client, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        job = await c.ok("GET", f"/v1/jobs/{job_id}")
        if job["state"] in ("done", "failed") or time.monotonic() > deadline:
            return job
        await asyncio.sleep(0.02)


def unscored(found: Any, where: str) -> None:
    """No key of a diagnostic reply carries a score, a percentage or a mark (UXS-40)."""
    if isinstance(found, dict):
        for key, value in found.items():
            assert not any(word in key.lower() for word in SCORED), f"{where}: {key}"
            unscored(value, where)
    elif isinstance(found, list):
        for value in found:
            unscored(value, where)


def misconception_choice(item_id: str) -> tuple[dict[str, Any], str] | None:
    """For a misconception-mapped item, the answer that picks a mapped distractor, and its misconception."""
    record = next(i for i in source("phy")["items"] if i["id"] == item_id)
    if record["type"] != "mcq_diagnostic" or len(record["parts"]) != 1:
        return None
    part = record["parts"][0]
    wrong = next((o for o in part["answer"]["options"] if not o["correct"] and o.get("misconception_id")), None)
    if wrong is None:
        return None
    return {"parts": [{"part_id": part["id"], "kind": "mcq", "option_id": wrong["id"]}]}, wrong["misconception_id"]


async def diagnose(c: Client, subject: str = "physics", *, stop_after: int | None = None, how: str = "key",
                   ) -> tuple[dict[str, Any], list[str], list[str]]:  # fmt: skip
    """The entry diagnostic, each served item answered (`how`: its key, "not_learned", or "misconception": a mapped
    distractor where the item has one, else the key), until it ends or `stop_after` answers. Returns the last state,
    the items served in order, and the misconceptions chosen."""
    state = await c.ok("POST", "/v1/assessments", {"kind": "diagnostic", "subject": subject})
    unscored(state, "start")
    served: list[str] = []
    chosen: list[str] = []
    while state["state"] == "in_progress" and state["current_item"] is not None:
        if stop_after is not None and state["answered_count"] >= stop_after:
            break
        item_id = state["current_item"]["item_id"]
        served.append(item_id)
        body: dict[str, Any] = {"client_answer_id": cli(), "item_id": item_id, "action": "answer"}
        mapped = misconception_choice(item_id) if how == "misconception" else None
        if how == "not_learned":
            body["action"] = "not_learned"
        elif mapped is not None:
            body["answer"], misconception = mapped
            chosen.append(misconception)
        else:
            body["answer"] = practice_key(item_id)
        state = await c.ok("POST", f"/v1/assessments/{state['assessment_id']}/answers", body)
        unscored(state, f"answer {len(served)}")
    return state, served, chosen


async def kc_states(c: Client) -> dict[str, str]:
    subject_map = await c.ok("GET", "/v1/curriculum/cur.phy.o/map")
    return {k["kc_id"]: k["state"] for s in subject_map["sections"] for t in s["topics"] for k in t["kcs"]}


async def learns(c: Client) -> None:
    """Lessons and practice answer: a lesson opened and its first quick check marked, one practice item marked."""
    (lesson_id, item_id), *_ = await lesson_items(c)
    assert (await c.ok("GET", f"/v1/lessons/{lesson_id}"))["blocks"]
    body = {"client_attempt_id": cli(), "item_id": item_id, "answer": practice_key(item_id), "time_ms": 9000}
    assert (await c.ok("POST", f"/v1/lessons/{lesson_id}/checks", body))["verdict"] == "correct"
    practice = await c.ok("POST", "/v1/practice/sets", {"client_set_id": cli(), "subject": "physics", "size": 3,
                                                       "source": "adaptive"})  # fmt: skip
    item = practice["current_item"]
    assert item is not None
    body = {"client_attempt_id": cli(), "item_id": item["item_id"], "time_ms": 9000, "hints_used": 0,
            "answer": practice_key(item["item_id"])}  # fmt: skip
    assert (await c.ok("POST", f"/v1/practice/sets/{practice['set_id']}/answers", body))["verdict"] == "correct"


async def tutor_turn(c: Client) -> dict[str, Any]:
    """One guided question on the scripted model; the engine's record of the turn."""
    sid = await session(c)
    engine = await turn(c, sid, STATEMENT)
    return dict(engine.turn_log[-1])


def no_selling(found: Any, where: str) -> None:
    text = json.dumps(found)
    assert not SELLING.search(text), f"{where}: {SELLING.search(text)}"


# --- JRN-03: first run to a first plan -------------------------------------------------------------------------------

OWN_GOAL = "Understand circuits before the mock"  # the student's own words for a goal (synthetic)


async def interview(c: Client, provider: Any) -> list[str]:
    """The hand-off's first-session interview as the client plays it (UXS-10, TOL-20): one question on each card, each
    answered with its first option (and the student's own words where the card takes them), with no model call. Returns
    the questions asked, in order."""
    calls = len(provider.requests)
    asked: list[str] = []
    view = await c.ok("GET", "/v1/interview")
    while not view["done"]:
        question = view["question"]
        card = question["card"]
        assert card["card_type"] == "question" and card["options"] and not SELLING.search(json.dumps(card))
        asked.append(question["question_id"])
        answer: dict[str, Any] = {"option_ids": [card["options"][0]["id"]]}
        if card["allow_free_text"]:
            answer["text"] = OWN_GOAL
        view = await c.ok("POST", f"/v1/interview/{question['question_id']}/answer",
                          {"client_answer_id": cli(), "answer": answer})  # fmt: skip
        assert view["answered"] == len(asked)
    assert len(provider.requests) == calls, "the interview's questions are scripted: no model call"
    return asked


def first_run_core(tmp_path: Path, provider: Any, laptop: str = "low") -> Callable[[], Any]:
    """The data folder after the installer (step 1): the bundled models copied (none below the minimum laptop); the
    core starts on it and writes its launch plan for the reference laptop."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    if laptop != "below_minimum":
        fake_models.install(data)

    @contextlib.asynccontextmanager
    async def started() -> AsyncIterator[Device]:
        device = Device(await start(data, provider=provider))
        try:
            launch(device.r, laptop)
            yield device
        finally:
            await stop_core(device.r)

    return started


@dataclass
class Device:
    """The computer's running core, which a restart replaces (the same data folder)."""

    r: Running

    async def restart(self, provider: Any, laptop: str = "low") -> Running:
        # The packs are installed already; a restart reads them as they are (`subjects=()`).
        self.r = await restart(self.r, provider=provider, subjects=())
        launch(self.r, laptop)
        return self.r


def _first_run(tmp_path: Path) -> JourneyProbe:
    provider = timed({})  # every step here is code: any model call would exhaust the script and fail the case
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        began = time.monotonic()
        async with started() as device:
            r = device.r
            api = Api(r)
            run.device_lab(1, INSTALLER)
            with run.step(2):  # UXS-10, PLT-17, PLT-08, MDL-16, TCH-13, PRV-02, PRV-12, DAT-14, CUR-01, PLT-13, CUR-08
                packs = (await api.call("GET", "/v1/packs")).json()["packs"]
                assert [(p["pack_id"], p["signature_ok"]) for p in packs] == [("pack.phy.o", True)]  # CUR-08, PLT-13
                c, profile = await first_run(r)
                (tile,) = (await api.call("GET", "/v1/profiles")).json()["profiles"]
                assert set(tile) == {"profile_id", "display_name", "avatar"}, "no PIN, code or account (D86)"
                shown = await c.ok("GET", f"/v1/profiles/{profile}")
                assert (shown["level"], shown["subjects"], shown["age_band"], shown["exam_date"]) == (
                    "O",
                    ["physics"],
                    "13_15",
                    None,
                )  # the defaults of TABLE PLT-17b: installed subjects, a minor
                assert (await c.ok("GET", "/v1/licence"))["state"] == "none"  # nothing activated (PLT-19, D84)
                features = (await c.ok("GET", "/v1/connectivity"))["features"]
                assert features and not any(f["enabled"] for f in features.values())  # PRV-02
                assert r.core.notices.get("cloud_tier"), "the versioned notices ship (PRV-12)"
                models = await c.ok("GET", "/v1/models")
                hardware = models["hardware"]
                assert (hardware["hardware_class"], hardware["basis"], hardware["benchmark_due"]) == (
                    "low",
                    "predicted",
                    True,
                )  # MDL-16: the probe predicts; the benchmark is due on first run
                assert r.runtime.plan is not None and r.runtime.plan["model"] == models["recommended"]["strong"]
                started_bench = await c.send("POST", "/v1/models/benchmark", {})
                assert started_bench.status_code == 202, started_bench.text
                job = await c.ok("GET", f"/v1/jobs/{started_bench.json()['job_id']}")
                assert job["state"] == "running", job  # in the background (PLT-08)
                assert r.runtime.measuring is not None
                choice = await r.runtime.measuring
                measured = (await c.ok("GET", "/v1/models"))["hardware"]
                assert choice is not None and choice.hardware_class == "low" and not choice.provisional
                assert (measured["hardware_class"], measured["basis"], measured["benchmark_due"]) == (
                    "low",
                    "measured",
                    False,
                )
            with run.step(3):  # UXS-10, TOL-20, LRN-03, MEM-06: the first-session interview on the hand-off
                assert await interview(c, provider) == ["goals", "confidence"], "one question per card"
                with r.runtime.directory.open_learner(profile) as conn:
                    merged = stored_profile(conn)
                assert merged["goals"] and OWN_GOAL in merged["goals"], merged  # merged into the profile (LRN-04)
                assert (await c.ok("GET", "/v1/interview"))["done"], "asked once"
            with run.step(4):  # UXS-40, ASM-10, ASM-11, ASM-12, LRN-10, CUR-05
                before = await kc_states(c)
                state, served, chosen = await diagnose(c, how="misconception")
                assert state["state"] == "completed" and state["current_item"] is None
                assert len(served) == state["answered_count"] <= r.core.settings.diagnostic_max_items  # ASM-10
                assert chosen, "a misconception-mapped choice was offered and taken (ASM-12)"
                knows = await c.ok("GET", f"/v1/profiles/{profile}/knows")
                assert set(chosen) & set(re.findall(r"mc\.phy\.o\.[a-z0-9_]+", json.dumps(knows))), knows
                after = await kc_states(c)
                assert after != before, "mastery is initialised from the diagnostic"
                assert {t["status"] for t in state["outcome_topics"]} - {"not_started"}  # labels, never a score
                # Adaptive over the prerequisite graph (ASM-11): another student answering "I haven't learned this
                # yet" starts from the same anchors and is walked to other items.
                other = await opened(r, await add_by_name(r, "Kofi"))
                _, walked, _ = await diagnose(other, how="not_learned")
                assert walked[0] == served[0] and walked != served, (served, walked)
                c = await opened(r, profile)
            with run.step(5):  # LRN-28, UXS-12
                calls = len(provider.requests)
                plan = await c.ok("POST", "/v1/plans", {"client_request_id": cli()})
                assert len(provider.requests) == calls, "the plan is built by code, with no model call"
                main = next(b for b in plan["blocks"] if b["kind"] == "main")
                assert main["kc_ids"] and main["minutes"] > 0
                assert plan["card"]["card_type"] == "plan" and {"start", "change"} <= set(plan["card"]["actions"])
                assert re.search(r"lesson|practice", plan["card"]["items"][0]["text"])  # a lesson or practice first
                current = await c.ok("GET", "/v1/plans/current")
                assert current is not None and current["plan_id"] == plan["plan_id"]  # what Home shows
        run.note(
            f"the scripted first run to Home's plan took {time.monotonic() - began:.1f} s on this machine, install "
            "excluded; the target on the low-class reference laptop is the device lab's (JRN-03 acceptance)"
        )

    return probe


def _f1_below_minimum(tmp_path: Path) -> JourneyProbe:
    """PLT-29, PRD-04, ARC-26: a 4 GB machine finishes setup in the content-only class; the figures Home shows come
    from the check that failed; lessons and practice work, no model is called, and the online tier stays on offer."""
    provider = timed({})
    started = first_run_core(tmp_path, provider, "below_minimum")

    async def probe(run: Run) -> None:
        async with started() as device:
            r = device.r
            c, _ = await first_run(r)
            models = await c.ok("GET", "/v1/models")
            hardware = models["hardware"]
            assert (hardware["hardware_class"], hardware["basis"], hardware["tutor_path"]) == (
                "content_only",
                "below_minimum_ram",
                "none",
            )
            assert hardware["shortfalls"] == [{"check": "ram", "have": 4, "need": 8.0, "unit": "GB"}]
            assert models["recommended"]["reason_key"] == "hardware_class.content_only.below_minimum_ram"
            await learns(c)
            sid = await session(c)
            refused = await c.send(
                "POST",
                f"/v1/sessions/{sid}/turns",
                {"client_message_id": cli(), "intent": "ask", "content": [{"type": "text", "text": STATEMENT}]},
            )
            assert code(refused) == "model_unavailable", refused.text
            assert provider.requests == [], "no model call on a machine below the minimum laptop"
            assert not (await c.ok("GET", "/v1/connectivity"))["features"]["cloud_tier"]["enabled"]
            assert (await c.ok("GET", "/v1/licence"))["entitlements"]["cloud_tier"] == "available"

    return probe


def _f2_model_loading(tmp_path: Path) -> JourneyProbe:
    provider = timed(question_script())
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        async with started() as device:
            r = device.r
            # The runtime is attached and its touch generation runs (TABLE ARC-22b `model_loading`), as the link
            # reports it to the core.
            r.core.readiness, r.core.components["runtime"] = "model_loading", "starting"
            c, profile = await first_run(r)
            health = await c.ok("GET", "/v1/health")
            assert (health["readiness"], health["components"]["runtime"]) == ("model_loading", "starting")
            await learns(c)  # Home is usable while the model warms (MDL-20)
            assert await interview(c, provider) == ["goals", "confidence"]  # scripted while the model warms
            with r.runtime.directory.open_learner(profile) as conn:
                merged = stored_profile(conn)
            assert merged["goals"], merged
            r.core.readiness, r.core.components["runtime"] = "ready", "ok"  # warm: the tutor joins
            assert (await tutor_turn(c))["turn_id"]

    return probe


def _f3_power_cut(tmp_path: Path) -> JourneyProbe:
    """ARC-25, DAT-07: the power is cut during the diagnostic; on restart it resumes at the last answered item."""
    provider = timed({})
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        async with started() as device:
            r = device.r
            c, profile = await first_run(r)
            state, served, _ = await diagnose(c, stop_after=3)
            assert state["state"] == "in_progress" and state["answered_count"] == 3
            waiting = state["current_item"]["item_id"]
            assessment = state["assessment_id"]
            r2 = await device.restart(provider)  # the power cut: nothing stopped or saved on the way down
            c2 = await opened(r2, profile)
            found = [a for a in (await c2.get("/v1/assessments")).json() if a["assessment_id"] == assessment]
            assert [a["state"] for a in found] == ["stopped"], found  # set aside at the restart, never lost
            back = await c2.ok("POST", f"/v1/assessments/{assessment}/resume", {})
            assert back["state"] == "in_progress", back
            assert [a["item_id"] for a in back["answered_items"]] == served, "every answer before the cut is kept"
            assert back["current_item"]["item_id"] == waiting, "it resumes at the next unanswered item"
            resumed, more, _ = await diagnose(c2)
            assert resumed["state"] == "completed" and resumed["answered_count"] == 3 + len(more)
            assert resumed["answered_count"] <= r2.core.settings.diagnostic_max_items

    return probe


def _f4_skip_diagnostic(tmp_path: Path) -> JourneyProbe:
    """LRN-10: "Skip for now": mastery starts from priors (every KC not started), a plan is still offered, and the
    diagnostic stays on offer for later."""
    provider = timed({})
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        async with started() as device:
            r = device.r
            c, _ = await first_run(r)
            assert set((await kc_states(c)).values()) == {"not_started"}  # unassessed KCs show not started
            assert (await c.get("/v1/assessments")).json() == []  # nothing begun: Home offers "Find my starting point"
            plan = await c.ok("POST", "/v1/plans", {"client_request_id": cli()})
            assert next(b for b in plan["blocks"] if b["kind"] == "main")["kc_ids"]
            assert re.search(r"lesson", plan["card"]["items"][0]["text"])  # from priors: a lesson first
            later = await c.ok("POST", "/v1/assessments", {"kind": "diagnostic", "subject": "physics"})
            assert later["state"] == "in_progress" and later["current_item"] is not None  # offered again later
            assert provider.requests == []

    return probe


def _f5_cloud_tier(tmp_path: Path) -> JourneyProbe:
    """ARC-11, PRV-05, PRV-06, MDL-24, D70: the subscription the parent bought online is applied with the guardian's
    consent given at the checkout; applying it records the consent and switches the tier on; offline, the tutor runs
    on the local tier and nothing is sent."""
    provider = timed(question_script())
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        from net_harness import FakeServices, layer

        (tmp_path / "services").mkdir(exist_ok=True)
        async with started() as device, FakeServices(tmp_path / "services") as services:
            r = device.r
            r.core.entitlement_trust = dev_trust()
            c, profile = await first_run(r)
            # This core's connectivity layer, pointed at the stand-in online services on loopback.
            await r.core.online.stop()
            online = layer(tmp_path / "net", services, device=r.runtime.stores.device)
            r.core.online = r.runtime.online = online
            online.publish.append(r.core.publish_app)
            r.core.closers.insert(0, online.stop)
            api = Api(r)
            applied = await subscribe(api, [profile])
            assert applied.status_code == 200, applied.text
            assert applied.json()["state"] == "active"
            consents = (await api.call("GET", f"/v1/profiles/{profile}/consents", profile=c.token)).json()
            (cloud,) = [s for s in consents if s["scope"] == "cloud_tier"]
            assert (cloud["granted"], cloud["granted_by_role"], cloud["method"]) == (
                True,
                "guardian",
                "checkout_guardian",
            )  # the guardian's consent from the checkout (PRV-06, D70)
            features = (await c.ok("GET", "/v1/connectivity"))["features"]
            assert features["cloud_tier"]["enabled"], "applying the subscription switched the tier on (D70)"
            with r.runtime.directory.open_learner(profile) as conn:
                assert online.cloud_effective(profile, conn), "in effect for this profile (MDL-24)"
            # Online: the device registers its service credential with the subscription (SEC-21), on loopback only.
            await online.connectivity.check()
            assert online.connectivity.state == "online"
            await online.credential.token()
            registration = next(s for s in services.requests if s.path == "/v1/devices").json()
            assert registration["entitlement"]["subscription_id"] == "sub_test_0001"
            # Offline: the network goes; the tutor runs on the local tier at once and nothing more leaves.
            online.connectivity.os_hint(online=False)
            sent = len(services.requests)
            c = await opened(r, profile)
            done = await tutor_turn(c)
            coach = [m for m in done.get("model_calls", []) if m.get("role") == "coach"]
            assert all(m["provider_kind"] == "local" for m in coach), coach
            assert any(req.get("_role") == "coach" for req in provider.requests), "the local model taught the turn"
            assert len(services.requests) == sent, "nothing was sent while offline"

    return probe


def _f6_nothing_to_forget(tmp_path: Path) -> JourneyProbe:
    """PLT-17, UXS-47, D84, D86: setup completes and learning starts with no PIN or recovery code to keep safe; a
    restart opens the profile with a tap; no purchase or activation prompt appears inside a learning flow."""
    provider = timed(question_script())
    started = first_run_core(tmp_path, provider)

    async def probe(run: Run) -> None:
        async with started() as device:
            r = device.r
            api = Api(r)
            c, profile = await first_run(r)
            no_selling((await api.call("GET", "/v1/setup")).json(), "setup")
            (lesson_id, item_id), *_ = await lesson_items(c)
            no_selling(await c.ok("GET", f"/v1/lessons/{lesson_id}"), "lesson")
            body = {"client_attempt_id": cli(), "item_id": item_id, "answer": practice_key(item_id), "time_ms": 9000}
            no_selling(await c.ok("POST", f"/v1/lessons/{lesson_id}/checks", body), "quick check")
            no_selling(await c.ok("POST", "/v1/plans", {"client_request_id": cli()}), "plan")
            sid = await session(c)
            await turn(c, sid, STATEMENT)
            no_selling(await c.ok("GET", f"/v1/sessions/{sid}/snapshot"), "tutor session")
            r2 = await device.restart(provider)
            listed = (await Api(r2).call("GET", "/v1/profiles")).json()["profiles"]
            assert [p["profile_id"] for p in listed] == [profile]
            again = await opened(r2, profile)  # a tap; nothing to remember
            assert (await again.ok("GET", "/v1/setup"))["step"] == "done"
            assert await again.ok("GET", "/v1/plans/current") is not None

    return probe


# --- JRN-11: lab install from the USB kit and a school licence -------------------------------------------------------


def lab_kit(tmp_path: Path, model_bytes: int = 64 * 1024) -> Path:
    """The school's USB kit: the development-signed physics pack built from the repository's curriculum, the
    low-class model pack, and the signed `kit.json` listing them (PLT-12)."""
    kit = tmp_path / "kit"
    if (kit / "kit.json").is_file():
        return kit
    (kit / "packs").mkdir(parents=True)
    tables = source("phy")
    written = {t: list(tables.get(t, [])) for t in TABLES if t not in ("search_fts", "search_vectors")}
    content_pack(kit / "packs" / "pack.phy.o.pack", "pack.phy.o", "0.1.0", tables=written)
    model_pack(kit / "models" / MODEL_PACK, weights=bytes(model_bytes), chunk_bytes=16 * 1024)
    files = [("packs/pack.phy.o.pack", "content_pack")]
    files += [(f"models/{MODEL_PACK}/{name}", "model_pack_file") for name in ("manifest.json", "model.gguf")]
    sign_kit(kit, files)
    return kit


def with_desk(r: Running, free: Callable[[], int] | None = None) -> PackDesk:
    """The pack desk the app's start wires (agent_core.api.__main__): installs from a file, folder or the USB kit."""
    desk = PackDesk(r.data_dir, Environment.DEV, "1.0.0", r.core.publish_app, downloads_on=lambda: False,
                    online=lambda: False, free_bytes=free or (lambda: shutil.disk_usage(r.data_dir).free))  # fmt: skip
    r.core.pack_desk = desk
    return desk


async def lab_computer(data: Path, provider: Any) -> Running:
    """A lab computer's core after the installer: no pack yet (they come from the kit)."""
    data.mkdir(parents=True, exist_ok=True)
    r = await start(data, provider=provider, subjects=())
    with_desk(r)
    attach(r)  # the licence state, evaluated against the test hierarchy's licence key
    return r


async def from_kit(r: Running, kit: Path) -> dict[str, Any]:
    c = Client(r)
    reply = await c.send("POST", "/v1/packs/install", {"source": {"kind": "usb", "path": str(kit)}})
    assert reply.status_code == 202 and reply.json()["queued_until_online"] is False, reply.text
    return await job_end(c, reply.json()["job_id"])


async def next_start(r: Running, provider: Any, laptop: str = "low") -> Running:
    """The app closed and started again on the same data folder: what it installed is read anew."""
    r2 = await restart(r, provider=provider, subjects=())
    with_desk(r2)
    attach(r2)
    launch(r2, laptop)
    return r2


LAB_INSTALLER = ("the native installer from the USB kit on each lab computer, with the WebView2 offline installer "
                 "(PLT-05, PLT-06); the core verifies the kit's packs and model after it")  # fmt: skip


def _lab_install(tmp_path: Path) -> JourneyProbe:
    provider = timed(question_script(2))

    async def probe(run: Run) -> None:
        kit = lab_kit(tmp_path)
        r = await lab_computer(tmp_path / "pc1", provider)
        try:
            run.device_lab(1, LAB_INSTALLER)
            job = await from_kit(r, kit)  # the kit's signed packs and model, verified offline (PLT-12, CUR-09)
            assert job["state"] == "done", job
            assert sorted(job["result_ref"].split(",")) == [MODEL_PACK, "pack.phy.o"]
            r = await next_start(r, provider)
            c = Client(r)
            installed = (await c.ok("GET", "/v1/packs"))["packs"]
            assert [(p["pack_id"], p["signature_ok"]) for p in installed] == [("pack.phy.o", True)]
            with run.step(2):  # PLT-17, PLT-18, DAT-15: profiles by name, no PIN, every online feature off
                students = [await add_by_name(r, name) for name in ("Ama", "Kofi")]
                listed = (await c.ok("GET", "/v1/profiles"))["profiles"]
                assert [p["profile_id"] for p in listed] == students
                assert all(set(p) == {"profile_id", "display_name", "avatar"} for p in listed)  # no PIN (D86)
                features = (await c.ok("GET", "/v1/connectivity"))["features"]
                assert not any(f["enabled"] for f in features.values())
            with run.step(3):  # BIZ-04, BIZ-09, PLT-19: the school's one signed licence file, verified offline
                file = issue_licence_file("lab_bundle", 1)  # one seat bought, two students: no seat count stops one
                applied = await c.send("POST", "/v1/licence", {"licence_file": file})
                assert applied.status_code == 200, applied.text
                shown = applied.json()
                assert (shown["state"], shown["install_kind"], shown["seats"]) == ("active", "school_lab", 1)
                assert offline_part(shown["entitlements"]) == FRESH_OFFLINE
                assert attach(r).state.install_kind == "school_lab"  # kept for the next start
            with run.step(4):  # PLT-07, PLT-08, PLT-20: each student learns offline with the full tutor
                hardware = (await c.ok("GET", "/v1/models"))["hardware"]
                assert hardware["hardware_class"] == "low" and hardware["tutor_path"] == "local"
                for student in students:
                    learner_c = await opened(r, student)
                    await learns(learner_c)
                    assert (await tutor_turn(learner_c))["turn_id"]
                licence = await c.ok("GET", "/v1/licence")
                assert licence["entitlements"]["parent_summary"] is False  # no parent view on a lab install
                assert licence["entitlements"]["cloud_tier"] == "no"
            with run.step(5):  # PLT-20, PRV-02: a student's own progress, from the device; nothing leaves it
                ama = await opened(r, students[0])
                progress = await ama.ok("GET", "/v1/progress")
                assert "Kofi" not in json.dumps(progress)
                api = Api(r)
                reply, archive = await _export(api, ama.token or "", tmp_path / "printout", kind="profile_archive",
                                               profile_ids=[students[0]], passphrase=PASSPHRASE)  # fmt: skip
                assert reply.status_code == 202 and archive is not None and archive.stat().st_size > 0
                ledger = await ama.ok("GET", "/v1/connectivity/ledger")
                assert ledger["entries"] == [], "nothing left the device"
                run.note("the print itself is the client's: the Progress screen, printed by the operating system")
        finally:
            await stop_core(r)

    return probe


def _f1_disk_full(tmp_path: Path) -> JourneyProbe:
    """PLT-06, PLT-07, PLT-23: with too little free disk, installing from the USB kit through the core stops before
    copying with `storage_full`, naming the space needed and the space free, and leaves nothing partial."""
    provider = timed({})

    async def probe(run: Run) -> None:
        kit = lab_kit(tmp_path, model_bytes=512 * 1024)
        r = await lab_computer(tmp_path / "pc1", provider)
        try:
            needed = sum(p.stat().st_size for p in kit.rglob("*") if p.is_file())
            with_desk(r, free=lambda: needed // 4)  # the disk has a quarter of what the kit needs

            def model_files() -> list[str]:
                return sorted(p.relative_to(r.data_dir).as_posix() for p in (r.data_dir / "models").rglob("*")
                              if p.is_file()) if (r.data_dir / "models").exists() else []  # fmt: skip

            before = model_files()
            job = await from_kit(r, kit)
            assert job["state"] == "failed", job
            assert job["error"]["code"] == "storage_full", job
            assert "needed" in json.dumps(job["error"]), job  # the exact space needed is named
            assert model_files() == before, "nothing partial is left behind"
        finally:
            await stop_core(r)

    return probe


def _f2_quarantine(tmp_path: Path) -> JourneyProbe:
    """PLT-06, PLT-20: antivirus quarantines the model file: at the next start the app names the pack whose file is
    missing, with the damaged-file state; no damaged model is loaded; learning goes on; copying it again from the USB
    kit restores it."""
    provider = timed({})

    async def probe(run: Run) -> None:
        kit = lab_kit(tmp_path)
        r = await lab_computer(tmp_path / "pc1", provider)
        try:
            assert (await from_kit(r, kit))["state"] == "done"
            weights = next((r.data_dir / "models" / "packs").rglob("model.gguf"))
            weights.unlink()  # quarantined
            r = await next_start(r, provider)
            c = Client(r)
            catalogue = await c.ok("GET", "/v1/models")
            listed = [m for m in catalogue.get("installed", []) if MODEL_PACK in json.dumps(m)]
            assert listed, catalogue
            assert any(m.get("state") == "error" and m.get("error_code") == "model.damaged" for m in listed), listed
            assert r.runtime.plan is not None and r.runtime.plan["model"] is None, "no damaged model is loaded"
            learner_c = await opened(r, await add_by_name(r, "Ama"))
            await learns(learner_c)  # lessons and practice still work
            assert (await from_kit(r, kit))["state"] == "done"  # copied again from the USB kit
            again = await c.ok("GET", "/v1/models")
            restored = [m for m in again.get("installed", []) if m.get("model_pack_id") == MODEL_PACK]
            assert restored and all(m.get("state") == "installed" for m in restored), restored
        finally:
            await stop_core(r)

    return probe


def _f3_licence_fails(tmp_path: Path) -> JourneyProbe:
    """PLT-20, BIZ-09: the lab's licence file expires, then is replaced by an edited one: each time the device keeps
    the whole free offline product and every profile's data, and Help names what the licence contact must do."""
    provider = timed({})
    now = int(datetime(2026, 10, 13, 9, tzinfo=UTC).timestamp() * 1000)

    async def probe(run: Run) -> None:
        clock = [now]
        r = await lab_computer(tmp_path / "pc1", provider)
        try:
            assert (await from_kit(r, lab_kit(tmp_path)))["state"] == "done"
            r = await next_start(r, provider)
            attach(r, wall_ms=lambda: clock[0])
            file = issue_licence_file("lab_bundle", 20, expires_at=iso_ms(now + 30 * DAY_MS), now=iso_ms(now))
            assert (await Client(r).send("POST", "/v1/licence", {"licence_file": file})).status_code == 200
            students = [await add_by_name(r, name) for name in ("Ama", "Kofi")]
            kept = {}
            for student in students:
                learner_c = await opened(r, student)
                await learns(learner_c)
                kept[student] = await kc_states(learner_c)
            for failure in ("expired", "edited"):
                if failure == "expired":
                    clock[0] = now + 40 * DAY_MS  # the licence ends; it applies at the next start (PLT-20)
                else:
                    stored = json.loads((r.data_dir / "licence" / "licence.json").read_text())
                    stored["seats"] = 400
                    (r.data_dir / "licence" / "licence.json").write_text(json.dumps(stored))
                r = await next_start(r, provider)
                attach(r, wall_ms=lambda: clock[0])
                shown = await Client(r).ok("GET", "/v1/licence")
                assert shown["state"] == ("expired" if failure == "expired" else "invalid"), shown
                assert shown["offer"] == "free" and offline_part(shown["entitlements"]) == FRESH_OFFLINE, failure
                listed = [p["profile_id"] for p in (await Client(r).ok("GET", "/v1/profiles"))["profiles"]]
                assert listed == students, "no student is locked out"
                for student in students:
                    learner_c = await opened(r, student)
                    assert await kc_states(learner_c) == kept[student], "every profile's progress is kept"
                    await learns(learner_c)
                    kept[student] = await kc_states(learner_c)
                # Help, offline, names what the licence contact must do: get the school's current signed file.
                articles = (await Client(r).ok("GET", "/v1/help"))["articles"]
                (article,) = [a for a in articles if a["id"] == "licence"]
                assert [k for k in article["step_keys"] if "licence file" in EN[k]], article
        finally:
            await stop_core(r)

    return probe


# --- the cases, by journey and part (prd03_core_journeys_offline replays them) --------------------------------------

CASES: dict[tuple[str, str], Callable[[Path], JourneyProbe]] = {
    ("JRN-03", "main"): _first_run,
    ("JRN-03", "F1"): _f1_below_minimum,
    ("JRN-03", "F2"): _f2_model_loading,
    ("JRN-03", "F3"): _f3_power_cut,
    ("JRN-03", "F4"): _f4_skip_diagnostic,
    ("JRN-03", "F5"): _f5_cloud_tier,
    ("JRN-03", "F6"): _f6_nothing_to_forget,
    ("JRN-11", "main"): _lab_install,
    ("JRN-11", "F1"): _f1_disk_full,
    ("JRN-11", "F2"): _f2_quarantine,
    ("JRN-11", "F3"): _f3_licence_fails,
}
GAPS: dict[tuple[str, str], str] = {}


def _cases(journey: str) -> list[Any]:
    return [pytest.param(b, marks=pytest.mark.xfail(strict=True, reason=GAPS[(journey, b)]))
            if (journey, b) in GAPS else b for b in branches(journey)]  # fmt: skip


def jrn03_first_run_to_plan(tmp_path: Path) -> None:
    play("JRN-03", "main", CASES[("JRN-03", "main")](tmp_path))


@pytest.mark.parametrize("branch", _cases("JRN-03"))
def jrn03_failure_branches(branch: str, tmp_path: Path) -> None:
    play("JRN-03", branch, CASES[("JRN-03", branch)](tmp_path))


def jrn11_offline_install(tmp_path: Path) -> None:
    play("JRN-11", "main", CASES[("JRN-11", "main")](tmp_path))


@pytest.mark.parametrize("branch", _cases("JRN-11"))
def jrn11_failure_branches(branch: str, tmp_path: Path) -> None:
    play("JRN-11", branch, CASES[("JRN-11", branch)](tmp_path))


def plt06_kit_install_storage_full(tmp_path: Path) -> None:
    """PLT-06, PLT-23 (D104: POST /v1/packs/install checks free disk first): an install from the USB kit or from a
    file, through the core, with too little free disk ends its job failed with `storage_full`, its details naming
    `needed_bytes` and `free_bytes`, and leaves no file of it on disk."""

    async def scenario() -> None:
        kit = lab_kit(tmp_path, model_bytes=512 * 1024)
        r = await lab_computer(tmp_path / "pc1", timed({}))
        try:
            needed = sum(p.stat().st_size for p in kit.rglob("*") if p.is_file())
            with_desk(r, free=lambda: needed // 4)

            def on_disk() -> list[str]:
                return sorted(p.relative_to(r.data_dir).as_posix() for folder in ("packs", "models")
                              for p in (r.data_dir / folder).rglob("*") if p.is_file())  # fmt: skip

            before = on_disk()
            c = Client(r)
            for source in ({"kind": "usb", "path": str(kit)},
                           {"kind": "file", "path": str(kit / "packs" / "pack.phy.o.pack")}):  # fmt: skip
                reply = await c.send("POST", "/v1/packs/install", {"source": source})
                assert reply.status_code == 202, reply.text
                job = await job_end(c, reply.json()["job_id"])
                assert job["state"] == "failed" and job["error"]["code"] == "storage_full", (source, job)
                details = job["error"]["details"]
                assert details["free_bytes"] == needed // 4 and details["needed_bytes"] > details["free_bytes"], job
                assert on_disk() == before, f"nothing of {source['kind']} is left on disk"
        finally:
            await stop_core(r)

    asyncio.run(scenario())
