"""Test doubles for the ingest: a throwaway CA and server certificate, staff tokens, a settable clock, and the ingest
served over TLS in-process so the device's real connectivity layer (egress client, pins, outbox) can reach it.

Nothing here reaches the internet: our placeholder hosts (`*.dev.jana.invalid`) are dialled at 127.0.0.1. All data
is synthetic."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from agent_core.config import Settings
from agent_core.net.client import spki_pin
from agent_core.net.layer import OnlineLayer
from agent_core.net.policy import load_policy
from agent_core.store.keystore import MemoryKeyStore
from agent_core.store.local import open_local
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from ingest.app import create_app
from ingest.config import IngestConfig, load_config
from ingest.custody import Secret

HOSTS = load_policy().services["dev"]
INGEST_HOSTS = (HOSTS["crash"], HOSTS["telemetry"])
STORAGE_KEY = base64.b64encode(bytes(range(32))).decode()  # synthetic, for tests only
TOKENS = {"ada": "synthetic-staff-token-ada-0001", "ben": "synthetic-staff-token-ben-0002",
          "cy": "synthetic-staff-token-cy-0003"}  # fmt: skip
DAY_S = 86_400


class Clock:
    def __init__(self, now: float = 1_790_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeSecrets:
    values: dict[str, str] = field(
        default_factory=lambda: {"ingest_storage_key": STORAGE_KEY, **{f"staff_{k}": v for k, v in TOKENS.items()}}
    )

    def get(self, name: str) -> Secret | None:
        value = self.values.get(name)
        return Secret(value) if value else None


def config(tmp: Path, **overrides: Any) -> IngestConfig:
    staff = {"ada": {"secret": "staff_ada", "level": "L3"}, "ben": {"secret": "staff_ben", "level": "L1"},
             "cy": {"secret": "staff_cy", "level": "L2"}}  # fmt: skip
    return load_config(None, environment="dev", storage_dir=tmp / "ingest", staff=staff, **overrides)


def app(tmp: Path, clock: Clock | None = None, **overrides: Any) -> FastAPI:
    return create_app(config(tmp, **overrides), secrets=FakeSecrets(), clock=clock or Clock())


def client(application: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url=f"https://{HOSTS['crash']}")


def staff(name: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[name]}"}


@dataclass
class Pki:
    ca_pem: bytes
    ca_der: bytes
    cert_pem: bytes
    key_pem: bytes

    @property
    def ca_pin(self) -> str:
        return spki_pin(self.ca_der)

    def client_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cadata=self.ca_pem.decode())
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context


def make_pki(names: tuple[str, ...]) -> Pki:
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
          .not_valid_after(now + datetime.timedelta(days=7))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))  # fmt: skip
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))  # fmt: skip
    pem = serialization.Encoding.PEM
    return Pki(ca.public_bytes(pem), ca.public_bytes(serialization.Encoding.DER), cert.public_bytes(pem),
               key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))  # fmt: skip


@contextlib.asynccontextmanager
async def serve_tls(application: FastAPI, tmp: Path) -> AsyncIterator[tuple[Pki, int]]:
    """The ingest on a local TLS port, as it runs behind its TLS terminator in a deployment."""
    pki = make_pki(INGEST_HOSTS)
    cert, key = tmp / "server.pem", tmp / "server.key"
    cert.write_bytes(pki.cert_pem + pki.ca_pem)
    key.write_bytes(pki.key_pem)
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=0, ssl_certfile=str(cert),
                                           ssl_keyfile=str(key), access_log=False, log_level="warning",
                                           proxy_headers=False, server_header=False))  # fmt: skip
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield pki, port
    finally:
        server.should_exit = True
        await task


def device_layer(tmp: Path, pki: Pki, port: int) -> OnlineLayer:
    """The device's connectivity layer on a fresh device.db, dialling the ingest hosts at the local port and pinning
    the test CA."""
    device = open_local(tmp / "data", app_version="0.0.0", now_ms=1_760_000_000_000).device
    return OnlineLayer(Settings(), device, MemoryKeyStore(), connect={h: ("127.0.0.1", port) for h in HOSTS.values()},
                       context=pki.client_context(), pins={h: (pki.ca_pin,) for h in HOSTS.values()})  # fmt: skip


def enable(online: OnlineLayer, *features: str) -> None:
    for feature in features:
        online.device.execute(
            "INSERT INTO online_features (feature, enabled, enabled_by_role, enabled_at) VALUES (?, 1, 'user', 0)"
            " ON CONFLICT (feature) DO UPDATE SET enabled = 1",
            (feature,),
        )
