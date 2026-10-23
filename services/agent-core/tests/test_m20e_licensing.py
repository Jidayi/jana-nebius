"""M20.e: licensing without activation, the subscription and the school licence file, entitlements and the
content-only tier (PLT-19, PLT-20, BIZ-01 to BIZ-04, BIZ-06, BIZ-09, SEC-28, PRD-04; D30, D70, D84, D86).

The offline product is free and needs no activation, code or licence check; paid online features go through the
subscription (D70); a school installs one signed licence file. Against the real core with a development-signed
physics pack built from the repository's sources, licence files from the signing service's issuer and subscription
entitlements signed by the test hierarchy's licence key. Learners and clocks are invented."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agent_core.config.environments import Environment
from agent_core.contracts import errors as contract_errors
from agent_core.store.entitlements import OFFLINE, check_table, entitlements, table
from agent_core.store.events import iso_ms
from agent_core.store.licence import LicenceRefused, read_file
from api_harness import cli, stop_core
from jana_tools import REPO_ROOT
from jana_tools.harness.egress import offline_run
from licence_harness import (
    DAY_MS,
    NOTICE,
    SETTINGS,
    answer,
    attach,
    core,
    kc_states,
    learner,
    lesson_items,
    seed_progress,
    subscribe,
)
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from signing_service.licences import issue_licence_file
from test_m10a_profiles import Api, code, student
from test_m10d_deletion_export import PASSPHRASE, _export
from test_m13g_learn import SPEED, Client, item_record, key_answer, mastery, source

NOW = int(datetime(2026, 10, 13, 9, tzinfo=UTC).timestamp() * 1000)
EN = json.loads((REPO_ROOT / "packages" / "i18n" / "locales" / "en.json").read_text())
# A shipped objective physics mock (M16) in the development-signed pack, answered with the item keys.
MOCK_PAPER = next(p for p in source("phy")["mock_papers"] if p["id"] == "mck.phy.o.0001")
FRESH_OFFLINE = {name: True for name in OFFLINE} | {"content_updates": "all", "student_profiles": "all"}


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def status_errors(found: Any) -> list[str]:
    return contract_errors("api/commands#/$defs/LicenceStatus", found)


def offline_part(granted: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in granted.items() if k in FRESH_OFFLINE}


async def install_file(c: Client, document: dict[str, Any]) -> Any:
    return await c.send("POST", "/v1/licence", {"licence_file": document})


async def check(c: Client, lesson_id: str, item_id: str) -> Any:
    body = {"client_attempt_id": cli(), "item_id": item_id,
            "answer": key_answer(item_record("phy", item_id)), "time_ms": 9000}  # fmt: skip
    return await c.send("POST", f"/v1/lessons/{lesson_id}/checks", body)


def below(kc_ids: set[str]) -> set[str]:
    """`kc_ids` and every KC under them by prerequisite links, where a success's implied evidence flows (LRN-10)."""
    edges = [(k["id"], p["kc_id"]) for k in source("phy")["kcs"] for p in k.get("prerequisites") or []]
    found, grown = set(kc_ids), True
    while grown:
        more = {b for a, b in edges if a in found}
        grown = not more <= found
        found |= more
    return found


async def sit(c: Client, exam_id: str, question: dict[str, Any]) -> None:
    """One mock question answered with its item's key, saved during the sitting."""
    body = {"answer": key_answer(item_record("phy", question["item_id"])), "flagged": False}
    await c.ok("PUT", f"/v1/mocks/{exam_id}/answers/{question['question_id']}", body)


def practice_key(item_id: str) -> dict[str, Any]:
    """A practice item's own key as the student's answer, for every answer kind the physics pack's items use."""
    item = item_record("phy", item_id)
    parts = key_answer(item)["parts"]
    for part in item["parts"]:
        key = part["answer"]
        if key["kind"] == "multi_select":
            chosen = [o["id"] for o in key["options"] if o["correct"]]
            parts.append({"part_id": part["id"], "kind": "multi_select", "option_ids": chosen})
        elif key["kind"] == "ordering":
            parts.append({"part_id": part["id"], "kind": "ordering", "element_ids": list(key["correct_order"])})
    return {"parts": parts}


async def cloud_on(api: Api) -> bool:
    return bool((await api.call("GET", "/v1/connectivity")).json()["features"]["cloud_tier"]["enabled"])


# --- PLT-19 ----------------------------------------------------------------------------------------------------------


