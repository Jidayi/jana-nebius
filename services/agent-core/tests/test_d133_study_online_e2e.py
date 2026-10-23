"""The online study tools (D133, STU-08) end to end: the device's real study queue and cloud client, the real cloud
gateway over pinned TLS on loopback, and a scripted stand-in for the Gemini model behind it.

Nothing reaches the internet: the study host is dialled at 127.0.0.1, its certificate comes from a throwaway CA, and
the model replies are scripted here. Each kind of study tool is made online, checked by the gateway's support pass,
published on the device with its citations, and its cloud copy is cleaned up afterwards."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from agent_core.config import Settings
from agent_core.engine.study import StudyDesk, StudyQueue
from agent_core.store import consents
from agent_core.store.sqlite import open_database
from cloud_gateway.app import create_app as create_gateway
from cloud_gateway.config import load_config
from cloud_gateway.custody import Secret
from net_harness import HOSTS, enable, layer, make_pki, registration_entitlement
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose

PROFILE = "prf_test"
NOW = 1792281600000
TEXT = (
    "Enzymes are biological catalysts. They speed up chemical reactions without being used up. "
    "Each enzyme has an active site that fits one substrate. High temperatures denature enzymes."
)


def cited(text: str) -> dict[str, Any]:
    """A drafted line citing the one passage; the gateway turns the passage id into the exact quote and range."""
    return {"text": text, "citations": [{"passage_id": "p0"}]}


def draft(request: dict[str, Any]) -> dict[str, Any]:
    """What the stand-in model writes for one request the gateway sends it, in the gateway's draft form."""
    first, second = "Enzymes are biological catalysts.", "High temperatures denature enzymes."
    out: dict[str, Any] = {"request_id": request["request_id"], "kind": request["kind"],
                           "claims": [cited(first), cited(second)]}  # fmt: skip
    if request["kind"] == "chat":
        out["claims"] = [cited("Enzymes are biological catalysts: they speed up reactions without being used up.")]
    if request["kind"] == "flashcards":
        out["flashcards"] = [
            {"front": cited("What are enzymes?"), "back": cited(first)},
            {"front": cited("What do high temperatures do to enzymes?"), "back": cited(second)},
        ]
    if request["kind"] == "quiz":
        out["quiz"] = {
            "items": [
                {
                    "item_id": "q1",
                    "type": "choice",
                    "stem": cited("What are enzymes?"),
                    "options": [
                        {"option_id": "a", "text": "Biological catalysts"},
                        {"option_id": "b", "text": "A kind of sugar"},
                    ],
                }
            ],
            "keys": [{"item_id": "q1", "answer": "a", "explanation": cited(first), "marking": "judged"}],
        }
    return out


class Model:
    """The stand-in for Gemini: drafts each study tool and passes the gateway's support check."""

    def __init__(self) -> None:
        self.drafts: list[str] = []
        self.checks = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        texts = [p.get("text", "") for c in body.get("contents", []) for p in c.get("parts", [])]
        if "supported" in json.dumps(body.get("generationConfig", {})):
            self.checks += 1
            text = json.dumps({"supported": True, "answerable": True, "reason": "", "repairable": False})
        else:
            sent = json.loads(texts[0])  # the frozen request: request_id, kind and the passages
            self.drafts.append(sent["kind"])
            text = json.dumps(draft(sent))
        usage = {"promptTokenCount": 400, "candidatesTokenCount": 120, "cachedContentTokenCount": 0,
                 "totalTokenCount": 520}  # fmt: skip
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                                                         "finishReason": "STOP"}],
                                         "usageMetadata": usage, "modelVersion": "gem-flash"})  # fmt: skip


class _Secrets:
    def get(self, name: str) -> Secret | None:
        return Secret("stub-gemini-key-not-real") if name == "gemini_api_key" else None


