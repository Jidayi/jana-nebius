"""Attached-identity credential refresh and provider destination boundaries."""

import asyncio

import httpx
import pytest
from cloud_gateway.config import ModelSpec, ProviderSpec
from cloud_gateway.providers.base import ProviderRequest, UpstreamError
from cloud_gateway.providers.vertex import METADATA_URL, VertexAdapter

BASE = "https://aiplatform.eu.rep.googleapis.com/v1/projects/jana-test-project-000000/locations/eu/publishers/google"


def spec(url=BASE):
    return ProviderSpec(adapter="vertex", base_url=url, secret="unused", models={})  # noqa: S106


def test_vertex_metadata_cached_and_never_sent_to_provider_as_key():
    async def run():
        seen = []

        def handle(request):
            seen.append(request)
            if str(request.url) == METADATA_URL:
                assert request.headers["Metadata-Flavor"] == "Google"
                assert "authorization" not in request.headers
                return httpx.Response(200, json={"access_token": "synthetic-runtime-token", "expires_in": 3600})
            assert str(request.url).startswith(BASE + "/models/gemini-3.8-flash:")
            assert request.headers["authorization"] == "Bearer synthetic-runtime-token"
            assert "x-goog-api-key" not in request.headers
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

        adapter = VertexAdapter(spec(), None, httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        request = ProviderRequest(
            ModelSpec(id="gemini-3.8-flash"), {"messages": [{"role": "user", "content": "hello"}]}, ""
        )
        await asyncio.gather(adapter.complete(request), adapter.complete(request))
        assert len(seen) == 3
        adapter._expires = 0
        await adapter.complete(request)
        assert sum(str(r.url) == METADATA_URL for r in seen) == 2
        assert "synthetic-runtime-token" not in repr(adapter)
        await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://aiplatform.googleapis.com/v1/projects/abcde/locations/eu/publishers/google",
        BASE + ".evil",
        BASE.replace("googleapis.com", "googleapis.com.evil"),
        BASE + "?key=x",
    ],
)
def test_vertex_refuses_credential_exfiltration_endpoint(url):
    with pytest.raises(ValueError, match="Google publisher"):
        VertexAdapter(spec(url), None, httpx.AsyncClient())


def test_vertex_metadata_failure_is_redacted():
    async def run():
        adapter = VertexAdapter(
            spec(),
            None,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"access_token": "never-print-this"}))
            ),
        )
        with pytest.raises(UpstreamError) as error:
            await adapter._request_headers()
        assert str(error.value) == "upstream_auth: runtime identity unavailable"
        await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "location,host",
    [
        ("global", "aiplatform.googleapis.com"),
        ("eu", "aiplatform.eu.rep.googleapis.com"),
        ("us", "aiplatform.us.rep.googleapis.com"),
        ("europe-west2", "europe-west2-aiplatform.googleapis.com"),
    ],
)
def test_vertex_uses_the_documented_host_for_each_location(location, host):
    async def run():
        url = f"https://{host}/v1/projects/jana-test-project-000000/locations/{location}/publishers/google"
        adapter = VertexAdapter(spec(url), None, httpx.AsyncClient())
        await adapter.aclose()

    asyncio.run(run())


def test_vertex_rejects_a_host_location_mismatch():
    with pytest.raises(ValueError, match="Google publisher"):
        VertexAdapter(spec(BASE.replace("/locations/eu/", "/locations/us/")), None, httpx.AsyncClient())