def plt19_free_without_activation(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path)
        try:
            with offline_run() as egress:
                *_, token = await learner(r)
                c = Client(r, token)
                shown = await c.ok("GET", "/v1/licence")
                (lesson_id, item_id), *_ = await lesson_items(c)
                assert (await answer(c, lesson_id, item_id))["verdict"] == "correct"
            assert egress.attempts == []
            assert status_errors(shown) == []
            assert (shown["state"], shown["offer"], shown["install_kind"]) == ("none", "free", "family")
            assert offline_part(shown["entitlements"]) == FRESH_OFFLINE  # every offline feature, nothing typed
        finally:
            await stop_core(r)

    run(scenario())


def plt19_no_activation_codes(tmp_path: Path) -> None:
    """No screen, command or setting accepts a typed activation or reply code: none is served, proposed, declared or
    worded, and the licence command takes only a school's signed file."""
    from agent_core.config.keys import Settings as Keys
    from agent_core.contracts import document
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    words = ("/activat", "activation", "reply_code", "reply-code", "device_code", "device-code")
    assert not [p for p in ENDPOINTS_BY_KEY if any(w in p for w in words)]
    definitions = document("api/commands")["$defs"]
    licensing = ("Entitlements", "LicenceStatus", "LicenceInstall", "SetupState", "SetupStep")
    assert not [d for d in licensing if any(w in json.dumps(definitions[d]) for w in words)]
    assert not [k for k in Keys.model_fields if any(w in k for w in words)]
    assert not [k for k, v in EN.items() if any(w in v.lower() for w in ("activation", "reply code", "device code"))]

    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            served = {getattr(route, "path", "") for route in r.server.config.app.app.app.routes} if r.server else set()
            assert served and not [p for p in served if any(w in p for w in words)]
            c = Client(r)
            typed = await c.send("POST", "/v1/licence", {"reply_code": "ABCD-EFGH-JKMN"})
            assert typed.status_code == 422 and code(typed) == "validation_failed"
            assert (await c.ok("GET", "/v1/licence"))["state"] == "none"
        finally:
            await stop_core(r)

    run(scenario())


def plt19_school_licence_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        lab = [await core(tmp_path / f"pc{i}", worker=False) for i in range(3)]
        try:
            file = issue_licence_file("school_seat", 2, expires_at="2027-12-31T23:59:59.999Z")  # copied from the kit
            with offline_run() as egress:
                for r in lab:
                    applied = (await install_file(Client(r), file)).json()
                    assert status_errors(applied) == []
                    assert (applied["state"], applied["install_kind"], applied["seats"]) == ("active", "school_lab", 2)
                    assert offline_part(applied["entitlements"]) == FRESH_OFFLINE
                    assert attach(lab[0]).state.status == "active"  # verified again at the next start
            assert egress.attempts == []
            # A tampered file is refused, changes nothing, and the device keeps the whole offline product.
            spare = await core(tmp_path / "spare", worker=False)
            try:
                c = Client(spare)
                refused = await install_file(c, {**file, "seats": 300})
                assert code(refused) == "validation_failed" and refused.json()["error"]["details"] == {
                    "reason": "invalid"
                }
                wrong_key = dev_signer(Purpose.CONTENT).sign("content_pack", {k: v for k, v in file.items()
                                                                              if k != "signature"})  # fmt: skip
                assert code(await install_file(c, wrong_key)) == "validation_failed"
                shown = await c.ok("GET", "/v1/licence")
                assert (shown["state"], shown["install_kind"]) == ("none", "family")
                assert offline_part(shown["entitlements"]) == FRESH_OFFLINE
            finally:
                await stop_core(spare)
        finally:
            for r in lab:
                await stop_core(r)

    run(scenario())


def test_install_takes_only_a_licence_file() -> None:
    from agent_core.contracts import document

    install = document("api/commands")["$defs"]["LicenceInstall"]
    assert install["required"] == ["licence_file"] and list(install["properties"]) == ["licence_file"]


# --- PLT-20 ----------------------------------------------------------------------------------------------------------


