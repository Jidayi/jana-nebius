"""OPS-02/06/10/15: operations artefacts pass service-side checks before signing."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_core.config import Environment
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.operations import OperationsPublisher

AT = "2026-10-16T00:00:00Z"


def body(sequence=1):
    return {
        "sequence": sequence,
        "channel": "stable",
        "issued_at": AT,
        "entries": [
            {
                "entry_id": "entry_synthetic",
                "target_kind": "tool",
                "target": "math_solve",
                "action": "disable",
                "reason_code": "synthetic",
                "incident_id": "inc_synthetic",
                "lift_when": None,
            }
        ],
    }


def test_ops_publisher_rechecks_and_preserves_sequence(tmp_path: Path):
    checks = []
    service = OperationsPublisher(
        tmp_path,
        dev_signer(),
        dev_trust(),
        Environment.DEV,
        lambda kind, doc: checks.append((kind, doc["channel"])) or [],
    )
    published = service.publish("safety_configuration", body(), at=AT)
    dev_trust().verify("safety_configuration", published, Environment.DEV, AT)
    assert checks == [("safety_configuration", "stable")]
    assert service.publish("safety_configuration", body(), at=AT) == published
    changed = body()
    changed["entries"] = []
    with pytest.raises(ValueError):
        service.publish("safety_configuration", changed, at=AT)
    assert (
        OperationsPublisher(tmp_path, dev_signer(), dev_trust(), Environment.DEV, lambda *_: []).publish(
            "safety_configuration", body(2), at=AT
        )["sequence"]
        == 2
    )


def test_ops_publisher_missing_gate_or_enabling_entry_never_signs(tmp_path: Path):
    service = OperationsPublisher(
        tmp_path, dev_signer(), dev_trust(), Environment.DEV, lambda *_: ["OPS-06: missing compatibility"]
    )
    with pytest.raises(ValueError):
        service.publish("safety_configuration", body(), at=AT)
    assert not list(tmp_path.glob("*.json"))
    service = OperationsPublisher(tmp_path, dev_signer(), dev_trust(), Environment.DEV, lambda *_: [])
    bad = body()
    bad["entries"][0]["action"] = "enable"
    with pytest.raises(ValueError):
        service.publish("safety_configuration", bad, at=AT)
