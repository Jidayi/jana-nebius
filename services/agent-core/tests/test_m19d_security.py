"""M19.d: device credentials and transport security for online features (SEC-21, SEC-31). The services are the local
TLS stand-in of net_harness; every key and certificate is made for the test."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.net.credentials import ID_REF, KEY_REF
from agent_core.net.policy import EgressRefused, load_policy
from agent_core.store.keystore import MemoryKeyStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from net_harness import ACCESS_TOKEN, CREDENTIAL_ID, HOSTS, FakeServices, enable, layer, make_pki, telemetry_payload

LOOP = asyncio.new_event_loop()


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def sec21_credential_separate(tmp_path: Path) -> None:
    """Service authentication uses its own Ed25519 key under its own keystore reference: not a database key, not
    the backup key; only its public half is registered (and recorded on the device), and only tokens are sent."""
    keys = MemoryKeyStore()
    keys.put("profile.01ARZ3NDEKTSV4RRFFQ69G5FAV.db", b"d" * 32)  # a learner database key (SEC-17)
    keys.put("backup.recovery", b"b" * 32)  # the personal backup key (SEC-32), when it exists

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server, keys=keys)
            enable(online, "cloud_tier")
            await online.connectivity.check()
            token = await online.credential.token()
            again = await online.credential.token()
            device = online.device.execute("SELECT credential_public_key FROM device").fetchone()[0]
            await online.stop()
            return server.requests, token, again, device

    requests, token, again, device = run(scenario())
    private = keys.get(KEY_REF)
    assert private is not None and len(private) == 32
    assert private not in (keys.get("profile.01ARZ3NDEKTSV4RRFFQ69G5FAV.db"), keys.get("backup.recovery"))
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()
    assert device == public, "the registered public key is recorded on the device"
    assert keys.get(ID_REF) == CREDENTIAL_ID.encode()
    registration = next(r for r in requests if r.path == "/v1/devices").json()
    assert registration["licence_id"] == "" and len(registration["public_key"]) == 44
    wire = b"".join(r.body for r in requests) + json.dumps([r.headers for r in requests]).encode()
    assert private not in wire and token == again == ACCESS_TOKEN  # the stand-in's token, reused
    assert [r.path for r in requests] == ["/v1/ping", "/v1/devices", "/v1/auth/challenge", "/v1/auth/token"]


def sec21_anonymous_features(tmp_path: Path) -> None:
    """Downloads, update checks, telemetry and crash reports carry no credential and no device identifier; the
    layer refuses a request for one of them that tries to carry a credential."""
    anonymous = ("downloads", "update_checks", "telemetry", "crash_reports")

    async def scenario() -> Any:
        async with FakeServices(tmp_path) as server:
            online = layer(tmp_path, server)
            enable(online, "cloud_tier", *anonymous)
            await online.connectivity.check()
            await online.credential.token()  # the device has a credential: it must still not travel
            device_id = online.device.execute("SELECT device_id FROM device").fetchone()[0]
            start = len(server.requests)
            for feature in anonymous:
                row = load_policy().features[feature]
                await online.client.send(feature, "POST", f"https://{online.host_for(feature)}/v1/x",
                                         row.payload_classes[0], content=telemetry_payload() if feature == "telemetry"
                                         else json.dumps({"app_version": "0.0.0"}).encode())  # fmt: skip
            refused = []
            for feature in anonymous:
                row = load_policy().features[feature]
                with pytest.raises(EgressRefused) as error:
                    await online.client.send(
                        feature,
                        "POST",
                        f"https://{online.host_for(feature)}/v1/x",
                        row.payload_classes[0],
                        headers={"Authorization": "Bearer tok_test"},
                    )
                refused.append(error.value.reason)
            sent = server.requests[start:]
            public = online.device.execute("SELECT credential_public_key FROM device").fetchone()[0]
            await online.stop()
            return sent, refused, device_id, public

    sent, refused, device_id, public = run(scenario())
    assert len(sent) == 4 and refused == ["credential_on_anonymous_feature"] * 4
    for seen in sent:
        wire = json.dumps(seen.headers) + seen.body.decode()
        assert "authorization" not in seen.headers and "tok_test" not in wire and "dcr_test" not in wire
        assert device_id not in wire and public.hex() not in wire


def sec31_pinned_tls_to_our_services(tmp_path: Path) -> None:
    """An interception proxy whose root the device trusts presents a valid certificate for our hostname, but not
    from our pinned CA: the connection is dropped after the handshake and the proxy reads no request, payload or
    credential. Plain HTTP is refused before any connection. With our CA the same request goes through."""
    proxy = make_pki(sorted(set(HOSTS.values())), "Interception proxy root")

    async def scenario() -> Any:
        ours = FakeServices(tmp_path / "ours")
        (tmp_path / "ours").mkdir()
        (tmp_path / "proxy").mkdir()
        async with FakeServices(tmp_path / "proxy", pki=proxy) as intercepting, ours:
            # The device trusts the proxy's root (as a managed machine might) but pins our CA.
            online = layer(tmp_path, context=proxy.client_context(), connect=intercepting.connect(),
                           pins={h: (ours.pki.ca_pin,) for h in HOSTS.values()})  # fmt: skip
            enable(online, "cloud_tier", "update_checks")
            online.connectivity.state = "online"
            reasons = []
            for attempt in (
                online.client.send("cloud_tier", "POST", f"https://{HOSTS['gateway']}/v1/chat/completions",
                                   "cloud_prompt", body={"messages": "secret question"},
                                   headers={"Authorization": "Bearer tok_secret"}),
                online.client.send("update_checks", "GET", f"https://{HOSTS['updates']}/v1/check", "update_check"),
                online.client.send("update_checks", "GET", f"http://{HOSTS['updates']}/v1/check", "update_check"),
            ):  # fmt: skip
                with pytest.raises(EgressRefused) as refused:
                    await attempt
                reasons.append(refused.value.reason)
            await online.stop()
            genuine = layer(tmp_path / "ours", ours)
            enable(genuine, "update_checks")
            genuine.connectivity.state = "online"
            reply = await genuine.client.send("update_checks", "GET", f"https://{HOSTS['updates']}/v1/ping",
                                              "update_check")  # fmt: skip
            await genuine.stop()
            return reasons, intercepting.requests, intercepting.raw_bytes, reply.status

    reasons, intercepted, raw, status = run(scenario())
    assert reasons == ["pin_mismatch", "pin_mismatch", "plain_http"]
    assert intercepted == [] and raw == 0, "the proxy read nothing"
    assert status == 204