def plt20_expiry_never_interrupts(tmp_path: Path) -> None:
    """The subscription ends while an M16 mock sitting is in progress: the remaining answers are still accepted and the
    submitted sitting is marked in full, and at the next start the cloud tier is off while the local tutor, every
    offline feature and all progress remain."""

    async def scenario() -> None:
        r = await core(tmp_path)
        try:
            api, profile, token = await learner(r)
            c = Client(r, token)
            questions = [q for s in MOCK_PAPER["sections"] for q in s["questions"]]
            # Earlier learning on two KCs the sitting's evidence cannot reach: its correct answers re-derive the KCs
            # it marks and their prerequisites, where progress seeded in the projection alone would be replaced.
            assessed = {k for q in questions for k in q["kc_ids"]}
            earlier = sorted(k for k in await kc_states(c) if k not in below(assessed))[:2]
            mastery(r, earlier[0], "mastered")
            mastery(r, earlier[1], "moved_on")
            assert (await subscribe(api, [profile])).json()["state"] == "active"
            assert await cloud_on(api)
            (lesson_id, item_id), *_ = await lesson_items(c)
            exam = await c.ok("POST", "/v1/mocks", {"client_exam_id": cli(), "paper_id": MOCK_PAPER["id"]})
            eid = exam["exam_id"]
            await c.ok("POST", f"/v1/mocks/{eid}/start", {})  # the sitting starts
            assert code(await check(c, lesson_id, item_id)) == "tutor_locked"  # a real sitting (AGT-24)
            half = len(questions) // 2
            for question in questions[:half]:
                await sit(c, eid, question)
            assert (await api.call("DELETE", "/v1/subscription")).status_code == 200
            for question in questions[half:]:
                await sit(c, eid, question)  # every remaining answer is accepted
            report = await c.ok("POST", f"/v1/mocks/{eid}/submit", {})
            assert report["unanswered"] == []
            assert report["score"] == MOCK_PAPER["total_marks"]  # marked to the end, in full
            states = await kc_states(c)
            assert (states[earlier[0]], states[earlier[1]]) == ("mastered", "moved_on")
            assert all(states[k] != "not_started" for k in assessed)  # the sitting's evidence reached learning
        finally:
            await stop_core(r)
        again = await core(tmp_path)  # the next app start
        try:
            api = Api(again)
            c = Client(again, await api.token(profile))
            shown = await c.ok("GET", "/v1/licence")
            assert not await cloud_on(api)
            assert shown["entitlements"]["cloud_tier"] == "available"
            assert offline_part(shown["entitlements"]) == FRESH_OFFLINE  # the local tutor and every offline feature
            assert await kc_states(c) == states  # progress intact
            assert (await c.ok("GET", f"/v1/mocks/{eid}"))["state"] == "marked"  # the marked sitting with it
        finally:
            await stop_core(again)

    run(scenario())


def plt20_no_offline_limits(tmp_path: Path) -> None:
    async def scenario() -> None:
        found = {}
        for name in ("none", "expired", "damaged"):
            clock = [NOW]
            r = await core(tmp_path / name, wall_ms=lambda clock=clock: clock[0], worker=False)
            try:
                folder = r.data_dir / "licence"
                folder.mkdir(exist_ok=True)
                if name == "expired":
                    document = issue_licence_file("school_seat", 9, expires_at=iso_ms(NOW - DAY_MS),
                                                  now=iso_ms(NOW - 30 * DAY_MS))  # fmt: skip
                    (folder / "licence.json").write_text(json.dumps(document))
                elif name == "damaged":
                    (folder / "licence.json").write_text("{not json")
                attach(r, wall_ms=lambda clock=clock: clock[0])
                found[name] = offline_part((await Client(r).ok("GET", "/v1/licence"))["entitlements"])
            finally:
                await stop_core(r)
        assert found == {"none": FRESH_OFFLINE, "expired": FRESH_OFFLINE, "damaged": FRESH_OFFLINE}

    run(scenario())


