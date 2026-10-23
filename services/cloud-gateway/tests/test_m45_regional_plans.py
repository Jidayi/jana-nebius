"""BIZ-18 (D121, superseding D10's single US$20 price): TABLE BIZ-18a's regional prices, what each plan gives, and one
allowance with no model picker. The figures below are copied from TABLE BIZ-18a itself, so a change to `plans.toml`
that drifts from the specification fails here."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config.environments import Environment
from agent_core.store import subscription as device_subscription
from agent_core.store.events import ms_from_iso
from cloud_gateway import plans, tier
from cloud_gateway.config import Limits, Plan, Plans, Tier, load_config
from cloud_gateway.contracts import errors as contract_errors
from gateway_stubs import LICENCE, Device, gateway_config, harness
from signing_service.hierarchy import dev_signer
from signing_service.keys import Purpose

START = "2026-09-01T00:00:00.000Z"  # the harness clock's default time (2026-09-21) is inside every paid period below
CONTRACT = "ops/licence#/$defs/CloudTierEntitlement"
PAID_FEATURES = ["cloud_tier", "ask_anything", "study_area", "uploads", "recordings", "podcasts", "past_paper_import",
                 "online_voice", "exam_reminders"]  # fmt: skip
PAID_LIMITS = {"ask_anything_per_day": 150, "uploads_per_day": 30, "upload_max_pages": 1000, "upload_max_mb": 200,
               "recording_hours_per_month": 10, "podcasts_per_day": 5, "voice_minutes_per_month": 300}  # fmt: skip
# TABLE BIZ-18a, by billing country: (plan, billing) -> what the checkout shows.
TABLE = {
    "NG": {("jana_online", "month"): "NGN 9,000 a month", ("jana_online", "term"): "NGN 24,000 a term",
           ("jana_online", "year"): "NGN 75,000 a year", ("jana_family", "month"): "NGN 22,000 a month",
           ("jana_family", "year"): "NGN 180,000 a year"},
    "GH": {("jana_online", "month"): "US$6 a month", ("jana_family", "month"): "US$15 a month"},
    "GB": {("jana_online", "month"): "US$12 a month", ("jana_online", "year"): "US$96 a year",
           ("jana_family", "month"): "US$25 a month"},
}  # fmt: skip
BAND = {"NG": "nigeria", "GH": "purchasing_power", "GB": "international"}


def signed(document: dict[str, Any]) -> dict[str, Any]:
    return dev_signer(Purpose.LICENCE).sign("licence_file", document, now=document["created_at"])


def terms(config: Any, country: str, plan: str, billing: str, seats: int = 1, **extra: Any) -> dict[str, Any]:
    bought = plans.quote(config, country, plan, billing, seats)
    return plans.entitlement_terms(config, bought, subscription_id=f"sub_{plan}_{billing}_{country}",
                                   licence_id=LICENCE, period_start=START, created_at=START, **extra)  # fmt: skip


def biz18_regional_price_and_entitlement(tmp_path: Path) -> None:
    """The checkout shows the band's price in its currency from the billing country, and the entitlement grants exactly
    the table's features and limits: the gateway registers it, the device reads the same plan back, Jana Family covers
    at most four students, and Free's online taste is the table's."""
    config = gateway_config(tmp_path)
    # The band comes from the billing country alone; a country in no band is international.
    for country, band in {**BAND, "ng": "nigeria", "KE": "purchasing_power", "US": "international"}.items():
        assert plans.band_for(config, country) == band
    with pytest.raises(plans.PlanRefused):
        plans.band_for(config, "Nigeria")
    # Each band offers exactly the table's prices, in its own currency, and nothing else.
    for country, expected in TABLE.items():
        shown = {(q.plan, q.billing): q.label() for q in plans.offers(config, country)}
        assert shown == expected, country
        assert {q.band for q in plans.offers(config, country)} == {BAND[country]}
        assert {q.currency for q in plans.offers(config, country)} == {"NGN" if country == "NG" else "USD"}
    with pytest.raises(plans.PlanRefused):
        plans.quote(config, "GH", "jana_online", "year")  # the purchasing-power band sells a month only
    with pytest.raises(plans.PlanRefused):
        plans.quote(config, "GB", "jana_online", "term")
    with pytest.raises(plans.PlanRefused):
        plans.quote(config, "NG", "jana_family", "month", seats=5)  # up to four students
    with pytest.raises(plans.PlanRefused):
        plans.quote(config, "NG", "jana_premium", "month")
    # Jana Online is priced per student; Jana Family per subscription of up to four.
    assert plans.quote(config, "NG", "jana_online", "month", seats=2).amount == 18_000
    assert plans.quote(config, "NG", "jana_family", "month", seats=4).amount == 22_000
    # The term is three months prepaid (D33) and a year twelve: the period the entitlement signs.
    assert terms(config, "NG", "jana_online", "term")["period_end"] == "2026-12-01T00:00:00.000Z"
    assert terms(config, "NG", "jana_online", "year")["period_end"] == "2027-09-01T00:00:00.000Z"

    # Every offer's entitlement grants exactly the table's features and limits, and matches its contract.
    for country, expected in TABLE.items():
        for plan, billing in expected:
            document = signed(terms(config, country, plan, billing))
            assert not contract_errors(CONTRACT, document), (country, plan, billing)
            assert (document["plan"], document["band"], document["billing"]) == (plan, BAND[country], billing)
            assert document["features"] == PAID_FEATURES and document["limits"] == PAID_LIMITS
            assert not {"price", "amount", "currency", "country"} & set(document)  # no payment detail (the contract)
    assert (config.plans.free.features, config.plans.free.limits.granted()) == (
        ("ask_anything", "uploads"),
        {"ask_anything_per_day": 3, "uploads_per_week": 1, "upload_max_pages": 50},
    )

    family = ["prf_" + "0" * 25 + str(n) for n in range(1, 5)]
    document = signed(terms(config, "NG", "jana_family", "year", seats=4, profile_ids=family))
    # The device verifies the checkout's entitlement and reads back the same plan, features and limits (D70).
    granted = device_subscription.verify(document, Environment.DEV)
    assert (granted.plan, granted.band, granted.billing, granted.seats) == ("jana_family", "nigeria", "year", 4)
    record = device_subscription.record(granted, family, minors=[], consented=[], payer="guardian", document=document)
    now_ms = ms_from_iso("2026-09-21T00:00:00.000Z")
    assert device_subscription.granted(record, family[0], now_ms) == {
        "plan": "jana_family",
        "features": PAID_FEATURES,
        "limits": PAID_LIMITS,
    }
    assert device_subscription.granted(record, "prf_" + "1" * 26, now_ms) is None

    async def main() -> None:
        h = harness(config)
        # Each of a Family's four students may register their own devices on the one subscription.
        devices = [Device(subscription=document["subscription_id"]) for _ in range(config.devices_per_subscription * 4)]
        for device in devices:
            assert (await device.register(h.client, document=document)).status_code == 201
        assert (await Device().register(h.client, document=document)).status_code == 409
        # A Family entitlement for five students is not one the table sells: refused, whoever signed it.
        five = signed({**terms(config, "NG", "jana_family", "year", seats=4), "seats": 5,
                       "subscription_id": "sub_family_five"})  # fmt: skip
        refused = await Device().register(h.client, document=five)
        assert refused.status_code == 403 and "at most 4 students" in refused.json()["error"]["message"]

    asyncio.run(main())


def biz18_one_allowance_no_picker(tmp_path: Path) -> None:
    """One monthly allowance for every plan, band and paid period, with no model choice and no second (premium) quota
    anywhere in the table, the configuration or the entitlement; the allowance changes before any price does."""
    config = gateway_config(tmp_path)
    allowances = {terms(config, country, plan, billing)["allowance_tokens"]
                  for country, expected in TABLE.items() for plan, billing in expected}  # fmt: skip
    assert allowances == {tier.monthly_allowance_tokens(config)} and allowances != {0}
    # It is kept at the lowest price a covered student's month brings in, so every plan covers it (BIZ-08 formula 4).
    lowest = min(tier.student_months_usd(config).values())
    assert tier.monthly_allowance_usd(config) == pytest.approx(lowest * (1 - config.tier.gross_margin))
    # Changing the allowance leaves every price as it was.
    smaller = gateway_config(tmp_path, tier={"allowance_usd_per_student_month": 0.5})
    assert tier.monthly_allowance_usd(smaller) == 0.5
    assert [q.label() for q in plans.offers(smaller, "NG")] == [q.label() for q in plans.offers(config, "NG")]

    # No field anywhere lets a payer or a student pick a model or buy a second quota.
    def names(model: Any) -> set[str]:
        return set(model.model_fields)

    words = ("model", "premium", "quota", "picker", "tier_choice")
    for fields in (names(Plans), names(Plan), names(Limits), names(Tier)):
        assert not [f for f in fields if any(w in f for w in words)], fields
    assert [f for f in names(Tier) if "allowance" in f] == ["allowance_usd_per_student_month"]
    schema = json.loads((Path(plans.__file__).parent / "contracts" / "schemas" / "ops" / "licence.schema.json")
                        .read_text())["$defs"]  # fmt: skip
    entitlement = schema["CloudTierEntitlement"]["properties"]
    assert [p for p in entitlement if "allowance" in p or "quota" in p] == ["allowance_tokens"]
    assert not [p for p in [*entitlement, *schema["PlanLimits"]["properties"]] if "model" in p or "premium" in p]
    # The two paid plans give the same features and limits: the Family is Jana Online for each student.
    online, family = config.plans.paid["jana_online"], config.plans.paid["jana_family"]
    assert (online.features, online.limits) == (family.features, family.limits)
    # The packaged table is the one the default configuration reads.
    assert load_config().plans == config.plans
