"""An unknown send holds quota until operator evidence settles it exactly once."""

import hashlib

import pytest
from cloud_gateway.store import GatewayStore
from cloud_gateway.study import SCHEMA, Refused, StudyService
from cloud_gateway.study_reconcile import reconcile


def test_uncertain_receipt_dry_run_atomic_settlement_and_conflicting_replay(tmp_path):
    store = GatewayStore(tmp_path)
    store._db.executescript(SCHEMA)
    identity, evidence = "a" * 64, "b" * 64
    account = hashlib.sha256(b"synthetic account").digest()
    store._db.execute(
        "INSERT INTO study_receipts VALUES (?,?,?,?,?,?,?,?,?)",
        (identity, account, "c" * 64, "reserved", 0.25, 0, 100, 101, "process"),
    )
    assert reconcile(store, identity, 0.04, evidence)["state"] == "dry_run"
    assert store._db.execute("SELECT state FROM study_receipts").fetchone()[0] == "reserved"
    assert not store._db.execute("SELECT * FROM allowance_spend").fetchall()
    assert reconcile(store, identity, 0.04, evidence, apply=True, now=200)["changed"]
    assert not reconcile(store, identity, 0.04, evidence, apply=True)["changed"]
    assert store._db.execute("SELECT cost_usd FROM allowance_spend").fetchone()[0] == 0.04
    assert store._db.execute("SELECT reserved_usd,actual_usd FROM study_receipts").fetchone() == (0, 0.04)
    with pytest.raises(ValueError, match="different evidence"):
        reconcile(store, identity, 0.05, evidence, apply=True)
    assert store._db.execute("SELECT count(*) FROM study_reconciliations").fetchone()[0] == 1
    store.close()


def test_held_previous_month_send_still_counts_against_daily_admission(tmp_path):
    from types import SimpleNamespace

    store = GatewayStore(tmp_path)
    service = StudyService(
        SimpleNamespace(
            store=store,
            clock=lambda: 1792281600,
            config=SimpleNamespace(quotas=SimpleNamespace(device_daily_spend_usd=2, study_daily_spend_usd=None)),
        )
    )
    session = SimpleNamespace(account="synthetic-account", period_start=None, seats=None)
    account = hashlib.sha256(session.account.encode()).digest()
    store._db.execute(
        "INSERT INTO study_receipts VALUES (?,?,?,?,?,?,?,?,?)",
        ("a" * 64, account, "c" * 64, "reserved", 1.99, 0, 1, 100, "process"),
    )
    with pytest.raises(Refused) as refused:
        service.reserve("b" * 64, session, {"synthetic": True}, 0.02)
    assert refused.value.reason == "allowance_exhausted"
    assert store._db.execute("SELECT count(*) FROM study_receipts").fetchone()[0] == 1
    store.close()


def test_global_daily_ceiling_covers_other_devices_unknowns_and_reconciliation(tmp_path):
    from types import SimpleNamespace

    from cloud_gateway.config import load_config

    store = GatewayStore(tmp_path)
    now = 1792281600
    config = load_config(quotas={"study_daily_spend_usd": 1, "device_daily_spend_usd": 10})
    service = StudyService(SimpleNamespace(store=store, clock=lambda: now, config=config))
    one = SimpleNamespace(account="device-one", period_start=None, seats=None)
    two = SimpleNamespace(account="device-two", period_start=None, seats=None)
    assert service.reserve("a" * 64, one, {"synthetic": 1}, 0.8)
    # A second account shares the same cap, even after UTC midnight.
    now += 86400
    with pytest.raises(Refused):
        service.reserve("b" * 64, two, {"synthetic": 2}, 0.3)
    reconcile(store, "a" * 64, 0.4, "e" * 64, apply=True, now=now)
    # Settled cost is counted once, so .4 + .5 fits; one extra .2 does not.
    assert service.reserve("b" * 64, two, {"synthetic": 2}, 0.5)
    with pytest.raises(Refused):
        service.reserve("c" * 64, one, {"synthetic": 3}, 0.2)
    assert not service.reserve("b" * 64, two, {"synthetic": 2}, 0.5)