def test_clock_changes_never_expire_early_and_never_extend(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = [NOW]
        r = await core(tmp_path, wall_ms=lambda: clock[0], worker=False)
        try:
            c = Client(r)
            file = issue_licence_file("school_seat", 5, expires_at=iso_ms(NOW + 180 * DAY_MS), now=iso_ms(NOW))
            assert (await install_file(c, file)).json()["state"] == "active"
            clock[0] = NOW + 2 * 365 * DAY_MS  # the clock jumps two years ahead
            assert attach(r, wall_ms=lambda: clock[0]).state.status == "active"
            clock[0] = NOW + 400 * DAY_MS  # after several starts the trusted time catches up and the licence ends
            states = [attach(r, wall_ms=lambda: clock[0]).state.status for _ in range(6)]
            assert states[-1] == "expired"
            clock[0] = NOW  # setting the clock back does not bring it back
            back = attach(r, wall_ms=lambda: clock[0]).state
            assert back.status == "expired" and back.clock_behind
        finally:
            await stop_core(r)

    run(scenario())


# --- BIZ-01 ----------------------------------------------------------------------------------------------------------


def biz01_no_local_question_metering() -> None:
    assert check_table(table()) == []
    for column in ("every_install", "school_lab"):
        assert not any(word in json.dumps(table()[column]) for word in ("question", "turn", "token")), column
    assert table()["every_install"]["local_tutor"] == "yes"  # a feature, never a count
    seeded = copy.deepcopy(table())
    seeded["every_install"]["local_questions_per_day"] = "yes"
    assert any("never metered" in p for p in check_table(seeded))
    seeded = copy.deepcopy(table())
    seeded["every_install"]["local_tutor"] = "100_turns"
    assert any("never metered" in p for p in check_table(seeded))


# --- BIZ-02 ----------------------------------------------------------------------------------------------------------


def biz02_free_tier_offline(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path)
        try:
            with offline_run() as egress:
                *_, token = await learner(r)
                c = Client(r, token)
                shown = await c.ok("GET", "/v1/licence")
                assert (shown["state"], shown["offer"]) == ("none", "free")
                assert offline_part(shown["entitlements"]) == FRESH_OFFLINE  # nothing counted or capped
                assert shown["entitlements"]["parent_summary"] is True
                items = await lesson_items(c)
                lesson_id = items[0][0]
                assert (await c.ok("GET", f"/v1/lessons/{lesson_id}"))["blocks"]
                checked = []
                for lesson_id, item_id in items[:12]:  # practice with no daily cap
                    marked = await answer(c, lesson_id, item_id)
                    assert marked["verdict"] == "correct"
                    checked += [bool(p["check_ids"]) for p in marked["parts"]]
                assert any(checked)  # numeric answers are checked by the tools
                seed_progress(r)
                assert (await kc_states(c))[SPEED] == "mastered"  # progress and mastery are shown
            assert egress.attempts == []
        finally:
            await stop_core(r)

    run(scenario())


def biz02_expiry_keeps_data(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            api, profile, token = await learner(r)
            c = Client(r, token)
            before_offline = offline_part((await c.ok("GET", "/v1/licence"))["entitlements"])
            await subscribe(api, [profile])
            seed_progress(r)
            before = await kc_states(c)
            events = r.runtime.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0]
            ended = await api.call("DELETE", "/v1/subscription")
            assert ended.json()["state"] == "ended"
            token = await api.token(profile)
            c = Client(r, token)
            assert offline_part((await c.ok("GET", "/v1/licence"))["entitlements"]) == before_offline
            assert await kc_states(c) == before
            assert r.runtime.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] >= events
        finally:
            await stop_core(r)

    run(scenario())


def biz02_no_offline_limits() -> None:
    assert check_table(table()) == []
    for cell in OFFLINE:
        assert table()["every_install"][cell] == "yes", cell
        assert cell not in table()["school_lab"], cell
    seeded = copy.deepcopy(table())
    seeded["every_install"]["practice"] = "20_per_day"
    assert any("no limit" in p for p in check_table(seeded))
    seeded = copy.deepcopy(table())
    seeded["every_install"]["mock_exam_allowance"] = "yes"
    assert any("no limit" in p for p in check_table(seeded))
    seeded = copy.deepcopy(table())
    seeded["school_lab"]["local_tutor"] = "yes"
    assert any("never changes an offline feature" in p for p in check_table(seeded))
    from agent_core.config.keys import Settings as Keys

    assert not [k for k in Keys.model_fields if k.startswith("free_tier")]


# --- BIZ-03 ----------------------------------------------------------------------------------------------------------


def biz03_subscription_unlocks_online_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            api, ama, _ = await learner(r)
            kofi = await api.add(student("Kofi"))
            before = (await Client(r).ok("GET", "/v1/licence"))["entitlements"]
            done = await subscribe(api, [ama, kofi])  # nothing typed: the checkout's signed entitlement
            assert done.json()["state"] == "active" and await cloud_on(api)
            for profile in (ama, kofi):  # the guardian's consent, recorded for each profile under 18
                with r.runtime.directory.open_learner(profile) as conn:
                    from agent_core.store import consents as consent_store

                    assert consent_store.active(conn, "cloud_tier")[1] == "guardian"
            after = (await Client(r).ok("GET", "/v1/licence"))["entitlements"]
            assert after["cloud_tier"] == "subscribed" and before["cloud_tier"] == "available"
            assert offline_part(after) == offline_part(before)  # nothing offline depends on it
        finally:
            await stop_core(r)

    run(scenario())


def biz03_lapsed_subscription_keeps_offline(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path)
        try:
            api, profile, token = await learner(r)
            seed_progress(r)
            lapsing = await subscribe(api, [profile], period_end=iso_ms(int(datetime.now(UTC).timestamp() * 1000)
                                                                               + 1500))  # fmt: skip
            assert lapsing.json()["state"] == "active"
            await asyncio.sleep(2)  # the period ends
            c = Client(r, token)
            shown = await c.ok("GET", "/v1/licence")
            assert shown["entitlements"]["cloud_tier"] == "available"
            assert offline_part(shown["entitlements"]) == FRESH_OFFLINE
            assert (await c.ok("GET", "/v1/curriculum/cur.phy.o/map"))["status"] == "ready"  # installed packs
            (lesson_id, item_id), *_ = await lesson_items(c)
            assert (await answer(c, lesson_id, item_id))["verdict"] == "correct"
            assert (await kc_states(c))[SPEED] == "mastered"  # learner data
        finally:
            await stop_core(r)

    run(scenario())


