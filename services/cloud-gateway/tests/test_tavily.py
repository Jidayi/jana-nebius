"""No-network Tavily integration: credit custody, restart safety, citations and explicit public-page import."""

import asyncio
import json
import sys

import httpx
import pytest
from cloud_gateway.custody import TavilyEnvironmentSecrets
from cloud_gateway.secret_scan import scan_bytes
from cloud_gateway.tavily import Tavily, TavilyError, public_url
from gateway_stubs import FAKE_KEYS, Device, FakeSecrets, Output, gateway_config, harness
from test_m45a_ask import body

PAGE = "https://www.britannica.com/place/Paris"
TEXT = "Paris is the capital of France. It stands on the Seine."


def test_tavily_credentials_are_detected_and_masked():
    for variant in (b"", b"dev-", b"prod-"):
        value = b"tv" + b"ly-" + variant + b"A7" * 20
        findings = scan_bytes(value, "fixture")
        assert len(findings) == 1 and findings[0].pattern == "tavily_key"
        assert value.decode() not in str(findings[0])


def test_tavily_status_requires_authentication_and_exposes_only_readiness(tmp_path):
    async def run():
        h, _, seen = setup(tmp_path)
        denied = await h.client.get("/v1/web/status")
        assert denied.status_code == 401
        device = Device()
        await device.login(h.client)
        ready = await h.client.get("/v1/web/status", headers=device.headers())
        assert ready.status_code == 200
        assert ready.json() == {"enabled": True, "configured": True}
        assert seen == []

    asyncio.run(run())


def setup(tmp, **limits):
    config = gateway_config(
        tmp, slots={"primary": "nebius"}, tavily={"enabled": True, "expires_at": "2026-11-02T00:46:01Z", **limits}
    )
    h = harness(config, secrets=FakeSecrets({**FAKE_KEYS, "tavily_api_key": "stub-tavily-key-not-real"}))
    service = h.client._transport.app.state.gateway.tavily
    seen = []

    def handle(request):
        assert request.url.host == "api.tavily.com"
        assert request.headers["authorization"] == "Bearer stub-tavily-key-not-real"
        assert "x-profile-token" not in request.headers
        sent = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, sent))
        if request.url.path == "/usage":
            return httpx.Response(
                200,
                json={
                    "account": {"plan_limit": 12125, "plan_usage": 0, "paygo_limit": 0},
                    "key": {"limit": 500, "usage": 0},
                },
            )
        if request.url.path == "/search":
            assert sent["search_depth"] == "basic" and sent["auto_parameters"] is False
            assert sent["include_answer"] is False and sent["safe_search"] is True
            assert not {"own", "files", "profile_id", "messages"} & sent.keys()
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": PAGE, "title": "Paris", "content": TEXT},
                        {"url": "http://127.0.0.1/private", "title": "Private", "content": "ignored"},
                    ]
                },
            )
        assert request.url.path == "/extract" and len(sent["urls"]) <= 5
        assert sent["extract_depth"] == "basic"
        return httpx.Response(200, json={"results": [{"url": PAGE, "raw_content": TEXT}]})

    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return h, service, seen


def test_tavily_search_extract_and_nemotron_support_keep_only_grounded_claims(tmp_path):
    async def run():
        h, service, seen = setup(tmp_path)
        device = Device()
        await device.login(h.client)
        denied = await h.client.post("/v1/ask", json=body(), headers=device.headers())
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "web_permission_required"
        assert seen == [] and h.stubs["nebius"].seen == []
        h.stubs["nebius"].say(
            Output(
                text=json.dumps(
                    {
                        "statements": [
                            {"text": "Paris is France's capital.", "refs": ["web1"]},
                            {"text": "Paris is on the Moon.", "refs": ["web1"]},
                        ],
                        "check_question": "Why might capitals develop on rivers?",
                        "explanation": [],
                    }
                )
            ),
            Output(text=json.dumps({"supported": [True, False]})),
        )
        reply = await h.client.post("/v1/ask", json=body(web_confirmed=True), headers=device.headers())
        assert reply.status_code == 200, reply.text
        assert reply.json()["statements"] == [{"text": "Paris is France's capital.", "refs": ["web1"]}]
        assert [s["url"] for s in reply.json()["sources"]] == [PAGE]
        assert [p for m, p, _ in seen if m == "POST"] == ["/search", "/extract"]
        assert seen[1][2]["include_domains"] == ["britannica.com", "who.int"]
        assert len(h.stubs["nebius"].seen) == 2
        assert service.gw.store._db.execute("SELECT sum(credits) FROM tavily_credits").fetchone()[0] == 2
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert TEXT.encode() not in path.read_bytes() and b"stub-tavily-key-not-real" not in path.read_bytes()

    asyncio.run(run())


def test_answer_and_support_receive_relevant_extracted_evidence_beyond_old_snippet_limit(tmp_path, monkeypatch):
    fact = "Paris is the capital of France."
    passage = "Page navigation and introductory material. " * 20 + fact + " tail" * 1000
    monkeypatch.setattr(sys.modules[__name__], "TEXT", passage)

    async def run():
        h, _, _ = setup(tmp_path)
        device = Device()
        await device.login(h.client)
        h.stubs["nebius"].say(
            Output(
                text=json.dumps(
                    {
                        "statements": [{"text": fact, "refs": ["web1"]}],
                        "check_question": "Where is Paris?",
                        "explanation": [],
                    }
                )
            ),
            Output(text=json.dumps({"supported": [True]})),
        )
        reply = await h.client.post("/v1/ask", json=body(web_confirmed=True), headers=device.headers())
        assert reply.status_code == 200
        assert fact in reply.json()["sources"][0]["snippet"]
        assert len(reply.json()["sources"][0]["snippet"]) <= 3000
        for sent in h.stubs["nebius"].seen:
            assert fact in "\n".join(sent.user_texts)

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/x",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://host.local/x",
        "https://user:pass@example.org/x",
        "https://example.org:8080/x",
        "https://example.org/?token=secret",
        "file:///private/x",
        "https://localhost/x",
    ],
)
def test_only_public_https_pages(url):
    with pytest.raises(TavilyError, match="invalid_public_url"):
        public_url(url)


