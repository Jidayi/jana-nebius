"""PRD-22 on the running core: a pilot build creates no profile until its signed pilot-country record is complete,
and names the missing rows. A device whose school licence puts it on the pilot channel is a pilot build too. Every
record is synthetic and signed by the published test root."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config import pilot as pilot_config
from agent_core.config.pilot import COUNTRY_FIELDS
from api_harness import start_core, stop_core
from signing_service.hierarchy import dev_signer
from signing_service.keys import Purpose
from test_m10a_profiles import Api, student

SIGNED_AT = "2026-10-10T00:00:00.000Z"


def record(**items: str) -> dict[str, Any]:
    value = {
        "country": "XX",
        "locale": "en-XX",
        "currency_code": "XXX",
        "currency_symbol": "X",
        "issued_at": SIGNED_AT,
        "items": {name: items.get(name, "synthetic-ref") for name in COUNTRY_FIELDS},
        "pilot_clearance": {
            "protocol_id": "synthetic-pilot",
            "registered_at": "2026-10-01T00:00:00Z",
            "baseline_at": "2026-10-02T00:00:00Z",
            "starts_at": "2026-10-03T00:00:00Z",
            "analysis_sha256": "a" * 64,
            "approval_ref": "synthetic-owner-approval",
        },
    }
    return dev_signer(Purpose.CONTENT).sign("pilot_country", value, now=SIGNED_AT)


class _AcceptTestRoot:
    """The pilot build's trust, standing in for the release root this checkout does not have yet (the key ceremony):
    the signature rules themselves are prd22_pilot_checklist_gate's."""

    def verify(self, *args: Any) -> None:
        return None


def create(tmp_path: Path, settings: Settings, licence_channel: str | None = None) -> tuple[int, Any]:
    async def go() -> tuple[int, Any]:
        r = await start_core(tmp_path / "core", settings=settings, worker=False)
        try:
            if licence_channel is not None:

                class Licence:
                    class state:
                        @staticmethod
                        def view(subscribed: bool = False) -> dict[str, Any]:
                            return {"channel": licence_channel}

                r.core.licence = Licence()
            reply = await Api(r).call("POST", "/v1/profiles", student("Ama"))
            return reply.status_code, reply.json()
        finally:
            await stop_core(r)

    return asyncio.run(go())


def test_pilot_build_refuses_profiles_until_the_country_record_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pilot_config, "bundled_trust", lambda: _AcceptTestRoot())
    path = tmp_path / "pilot-country.json"
    pilot = Settings(environment="pilot", pilot_country_file=str(path))
    path.write_text(json.dumps(record(safety_resources="", school_calendar="FILL-IN")))
    status, body = create(tmp_path / "incomplete", pilot)
    assert status != 200 and body["error"]["code"] == "validation_failed"
    assert "missing safety_resources, school_calendar" in body["error"]["message"]
    path.write_text(json.dumps(record()))
    status, body = create(tmp_path / "complete", pilot)
    assert status == 200, body
    # No country file at all: the pilot build refuses, naming it.
    status, body = create(tmp_path / "none", Settings(environment="pilot"))
    assert status != 200 and "missing pilot-country configuration" in body["error"]["message"]
    # A pilot-channel licence makes a build a pilot build even when the shell named no country file.
    status, body = create(tmp_path / "licence", Settings(), licence_channel="pilot")
    assert status != 200 and "missing pilot-country configuration" in body["error"]["message"]
    status, _ = create(tmp_path / "stable", Settings(), licence_channel="stable")
    assert status == 200  # development and evaluation builds use the generic values (PRD-22)