def test_subscription_shows_this_months_allowance_used_up(tmp_path: Path) -> None:
    """BIZ-07, D33: the subscription's view tells the open profile whether this month's allowance is used up; the
    tokens metered in an earlier allowance month do not count."""
    from agent_core.store import subscription as subscriptions
    from agent_core.store.egress import DeviceSpend

    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            api, profile, _ = await learner(r)
            assert (await subscribe(api, [profile])).status_code == 200
            device = r.core.directory.device
            stored = subscriptions.load(device)
            now = r.core.clock_ms()
            index = subscriptions.allowance_window(stored, now)[0]
            assert index > 0  # the harness's paid period began in an earlier month
            earlier = f"{stored['subscription_id']}#m{index - 1}"
            DeviceSpend(device, profile, earlier, r.core.clock_ms).add("2026-09-30", 1.0, stored["allowance_tokens"])
            shown = await api.call("GET", "/v1/subscription", profile=await api.token(profile))
            assert shown.json()["allowance_used_up"] is False
            current = subscriptions.allowance_period(stored, now)
            DeviceSpend(device, profile, current, r.core.clock_ms).add("2026-10-16", 1.0, stored["allowance_tokens"])
            shown = await api.call("GET", "/v1/subscription", profile=await api.token(profile))
            assert shown.json()["allowance_used_up"] is True and shown.json()["state"] == "active"
        finally:
            await stop_core(r)

    run(scenario())


# --- BIZ-04 ----------------------------------------------------------------------------------------------------------


def biz04_one_licence_file_no_activation(tmp_path: Path) -> None:
    async def scenario() -> None:
        lab = [await core(tmp_path / f"pc{i}", worker=False) for i in range(3)]
        try:
            batch = issue_licence_file("school_seat", 2)  # two seats bought, three computers
            with offline_run() as egress:
                for r in lab:  # no hub, staff login or code: the file alone
                    applied = (await install_file(Client(r), batch)).json()
                    assert (applied["state"], applied["install_kind"]) == ("active", "school_lab")
                    assert offline_part(applied["entitlements"]) == FRESH_OFFLINE
            assert egress.attempts == []
            with pytest.raises(ValueError, match="at least one"):
                issue_licence_file("school_seat", 0)
            forged = dev_signer(Purpose.LICENCE).sign("licence_file", {**batch, "policy": {"study_hours": "never"}})
            with pytest.raises(LicenceRefused, match="configuration"):
                read_file(forged, dev_trust(), Environment.DEV)
        finally:
            for r in lab:
                await stop_core(r)

    run(scenario())


def test_school_seat_licences_are_set_aside() -> None:
    """D10 (decided in D100): school seats are neither defined nor sold, so a key other than the test hierarchy's signs
    no school seat file; a lab bundle file, which makes a lab install (JRN-11), is still signed."""
    from dataclasses import replace

    from signing_service.hierarchy import Signer, SigningRefused

    test_key = dev_signer(Purpose.LICENCE)
    other_key = Signer(replace(test_key.certificate, key_id="lic-not-the-test-hierarchy"), test_key.sign_bytes)
    with pytest.raises(SigningRefused, match="set aside"):
        issue_licence_file("school_seat", 30, signer=other_key)
    assert issue_licence_file("lab_bundle", 30, signer=other_key)["kind"] == "lab_bundle"


# --- BIZ-06 ----------------------------------------------------------------------------------------------------------

# TABLE BIZ-06a by column: every install (free, offline), with the subscription, and with a school licence file.
ONLINE = ("cloud_tier", "study_materials", "cloud_backup", "multi_device", "parent_remote_view", "web_client")
EXPECTED: dict[str, dict[str, Any]] = {
    "every_install": {**FRESH_OFFLINE, "parent_summary": True, **dict.fromkeys(ONLINE, "available")},
    "subscription": {**FRESH_OFFLINE, "parent_summary": True, **dict.fromkeys(ONLINE, "subscribed")},
    "school_licence_file": {**FRESH_OFFLINE, "parent_summary": False, **dict.fromkeys(ONLINE, "no")},
}  # fmt: skip