@contextlib.asynccontextmanager
async def gateway(tmp: Path, pki: Any, model: Model):
    signer = dev_signer(Purpose.LICENCE)
    models = {"fast-model": {"id": "gem-flash"}, "small-model": {"id": "gem-lite"}}
    config = load_config(None, environment="staging", audience_host=HOSTS["gateway"], storage_dir=tmp / "gateway",
                         entitlement_keys={signer.key_id: dev_trust().certificates[signer.key_id].public_key},
                         slots={"primary": "gemini"}, study_model="primary/fast-model",
                         providers={"gemini": {"adapter": "gemini", "base_url": "https://gemini.stub/v1beta",
                                               "secret": "gemini_api_key", "models": models}},
                         prices={m["id"]: {"input": 1.0, "cached_input": 0.1, "output": 4.0} for m in models.values()},
                         quotas={"device_burst": 1000, "licence_burst": 10000})  # fmt: skip
    app = create_gateway(config, secrets=_Secrets(),  # type: ignore[arg-type]
                         client_factory=lambda name, spec: httpx.AsyncClient(
                             transport=httpx.MockTransport(model.handler)))  # fmt: skip
    cert, key = tmp / "gateway.pem", tmp / "gateway.key"
    cert.write_bytes(pki.cert_pem + pki.ca_pem)
    key.write_bytes(pki.key_pem)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, ssl_certfile=str(cert), ssl_keyfile=str(key), log_level="warning",
                                           lifespan="on", log_config=None))  # fmt: skip
    served = asyncio.get_running_loop().create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        yield listener.getsockname()[1]
    finally:
        server.should_exit = True
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(served, 5)


def device(tmp: Path, port: int, pki: Any) -> tuple[Any, StudyDesk, StudyQueue]:
    """A subscribed device with the study switch and both consents on, and the real cloud client on its queue."""
    settings = Settings(study_workspace_enabled=True)
    online = layer(tmp, settings=settings, connect={h: ("127.0.0.1", port) for h in HOSTS.values()},
                   context=pki.client_context(), pins={h: (pki.ca_pin,) for h in HOSTS.values()})  # fmt: skip
    online.credential.entitlement = registration_entitlement(online.device)
    enable(online, "study_materials", "cloud_tier")
    online.record_notice(PROFILE, "study_materials", True)  # the student was told before anything left
    online.connectivity.state = "online"
    subscribed = {"subscription_id": "sub_test", "period_start": NOW - 86_400_000, "period_end": 4_000_000_000_000,
                  "seats": 1, "allowance_tokens": 1_800_000, "plan": "jana_online", "profiles": [PROFILE],
                  "consent_needed": [], "ended_at": None}  # fmt: skip
    online.subscription = lambda: subscribed  # type: ignore[method-assign]
    conn, _ = open_database(tmp / "learner.db", "learner")
    for scope in ("study_materials", "cloud_tier"):
        consents.grant(conn, scope, "guardian", "Parent", "v1", "dpia-test", NOW, include_study=True,
                       early=("cloud_tier",))  # fmt: skip
    desk = StudyDesk(conn, lambda: NOW, settings)
    queue = StudyQueue(lambda: conn, lambda: None, lambda: False, desk.clock, settings)
    queue.cloud = online.study_client(lambda: PROFILE, lambda: conn)
    return online, desk, queue


def test_stu08_online_tools_end_to_end(tmp_path):
    """Notes, flashcards, a quiz and a Chat answer are each made online through the real gateway, pass its support
    check and land on the device with exact citations; no local model is asked, and each cloud copy is deleted."""
    pki = make_pki(list(HOSTS.values()))
    model = Model()

    async def go() -> None:
        async with gateway(tmp_path, pki, model) as port:
            _online, desk, queue = device(tmp_path, port, pki)
            source = desk.create({"kind": "text", "title": "Enzymes", "text": TEXT})
            for kind in ("notes", "flashcards", "quiz", "chat"):
                body = {"kind": kind, "execution": "prefer_cloud",
                        "sources": [{"source_id": source["source_id"], "revision": source["revision"]}],
                        **({"count": 2} if kind in ("flashcards", "quiz") else {}),
                        **({"prompt": "What are enzymes?"} if kind == "chat" else {})}  # fmt: skip
                job = desk.create_job(body)
                await queue.run(desk, job["job_id"])
                finished = desk.job(job["job_id"])
                assert finished["state"] == "completed", (kind, finished.get("error"), model.drafts, model.checks)
                aid = desk.aid(finished["result_ids"][0])
                for claim in aid["claims"] if "claims" in aid else []:
                    for citation in claim["citations"]:
                        assert TEXT[citation["start"] : citation["end"]] == citation["quote"]
            assert model.drafts == ["notes", "flashcards", "quiz", "chat"]
            assert model.checks >= 4
            assert desk.conn.execute("SELECT count(*) FROM study_cloud_cleanup").fetchone()[0] == 0

    asyncio.run(go())
