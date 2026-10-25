"""A signed scope-specific checkout grant, never an unsigned guardian checkbox or cloud-tier inference."""

from agent_core.config import Settings
from agent_core.store import consents, subscription
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from test_m10a_profiles import student
from test_m10e_consent import NOTICE, with_api
from test_m19b_api import entitlement


def test_pending_profile_does_not_disable_an_already_approved_profile():
    stored = {
        "profiles": ["approved_adult", "pending_learner"],
        "consent_needed": ["pending_learner"], "period_end": 2000, "ended_at": None,
    }
    assert subscription.state(stored, 1000) == "pending_consent"
    assert subscription.covers(stored, "approved_adult", 1000)
    assert not subscription.covers(stored, "pending_learner", 1000)
    assert not subscription.covers(stored, "uncovered_profile", 1000)
    assert not subscription.covers(stored, "approved_adult", 2000)
    assert not subscription.covers({**stored, "ended_at": 500}, "approved_adult", 1000)


def test_study_minor_checkout_scope_is_signed_and_separate(tmp_path):
    async def scenario(api, runtime):
        runtime.core.online = runtime.runtime.attach_online()
        runtime.core.entitlement_trust = dev_trust()
        minor = await api.add(student("Ama"))
        token = (await api.unlock(minor)).json()["profile_token"]
        evidence = [{"profile_id": minor, "actor_role": "guardian", "notice_version": "2026-10.m42-draft"}]
        runtime.core.notices["study_materials"] = ["2026-10.m42-draft"]
        cloud = entitlement([minor])
        apply = {"entitlement": cloud, "consents": [{"profile_id": minor, "notice_version": NOTICE}]}
        assert (await api.call("POST", "/v1/subscription", apply)).status_code == 200
        with runtime.runtime.directory.open_learner(minor) as conn:
            assert consents.active(conn, "cloud_tier") is not None
            assert consents.active(conn, "study_materials") is None
        forged = {**cloud, "study_material_consents": evidence}
        assert (await api.call("POST", "/v1/subscription", {**apply, "entitlement": forged})).status_code == 422
        unsigned = await api.call(
            "PUT",
            f"/v1/profiles/{minor}/consents/study_materials",
            {"action": "on", "guardian_agreed": True, "notice_version": "2026-10.m42-draft"},
            profile=token,
        )
        assert unsigned.status_code == 403
        assert runtime.runtime.online.notice_answer(minor, "study_materials") is None
        document = {k: v for k, v in forged.items() if k != "signature"}
        signed = dev_signer(Purpose.LICENCE).sign("licence_file", document, now=cloud["created_at"])
        response = await api.call("POST", "/v1/subscription", {**apply, "entitlement": signed})
        assert response.status_code == 200, response.text
        assert runtime.runtime.online.notice_answer(minor, "study_materials") == "accepted"
        with runtime.runtime.directory.open_learner(minor) as conn:
            grant = consents.active(conn, "study_materials")
            assert grant[1:4] == ("guardian", "checkout_guardian", "2026-10.m42-draft")
        # Reapplying the same signed document does not duplicate the scope's audit record.
        assert (await api.call("POST", "/v1/subscription", {**apply, "entitlement": signed})).status_code == 200
        with runtime.runtime.directory.open_learner(minor) as conn:
            assert conn.execute("SELECT count(*) FROM consents WHERE scope='study_materials'").fetchone()[0] == 1

    with_api(
        tmp_path,
        scenario,
        Settings(study_workspace_enabled=True, study_offline_enabled=True, consent_dpia_ref="synthetic-dpia"),
    )


def test_adult_study_agreement_records_scope_and_first_use(tmp_path):
    async def scenario(api, runtime):
        runtime.core.online = runtime.runtime.attach_online()
        adult = await api.add(student("Synthetic adult", age_band="18_plus"))
        token = (await api.unlock(adult)).json()["profile_token"]
        runtime.core.notices["study_materials"] = ["2026-10.m42-draft"]
        assert runtime.runtime.online.notice_answer(adult, "study_materials") is None
        response = await api.call(
            "PUT",
            f"/v1/profiles/{adult}/consents/study_materials",
            {"action": "on", "notice_version": "2026-10.m42-draft"},
            profile=token,
        )
        assert response.status_code == 200, response.text
        assert runtime.runtime.online.notice_answer(adult, "study_materials") == "accepted"
        with runtime.runtime.directory.open_learner(adult) as conn:
            assert consents.active(conn, "study_materials")[1] == "student_18_plus"

    with_api(tmp_path, scenario, Settings(study_workspace_enabled=True, consent_dpia_ref="synthetic-dpia"))