def biz06_entitlements_match_table(tmp_path: Path) -> None:
    assert entitlements("family", False) == EXPECTED["every_install"]
    assert entitlements("family", True) == EXPECTED["subscription"]
    assert entitlements("school_lab", True) == EXPECTED["school_licence_file"]  # no subscription on a lab install

    async def scenario() -> None:
        for column in EXPECTED:
            r = await core(tmp_path / column, worker=False)
            try:
                api, profile, _ = await learner(r)
                with offline_run() as egress:
                    if column == "subscription":
                        assert (await subscribe(api, [profile])).status_code == 200
                    elif column == "school_licence_file":
                        await install_file(Client(r), issue_licence_file("lab_bundle", 10))
                    shown = await Client(r).ok("GET", "/v1/licence")
                assert egress.attempts == []
                assert shown["entitlements"] == EXPECTED[column], column
                assert status_errors(shown) == []
            finally:
                await stop_core(r)

    run(scenario())


def jrn11_lab_no_guardian_scope(tmp_path: Path) -> None:
    """On a school_lab install no online guardian scope can be granted: no subscription, and no online consent for a
    minor or an 18+ student (PRV-06, JRN-11). A research scope stays recordable there (D100,
    `prv06_lab_research_consent_recordable`). Parent digests and alerts are not built yet (TCH-12, TCH-14)."""

    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            api, profile, _ = await learner(r)
            grown = await api.add(student("Esi", age_band="18_plus"))
            await install_file(Client(r), issue_licence_file("lab_bundle", 20))
            assert code(await subscribe(api, [profile])) == "feature_disabled"
            for who in (profile, grown):  # one profile open at a time
                key = await api.token(who)
                online = await api.call("PUT", f"/v1/profiles/{who}/consents/cloud_tier",
                                        {"action": "on", "notice_version": NOTICE, "guardian_agreed": True},
                                        profile=key)  # fmt: skip
                assert code(online) == "feature_disabled", who
                consents = (await api.call("GET", f"/v1/profiles/{who}/consents", profile=key)).json()
                assert not any(c["granted"] for c in consents), who
        finally:
            await stop_core(r)

    run(scenario())


def prv06_lab_research_consent_recordable(tmp_path: Path) -> None:
    """On a school_lab install a research scope is recorded through the study screen's agreement as on a family
    install (D13, D100): the guardian's in-app agreement for a minor (with the student's assent), the student's own at
    18+, and a research export then runs. It unlocks nothing online: the cloud tier stays refused and off."""
    from test_m10d_deletion_export import STUDY, _public

    settings = SETTINGS.model_copy(update={"export_research_public_key": _public(STUDY)})

    async def scenario() -> None:
        r = await core(tmp_path, worker=False, settings=settings)
        try:
            api, minor, _ = await learner(r)
            grown = await api.add(student("Esi", age_band="18_plus"))
            await install_file(Client(r), issue_licence_file("lab_bundle", 20))
            assert (await Client(r).ok("GET", "/v1/licence"))["install_kind"] == "school_lab"
            grown_token = await api.token(grown)
            own = await api.call("PUT", f"/v1/profiles/{grown}/consents/research_use",
                                 {"action": "on", "notice_version": NOTICE}, profile=grown_token)  # fmt: skip
            assert own.status_code == 200 and own.json()["granted_by_role"] == "student_18_plus"
            token = await api.token(minor)
            path = f"/v1/profiles/{minor}/consents/research_use"
            alone = await api.call("PUT", path, {"action": "on", "notice_version": NOTICE}, profile=token)
            assert code(alone) == "validation_failed"  # the student cannot grant it alone
            agreed = await api.call("PUT", path, {"action": "on", "notice_version": NOTICE, "guardian_agreed": True},
                                    profile=token)  # fmt: skip
            assert agreed.status_code == 200, agreed.text
            assert agreed.json()["granted_by_role"] == "guardian" and agreed.json()["effective"]
            with r.runtime.directory.open_learner(minor) as conn:
                methods = conn.execute("SELECT scope, method FROM consents WHERE withdrawn_at IS NULL").fetchall()
            assert methods == [("research_use", "in_app_guardian")]
            folder = tmp_path / "usb"
            folder.mkdir()
            approval = {"student_assent": True, "school_approval_ref": "synthetic-school-approval",
                        "protocol_ref": "synthetic-registered-protocol"}  # fmt: skip
            export = await api.call("POST", "/v1/exports", {"kind": "research_export", "profile_ids": [minor],
                                                            "destination": {"kind": "file", "path": str(folder)},
                                                            "research_approval": approval}, profile=token)  # fmt: skip
            assert export.status_code == 202, export.text
            for who in (minor, grown):  # nothing online follows from it
                key = await api.token(who)
                online = await api.call("PUT", f"/v1/profiles/{who}/consents/cloud_tier",
                                        {"action": "on", "notice_version": NOTICE, "guardian_agreed": True},
                                        profile=key)  # fmt: skip
                assert code(online) == "feature_disabled", who
            assert code(await subscribe(api, [minor])) == "feature_disabled"
            assert not await cloud_on(api)
        finally:
            await stop_core(r)

    run(scenario())


