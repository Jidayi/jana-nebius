"""M19.d security fix: the device registers its service credential with the applied subscription's licence and signed
entitlement, which the gateway requires (SEC-21, BIZ-07, D70); a refused challenge makes the next attempt register
again. The entitlement and every reply are synthetic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent_core.net.credentials import ID_REF
from agent_core.store import subscription as subscriptions
from net_harness import FakeServices, enable, layer
from signing_service.hierarchy import dev_trust
from test_m19b_api import entitlement

LOOP = asyncio.new_event_loop()


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def test_sec21_registration_carries_the_subscription(tmp_path: Path) -> None:
    signed = entitlement(["prf_01M4YKC4J7ZAA6XXC5QV6NCZ84"])

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            verified = subscriptions.verify(signed, online.environment, dev_trust())
            stored = subscriptions.record(verified, verified.profile_ids, [], [], "student_18_plus", signed)
            subscriptions.save(online.device, stored, online.clock_ms())
            enable(online, "cloud_tier")
            await online.connectivity.check()
            await online.credential.token()
            server.revoked = True  # the subscription lapsed or the portal revoked the credential
            online.credential.forget_token()
            refused = None
            try:
                await online.credential.token()
            except Exception as error:  # the refusal type is the client's own
                refused = type(error).__name__
            await online.stop()
            return server.requests, refused, online.keys.get(ID_REF)

    requests, refused, kept = run(scenario())
    registration = next(r for r in requests if r.path == "/v1/devices").json()
    assert registration["licence_id"] == "lic_test"
    assert registration["entitlement"]["subscription_id"] == "sub_test_0001"
    assert registration["entitlement"]["signature"]["alg"] == "ed25519"
    assert refused == "CredentialRefused" and kept is None, "a refused challenge forgets the credential id"


def test_registration_needs_an_entitlement_and_contract_replies(tmp_path: Path) -> None:
    """The registration, challenge and token bodies are built through the gateway contract (D39): with no
    subscription entitlement nothing is sent, and a reply the contract does not accept (here a credential id of the
    wrong form) is a refusal like any other."""
    from agent_core.contracts import errors as contract_errors
    from agent_core.net.credentials import CredentialRefused

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            bare = layer(tmp_path / "bare", server, entitlement=lambda: None)
            enable(bare, "cloud_tier")
            await bare.connectivity.check()
            refusals = []
            try:
                await bare.credential.token()
            except CredentialRefused as refused:
                refusals.append(str(refused))
            await bare.stop()
            sent_bare = [r.path for r in server.requests if r.path != "/v1/ping"]
            server.handlers["/v1/devices"] = lambda seen: (201, {"credential_id": "credential-7"})
            odd = layer(tmp_path / "odd", server)
            enable(odd, "cloud_tier")
            await odd.connectivity.check()
            try:
                await odd.credential.token()
            except CredentialRefused as refused:
                refusals.append(str(refused))
            await odd.stop()
            return sent_bare, refusals, odd.keys.get(ID_REF), server.requests

    sent_bare, refusals, kept, requests = run(scenario())
    assert sent_bare == [] and len(refusals) == 2 and kept is None
    registration = next(r for r in requests if r.path == "/v1/devices").json()
    assert contract_errors("cloud/gateway#/$defs/DeviceRegistration", registration) == []
