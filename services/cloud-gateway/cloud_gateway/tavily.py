"""Bounded Tavily Search/Extract using existing credits only, with no stored queries or page content.

The account must have paid overage disabled. /usage is checked before every charged request. A conservative
one-credit reservation per basic request remains counted after failures, cancellation and restart; uncertain
usage is never refunded automatically. Nemotron inference uses its separate, existing dollar ledger.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import ipaddress
import json
import math
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cloud_gateway import minimise
from cloud_gateway.auth import AuthError

BASE = "https://api.tavily.com"
MAX_RESPONSE = 2_000_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS tavily_credits (
 identity TEXT PRIMARY KEY, day TEXT NOT NULL, credits INTEGER NOT NULL, state TEXT NOT NULL
);
"""


class TavilyError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def public_url(value: Any) -> str:
    """Only a public HTTPS page URL is sent to Tavily. The gateway never fetches that URL itself."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 for c in value):
            raise ValueError
        p = urlsplit(value)
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            raise ValueError
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
            raise ValueError
        if host.endswith((".local", ".localhost", ".internal", ".invalid", ".test")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if any(
            re.search(r"token|password|secret|signature|^key$|^sig$|^x-amz-|^x-goog-", k, re.I)
            for k, _ in parse_qsl(p.query)
        ):
            raise ValueError
        return urlunsplit(("https", host, p.path or "/", p.query, ""))
    except (ValueError, TypeError):
        raise TavilyError("invalid_public_url") from None


class Tavily:
    def __init__(self, gw: Any, client: httpx.AsyncClient | None = None):
        self.gw = gw
        self.client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=25)
        self.lock = asyncio.Lock()
        gw.store._db.executescript(SCHEMA)

    def identity(self, owner: str, request_id: str, operation: str) -> str:
        return hashlib.sha256(f"{owner}:{request_id}:{operation}".encode()).hexdigest()

    def reserve(self, identity: str) -> None:
        cfg, now = self.gw.config.tavily, self.gw.clock()
        if not cfg.enabled or cfg.expires_at is None or now >= cfg.expires_at.timestamp():
            raise TavilyError("search_credits_exhausted")
        day = dt.datetime.fromtimestamp(now, dt.UTC).date().isoformat()
        db = self.gw.store._db
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM tavily_credits WHERE identity=?", (identity,)).fetchone():
                raise TavilyError("search_attempt_already_sent")
            daily, total = db.execute(
                "SELECT coalesce(sum(CASE WHEN day=? OR state='held' THEN credits ELSE 0 END),0),"
                "coalesce(sum(credits),0) FROM tavily_credits",
                (day,),
            ).fetchone()
            if daily + 1 > cfg.daily_credits or total + 1 > cfg.total_credits:
                raise TavilyError("search_credits_exhausted")
            db.execute("INSERT INTO tavily_credits VALUES (?,?,1,'held')", (identity, day))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    async def request(self, method: str, path: str, key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with self.client.stream(
                method, BASE + path, headers={"authorization": "Bearer " + key}, json=body
            ) as reply:
                if reply.status_code != 200:
                    raise TavilyError("search_unavailable")
                chunks, size = [], 0
                async for part in reply.aiter_bytes():
                    size += len(part)
                    if size > MAX_RESPONSE:
                        raise TavilyError("search_unavailable")
                    chunks.append(part)
                value = json.loads(b"".join(chunks))
                if not isinstance(value, dict):
                    raise TavilyError("search_unavailable")
                return value
        except (httpx.HTTPError, ValueError) as error:
            if isinstance(error, TavilyError):
                raise
            raise TavilyError("search_unavailable") from None

    async def prepaid(self, key: str) -> None:
        usage = await self.request("GET", "/usage", key)
        account = usage.get("account", {})
        # The Researcher dashboard reports PAYG Off while /usage can return an
        # explicit null limit. Missing fields are still unknown, never zero.
        # Keep this compatibility case confined to an unused free-plan PAYG
        # bucket, with a separate, finite plan balance checked below.
        free_paygo_off = (
            isinstance(account, dict)
            and account.get("current_plan") == "Researcher"
            and "paygo_limit" in account
            and account["paygo_limit"] is None
            and type(account.get("paygo_usage")) in (int, float)
            and account["paygo_usage"] == 0
        )
        if not isinstance(account, dict) or not (
            free_paygo_off or (type(account.get("paygo_limit")) in (int, float) and account["paygo_limit"] == 0)
        ):
            raise TavilyError("search_prepaid_only")
        for counters in (account, usage.get("key", {})):
            if not isinstance(counters, dict):
                raise TavilyError("search_unavailable")
            limit = counters.get("plan_limit" if counters is account else "limit")
            used = counters.get("plan_usage" if counters is account else "usage")
            if counters is not account and "limit" in counters and limit is None:
                continue  # A key without its own limit still has the account's hard prepaid limit.
            checked: list[float] = []
            for value in (limit, used):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise TavilyError("search_unavailable")
                checked.append(float(value))
            if checked[0] - checked[1] < 1:
                raise TavilyError("search_credits_exhausted")

    async def call(self, operation: str, body: dict[str, Any], owner: str, request_id: str) -> dict[str, Any]:
        if (
            operation not in {"search", "extract"}
            or body.get("search_depth", "basic") != "basic"
            or body.get("extract_depth", "basic") != "basic"
            or body.get("auto_parameters", False) is not False
        ):
            raise TavilyError("search_unavailable")
        async with self.lock:
            secret = self.gw.secrets.get("tavily_api_key")
            if secret is None:
                raise TavilyError("search_not_configured")
            key = secret.reveal()
            await self.prepaid(key)
            identity = self.identity(owner, request_id, operation)
            self.reserve(identity)
            result = await self.request("POST", "/" + operation, key, body)
            self.gw.store._db.execute("UPDATE tavily_credits SET state='completed' WHERE identity=?", (identity,))
            return result

    async def extract(
        self, urls: list[str], owner: str, request_id: str, query: str | None = None
    ) -> list[dict[str, str]]:
        if not 1 <= len(urls) <= 5:
            raise TavilyError("invalid_public_url")
        canonical = [public_url(url) for url in urls[:5]]
        body: dict[str, Any] = {
            "urls": canonical,
            "extract_depth": "basic",
            "format": "text",
            "include_images": False,
            "include_usage": True,
            "timeout": 15,
        }
        if query:
            body.update(query=query[:2000], chunks_per_source=3)
        reply = await self.call("extract", body, owner, request_id)
        out = []
        results = reply.get("results", [])
        if not isinstance(results, list):
            raise TavilyError("search_unavailable")
        for item in results[:5]:
            if not isinstance(item, dict) or not isinstance(item.get("raw_content"), str):
                continue
            try:
                url = public_url(item.get("url"))
            except TavilyError:
                continue
            if url not in canonical:
                continue
            text = item["raw_content"].strip()
            if text and len(text) <= 180000:
                out.append({"url": url, "text": text})
        return out

    async def search(
        self, query: str, sites: list[str], limit: int, owner: str, request_id: str
    ) -> list[dict[str, str]]:
        body: dict[str, Any] = {
            "query": query[:2000],
            "search_depth": "basic",
            "max_results": min(limit, 6),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "auto_parameters": False,
            "safe_search": True,
            "include_usage": True,
        }
        if sites:
            body["include_domains"] = sites[:100]
        reply = await self.call("search", body, owner, request_id)
        results = reply.get("results", [])
        if not isinstance(results, list):
            raise TavilyError("search_unavailable")
        found = []
        for item in results[:6]:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("url", "title", "content")):
                continue
            try:
                url = public_url(item["url"])
            except TavilyError:
                continue
            host = urlsplit(url).hostname or ""
            if sites and not any(host == d or host.endswith("." + d) for d in sites):
                continue
            found.append({"url": url, "title": item["title"][:160], "snippet": item["content"][:3000]})
        if found:
            try:
                pages = await self.extract([i["url"] for i in found[:3]], owner, request_id, query)
                extracted = {p["url"]: p["text"] for p in pages}
                for item in found:
                    item["snippet"] = extracted.get(item["url"], item["snippet"])[:3000]
            except TavilyError:
                pass  # Search evidence remains usable; a failed extraction never silently creates more requests.
        return found


def add_routes(app: FastAPI, gw: Any) -> None:
    @app.get("/v1/web/status")
    async def status(request: Request) -> JSONResponse:
        try:
            gw.auth.authenticate(request.headers.get("authorization"))
        except AuthError:
            return JSONResponse({"error": {"code": "auth"}}, status_code=401, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {
                "enabled": gw.tavily is not None,
                "configured": gw.tavily is not None and gw.secrets.get("tavily_api_key") is not None,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/v1/web/extract")
    async def extract_page(request: Request) -> Any:
        try:
            session = gw.auth.authenticate(request.headers.get("authorization"))
            body = await gw.json_body(request, 4096)
            if not isinstance(body, dict) or set(body) != {"url", "request_id", "tavily_consent"}:
                raise TavilyError("invalid_public_url")
            if (
                body["tavily_consent"] is not True
                or not isinstance(body["request_id"], str)
                or not re.fullmatch(r"ask_[0-9A-HJKMNP-TV-Z]{26}", body["request_id"])
            ):
                raise TavilyError("web_permission_required")
            if minimise.refusal(request.headers, body):
                raise TavilyError("safety_blocked")
            url = public_url(body["url"])
            if gw.tavily is None:
                raise TavilyError("search_not_configured")
            pages = await gw.tavily.extract([url], session.credential_id, body["request_id"])
            if not pages:
                raise TavilyError("web_page_unreadable")
            page = pages[0]
            title = next(
                (line.strip().lstrip("# ") for line in page["text"].splitlines() if line.strip()),
                urlsplit(url).hostname or "Web page",
            )
            return JSONResponse(
                {"url": page["url"], "title": title[:160], "text": page["text"]}, headers={"Cache-Control": "no-store"}
            )
        except AuthError:
            return JSONResponse({"error": {"code": "auth"}}, status_code=401, headers={"Cache-Control": "no-store"})
        except TavilyError as error:
            status = (
                422
                if error.reason
                in {"invalid_public_url", "web_page_unreadable", "web_permission_required", "safety_blocked"}
                else 503
            )
            return JSONResponse(
                {"error": {"code": error.reason}}, status_code=status, headers={"Cache-Control": "no-store"}
            )