# --- BIZ-09 ----------------------------------------------------------------------------------------------------------


def biz09_licence_failures_degrade_to_free(tmp_path: Path) -> None:
    """No licence file, expired, damaged, edited, clock set back and the subscription ended: in each the student still
    opens lessons, practises and gets an export of their data."""

    async def failing(name: str, r: Any) -> None:
        folder = r.data_dir / "licence"
        folder.mkdir(exist_ok=True)
        document: dict[str, Any] | None = None
        if name == "expired":
            document = issue_licence_file("school_seat", 9, expires_at=iso_ms(NOW - DAY_MS),
                                          now=iso_ms(NOW - 30 * DAY_MS))  # fmt: skip
        elif name == "edited":
            document = {**issue_licence_file("school_seat", 9, expires_at=iso_ms(NOW - DAY_MS)), "expires_at": None}
        elif name == "clock_set_back":
            document = issue_licence_file("school_seat", 9, expires_at=iso_ms(NOW + DAY_MS), now=iso_ms(NOW - DAY_MS))
        if name == "damaged":
            (folder / "licence.json").write_text("{not json")
        elif document is not None:
            (folder / "licence.json").write_text(json.dumps(document))

    expected = {"none": "none", "expired": "expired", "damaged": "invalid", "edited": "invalid",
                "clock_set_back": "expired", "subscription_ended": "none"}  # fmt: skip

    async def scenario() -> None:
        for name, state in expected.items():
            clock = [NOW]
            r = await core(tmp_path / name, wall_ms=lambda clock=clock: clock[0])
            try:
                api, profile, token = await learner(r)
                await failing(name, r)
                if name == "subscription_ended":
                    await subscribe(api, [profile])
                    await api.call("DELETE", "/v1/subscription")
                    token = await api.token(profile)
                if name == "clock_set_back":  # seen at a later date once, then the clock is set back before expiry
                    clock[0] = NOW + 10 * DAY_MS
                    attach(r, wall_ms=lambda clock=clock: clock[0])
                    clock[0] = NOW - 5 * DAY_MS
                desk = attach(r, wall_ms=lambda clock=clock: clock[0])  # the next start
                c = Client(r, token)
                shown = await c.ok("GET", "/v1/licence")
                assert (shown["state"], shown["offer"]) == (state, "free"), name
                assert desk.state.status == state
                assert offline_part(shown["entitlements"]) == FRESH_OFFLINE, name
                (lesson_id, item_id), *_ = await lesson_items(c)
                assert (await c.ok("GET", f"/v1/lessons/{lesson_id}"))["blocks"], name
                assert (await answer(c, lesson_id, item_id))["verdict"] == "correct", name
                reply, archive = await _export(api, token, tmp_path / f"{name}-usb", kind="profile_archive",
                                               profile_ids=[profile], passphrase=PASSPHRASE)  # fmt: skip
                assert reply.status_code == 202 and archive is not None and archive.stat().st_size > 0, name
            finally:
                await stop_core(r)

    run(scenario())


# --- SEC-28 ----------------------------------------------------------------------------------------------------------


def test_licence_file_is_checked_locally_and_names_no_computer(tmp_path: Path) -> None:
    """SEC-28: the signature and the expiry are checked on the device with no network; editing the stored file makes
    it invalid at the next start (the whole offline product stays, never a lock-out); no hardware binding."""

    async def scenario() -> None:
        r = await core(tmp_path, worker=False)
        try:
            with offline_run() as egress:
                await install_file(Client(r), issue_licence_file("school_seat", 4))
            assert egress.attempts == []
            stored = json.loads((tmp_path / "licence" / "licence.json").read_text())
            assert "device_binding" not in stored
            stored["seats"] = 400
            (tmp_path / "licence" / "licence.json").write_text(json.dumps(stored))
            state = attach(r).state
            assert state.status == "invalid"
            assert offline_part(state.view()["entitlements"]) == FRESH_OFFLINE
        finally:
            await stop_core(r)

    run(scenario())


# --- PRD-04 ----------------------------------------------------------------------------------------------------------


