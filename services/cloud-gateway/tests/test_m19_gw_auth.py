"""SEC-21: device credentials bound to a licence, challenge-signed short-lived tokens, revocation."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from agent_core.providers.errors import classify_http
from gateway_stubs import FAKE_KEYS, Clock, Device, Output, gateway_config, harness

CHAT = {"model": "primary/fast-model", "messages": [{"role": "user", "content": "Hello"}]}


def _admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {FAKE_KEYS['admin_token']}"}


def sec21_revocation(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text="Hi."))
        assert (await device.chat(h.client, CHAT)).status_code == 200
        spare = (await device.challenge(h.client)).json()["nonce"]  # a challenge issued before revocation

        # Only the licence portal (admin secret) may revoke.
        path = f"/admin/v1/credentials/{device.credential_id}/revoke"
        assert (await h.client.post(path)).status_code == 401
        assert (await h.client.post(path, headers={"Authorization": "Bearer wrong"})).status_code == 401
        assert (await h.client.post(path, headers=_admin())).status_code == 204

        # The outstanding token stops working at once, and no fresh token can be had.
        refused = await device.chat(h.client, CHAT)
        assert refused.status_code == 401 and classify_http(401, refused.json()) == "auth"
        assert (await device.challenge(h.client)).status_code == 401
        assert (await device.exchange(h.client, spare)).status_code == 401
        assert len(h.stubs["gemini"].seen) == 1  # nothing reached the provider after revocation

    asyncio.run(main())


def test_registration_is_bound_to_a_known_licence(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        assert (await Device().register(h.client, "lic_unknown")).status_code == 403
        bad = await h.client.post("/v1/devices", json={"public_key": "AAAA", "licence_id": "lic_school_one"})
        assert bad.status_code == 400
        device = Device()
        reply = await device.register(h.client)
        assert reply.status_code == 201 and device.credential_id.startswith("dcr_")
        credential = h.client._transport.app.state.gateway.store.credential(device.credential_id)  # type: ignore[attr-defined]
        assert credential.licence_id == "lic_school_one"

    asyncio.run(main())


def test_nonce_is_single_use_and_expires(tmp_path: Path) -> None:
    async def main() -> None:
        clock = Clock()
        h = harness(gateway_config(tmp_path), clock)
        device = Device()
        await device.register(h.client)
        challenge = (await device.challenge(h.client)).json()
        assert challenge["expires_in"] == 60 and len(base64.b64decode(challenge["nonce"])) == 32
        assert (await device.exchange(h.client, challenge["nonce"])).status_code == 200
        assert (await device.exchange(h.client, challenge["nonce"])).status_code == 401  # replay

        late = (await device.challenge(h.client)).json()["nonce"]
        clock.now += 61
        assert (await device.exchange(h.client, late)).status_code == 401

        other = Device()
        await other.register(h.client)
        theirs = (await other.challenge(h.client)).json()["nonce"]
        assert (await device.exchange(h.client, theirs)).status_code == 401  # another credential's nonce

    asyncio.run(main())


def test_signature_must_cover_this_gateway(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.register(h.client)
        nonce = (await device.challenge(h.client)).json()["nonce"]
        assert (await device.exchange(h.client, nonce, audience="elsewhere.test")).status_code == 401
        impostor = Device(credential_id=device.credential_id)  # right id, wrong key
        nonce = (await impostor.challenge(h.client)).json()["nonce"]
        assert (await impostor.exchange(h.client, nonce)).status_code == 401

    asyncio.run(main())


def test_access_token_expires(tmp_path: Path) -> None:
    async def main() -> None:
        clock = Clock()
        h = harness(gateway_config(tmp_path), clock)
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text="a"), Output(text="b"))
        assert (await device.chat(h.client, CHAT)).status_code == 200
        clock.now += h.config.access_token_ttl_s + 1
        assert (await device.chat(h.client, CHAT)).status_code == 401
        await device.login(h.client)
        assert (await device.chat(h.client, CHAT)).status_code == 200

    asyncio.run(main())


def test_ping_and_status(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        ping = await h.client.get("/v1/ping")
        assert ping.status_code == 204 and ping.headers["Jana-Gateway-Version"] == "1.1"
        assert (await h.client.get("/v1/status")).json() == {"status": "ok"}
        device = Device()
        await device.login(h.client)
        for _ in range(6):
            h.stubs["gemini"].say(Output(error=(500, {"error": {"message": "boom"}})))
            await device.chat(h.client, CHAT)
        assert (await h.client.get("/v1/status")).json() == {"status": "outage"}
        for _ in range(10):
            h.stubs["gemini"].say(Output(text="fine"))
            await device.chat(h.client, CHAT)
        assert (await h.client.get("/v1/status")).json() == {"status": "degraded"}

    asyncio.run(main())


def test_device_routes_read_and_answer_through_the_gateway_contract(tmp_path: Path) -> None:
    """Registration, challenge and token bodies are read through the gateway contract (D39): a registration with a
    field the contract does not list is refused as malformed (400), as are challenge and token bodies with one (401,
    like any refused credential); every reply, the status and the error bodies match their definitions."""
    from agent_core.contracts import errors as contract_errors
    from gateway_stubs import entitlement

    def gateway(definition: str) -> str:
        return f"cloud/gateway#/$defs/{definition}"

    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        body = {"public_key": device.public_key(), "entitlement": entitlement(device.subscription),
                "device_name": "Lab computer 3"}  # fmt: skip
        extra = await h.client.post("/v1/devices", json=body)
        assert extra.status_code == 400 and contract_errors(gateway("GatewayError"), extra.json()) == []
        registered = await device.register(h.client)
        assert registered.status_code == 201 and contract_errors(gateway("DeviceRegistered"), registered.json()) == []
        nosy = await h.client.post("/v1/auth/challenge", json={"credential_id": device.credential_id, "ip": "x"})
        assert nosy.status_code == 401 and classify_http(401, nosy.json()) == "auth"
        challenge = await device.challenge(h.client)
        assert contract_errors(gateway("Challenge"), challenge.json()) == []
        nonce = challenge.json()["nonce"]
        signed = {"credential_id": device.credential_id, "nonce": nonce, "signature": device.sign(nonce)}
        assert (await h.client.post("/v1/auth/token", json={**signed, "scope": "all"})).status_code == 401
        token = await h.client.post("/v1/auth/token", json=signed)  # the refused body did not use up the nonce
        assert token.status_code == 200 and contract_errors(gateway("AccessToken"), token.json()) == []
        status = await h.client.get("/v1/status")
        assert contract_errors(gateway("GatewayStatus"), status.json()) == []

    asyncio.run(main())