def test_prepaid_credit_limits_survive_restart_and_unknown_usage_stays_held(tmp_path):
    async def run():
        h, service, _ = setup(tmp_path, daily_credits=1, total_credits=2)
        await service.search("public", [], 1, "device", "first")
        # Daily cap, including a second process using the same durable database.
        other = Tavily(service.gw, service.client)
        with pytest.raises(TavilyError, match="search_credits_exhausted"):
            await other.call("search", {"query": "public"}, "device", "second")
        h.clock.now += 86400

        def fail(request):
            if request.url.path == "/usage":
                return httpx.Response(
                    200,
                    json={
                        "account": {"plan_limit": 100, "plan_usage": 0, "paygo_limit": 0},
                        "key": {"limit": 100, "usage": 0},
                    },
                )
            raise httpx.ReadTimeout("not logged")

        other.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        with pytest.raises(TavilyError, match="search_unavailable"):
            await other.call("search", {}, "device", "second")
        assert service.gw.store._db.execute("SELECT state FROM tavily_credits ORDER BY rowid").fetchall() == [
            ("completed",),
            ("held",),
        ]
        h.clock.now += 86400
        with pytest.raises(TavilyError, match="search_credits_exhausted"):
            await other.call("search", {}, "device", "third")
        await other.client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "account",
    [
        {"plan_limit": 100, "plan_usage": 0, "paygo_limit": 10},
        {"plan_limit": 0, "plan_usage": 0, "paygo_limit": 0},
        {"plan_limit": 100, "plan_usage": 0},
        {"plan_limit": "unlimited", "plan_usage": 0, "paygo_limit": 0},
        {"plan_limit": 100, "plan_usage": 0, "paygo_limit": None},
        {"current_plan": "Researcher", "plan_limit": 1000, "plan_usage": 0, "paygo_limit": None, "paygo_usage": 1},
        {"current_plan": "Researcher", "plan_limit": 1000, "plan_usage": 0, "paygo_limit": None, "paygo_usage": False},
    ],
)
def test_no_charged_request_when_prepaid_balance_or_overage_cannot_be_verified(tmp_path, account):
    async def run():
        _, service, _ = setup(tmp_path)
        seen = []

        def handle(request):
            seen.append(request.method)
            return httpx.Response(200, json={"account": account, "key": {"limit": 500, "usage": 0}})

        service.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with pytest.raises(TavilyError):
            await service.call("search", {}, "device", "one")
        assert seen == ["GET"]
        assert service.gw.store._db.execute("SELECT count(*) FROM tavily_credits").fetchone()[0] == 0

    asyncio.run(run())


def test_researcher_explicit_null_paygo_with_zero_usage_and_finite_plan_balance(tmp_path):
    async def run():
        _, service, _ = setup(tmp_path)
        seen = []

        def handle(request):
            seen.append(request.method)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "account": {
                            "current_plan": "Researcher",
                            "plan_limit": 1000,
                            "plan_usage": 0,
                            "paygo_limit": None,
                            "paygo_usage": 0,
                        },
                        "key": {"limit": None, "usage": 0},
                    },
                )
            return httpx.Response(200, json={"results": []})

        service.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        await service.search("Public question", [], 1, "device", "one")
        assert seen == ["GET", "POST"]
        assert service.gw.store._db.execute("SELECT sum(credits) FROM tavily_credits").fetchone()[0] == 1

    asyncio.run(run())


def test_public_page_import_needs_authentication_and_explicit_tavily_permission(tmp_path):
    async def run():
        h, _, seen = setup(tmp_path)
        asked = {"url": PAGE, "request_id": "ask_" + "0" * 26, "tavily_consent": True}
        assert (await h.client.post("/v1/web/extract", json=asked)).status_code == 401
        device = Device()
        await device.login(h.client)
        assert (
            await h.client.post("/v1/web/extract", json={**asked, "tavily_consent": False}, headers=device.headers())
        ).status_code == 422
        assert seen == []
        reply = await h.client.post("/v1/web/extract", json=asked, headers=device.headers())
        assert reply.status_code == 200, reply.text
        assert reply.json()["text"] == TEXT and reply.json()["url"] == PAGE
        assert [p for m, p, _ in seen if m == "POST"] == ["/extract"]
        repeated = await h.client.post("/v1/web/extract", json=asked, headers=device.headers())
        assert repeated.json()["error"]["code"] == "search_attempt_already_sent"
        assert [p for m, p, _ in seen if m == "POST"] == ["/extract"]

    asyncio.run(run())


def test_secret_source_exposes_only_the_tavily_key_to_the_gateway():
    source = TavilyEnvironmentSecrets({"TAVILY_API_KEY": "stub-tavily-key-not-real", "OTHER_KEY": "not-shared"})
    assert source.get("nebius_api_key") is None and source.get("other_key") is None
    assert source.get("tavily_api_key").reveal() == "stub-tavily-key-not-real"
    assert "stub" not in repr(source)