def prd04_content_only_core_loop(tmp_path: Path) -> None:
    """The content-only class (no tutor model at all, no network): a lesson read to its end with its quick checks, ten
    practice items marked instantly, a mock sitting chosen from the paper list, sat, submitted and marked, and the
    subject map's mastery updated by that evidence."""

    async def scenario() -> None:
        r = await core(tmp_path)
        r.runtime.providers.clear()  # the content-only class: no tutor model at all
        r.core.readiness = "degraded"
        try:
            with offline_run() as egress:
                _, _, token = await learner(r)
                c = Client(r, token)
                before = await kc_states(c)
                items = await lesson_items(c)
                lesson_id = items[0][0]
                lesson = await c.ok("GET", f"/v1/lessons/{lesson_id}")
                await c.ok("PUT", f"/v1/lessons/{lesson_id}/position",
                           {"block_index": len(lesson["blocks"]) - 1, "lesson_version": lesson["version"]})  # fmt: skip
                for lesson_id, item_id in items[:3]:
                    assert (await answer(c, lesson_id, item_id))["verdict"] == "correct"  # the lesson's quick checks
                practice = await c.ok("POST", "/v1/practice/sets", {"client_set_id": cli(), "subject": "physics",
                                                                    "size": 10, "source": "adaptive"})  # fmt: skip
                marked = []
                for _ in range(10):
                    item = practice["current_item"]
                    assert item is not None, "ten practice items are offered"
                    body = {"client_attempt_id": cli(), "item_id": item["item_id"], "time_ms": 9000, "hints_used": 0,
                            "answer": practice_key(item["item_id"])}  # fmt: skip
                    reply = await c.ok("POST", f"/v1/practice/sets/{practice['set_id']}/answers", body)
                    marked.append(reply["verdict"])
                    practice = {**practice, "current_item": reply["next_item"]}
                assert marked == ["correct"] * 10  # each marked at once, with no model
                offered = await c.ok("GET", "/v1/mocks")
                assert MOCK_PAPER["id"] in {p["paper_id"] for p in offered["papers"]}
                exam = await c.ok("POST", "/v1/mocks", {"client_exam_id": cli(), "paper_id": MOCK_PAPER["id"]})
                eid = exam["exam_id"]
                await c.ok("POST", f"/v1/mocks/{eid}/start", {})
                questions = [q for s in MOCK_PAPER["sections"] for q in s["questions"]]
                for question in questions:
                    await sit(c, eid, question)
                report = await c.ok("POST", f"/v1/mocks/{eid}/submit", {})
                assert report["score"] == MOCK_PAPER["total_marks"] and report["unanswered"] == []
                listed = await c.ok("GET", "/v1/mocks")
                assert [(s["exam_id"], s["state"]) for s in listed["sittings"]] == [(eid, "marked")]
                after = await kc_states(c)
                assessed = {k for q in questions for k in q["kc_ids"]}
                assert all(after[k] != "not_started" for k in assessed)  # the sitting's evidence shows as mastery
                assert after != before
            assert egress.attempts == []
        finally:
            await stop_core(r)

    run(scenario())


def prd04_model_crash_degrades_gracefully(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await core(tmp_path)
        try:
            _, _, token = await learner(r)
            c = Client(r, token)
            seed_progress(r)
            items = await lesson_items(c)
            for lesson_id, item_id in items[:3]:
                assert (await answer(c, lesson_id, item_id))["verdict"] == "correct"
            # The model runtime dies mid-practice.
            r.runtime.providers.clear()
            r.core.readiness, r.core.components["runtime"] = "degraded", "down"
            for lesson_id, item_id in items[3:6]:
                assert (await answer(c, lesson_id, item_id))["verdict"] == "correct"
            health = (await c.get("/v1/health")).json()
            assert health["components"]["runtime"] == "down"
            assert (await kc_states(c))[SPEED] == "mastered"  # progress stays readable
        finally:
            await stop_core(r)

    run(scenario())


def test_licence_file_outside_its_contract_is_invalid() -> None:
    """A licence file signed by the licence key but carrying a field the `SchoolLicenceFile` contract does not list
    is refused as `invalid` (D39), as is one missing a field it requires; the issued file matches the contract."""
    issued = issue_licence_file("school_seat", 3)
    assert contract_errors("ops/licence#/$defs/SchoolLicenceFile", issued) == []
    assert read_file(issued, dev_trust(), Environment.DEV).seats == 3
    unsigned = {k: v for k, v in issued.items() if k != "signature"}
    extra = dev_signer(Purpose.LICENCE).sign("licence_file", {**unsigned, "school_name": "Hilltop"})
    short = dev_signer(Purpose.LICENCE).sign("licence_file", {k: v for k, v in unsigned.items() if k != "features"})
    for document in (extra, short):
        with pytest.raises(LicenceRefused, match="contract") as refused:
            read_file(document, dev_trust(), Environment.DEV)
        assert refused.value.reason == "invalid"
