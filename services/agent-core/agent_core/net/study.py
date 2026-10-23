"""M42 cloud coordinator transport. Every send uses the existing pinned, consent-gated egress client."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any

from agent_core.contracts import errors
from agent_core.net.client import NetError
from agent_core.net.policy import EgressRefused
from agent_core.net.redaction import Redactor
from agent_core.store import consents, subscription
from agent_core.store.egress import DeviceSpend


class StudyCloudError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StudyCloud:
    def __init__(self, layer: Any, profile: Callable[[], str | None], connection: Callable[[], Any]):
        self.layer, self.profile, self.connection = layer, profile, connection

    def meter(self, conn: Any, output: dict[str, Any]) -> None:
        usage = output.get("usage")
        if usage is None:
            return  # Compatible with an older gateway; release qualification requires usage receipts.
        if errors("study/workspace#/$defs/UsageReceipt", usage):
            raise StudyCloudError("processing_failed")
        pid = self.guard(conn)
        DeviceSpend(
            self.layer.device,
            pid,
            subscription.allowance_period(self.layer.subscription(), self.layer.clock_ms()),
            self.layer.clock_ms,
        ).add_study(usage["receipt_id"], usage["cost_usd"], usage["input_tokens"] + usage["output_tokens"])

    def guard(self, conn: Any) -> str:
        pid = self.profile()
        if conn is not self.connection() or pid is None:
            raise StudyCloudError("consent_required")
        if not {"study_materials", "cloud_tier"} <= self.layer.features_on():
            raise StudyCloudError("consent_required")
        if not subscription.covers(self.layer.subscription(), pid, self.layer.clock_ms()):
            raise StudyCloudError("allowance_exhausted")
        band = conn.execute("SELECT age_band FROM profile").fetchone()
        for scope in ("study_materials", "cloud_tier"):
            row = consents.active(conn, scope)
            if row is None or row[5] is not None:
                raise StudyCloudError("consent_required")
            if band and band[0] != "18_plus" and (row[1] != "guardian" or row[2] != "checkout_guardian"):
                raise StudyCloudError("consent_required")
            expiry = conn.execute("SELECT expires_at FROM consents WHERE consent_id=?", (row[0],)).fetchone()
            if expiry and expiry[0] is not None and expiry[0] <= self.layer.clock_ms():
                raise StudyCloudError("consent_required")
        return pid

    async def send(
        self,
        conn: Any,
        method: str,
        path: str,
        body: Any = None,
        *,
        cleanup: bool = False,
        attempt: int = 1,
        request_id: str | None = None,
    ) -> Any:
        pid = self.profile() if cleanup else self.guard(conn)
        try:
            token = await self.layer.credential.token()
            if not cleanup:
                self.guard(conn)  # token renewal may have yielded through a profile/consent change
            reply = await self.layer.client.send(
                "study_materials",
                method,
                "https://" + self.layer.host_for("study_materials") + path,
                "tombstone" if cleanup else "study_material",
                body=body,
                headers={"authorization": "Bearer " + token, "x-study-attempt": str(attempt)},
                profile_id=pid,
                timeout_s=9000 if path == "/v1/study/extract" else 360,
            )
        except EgressRefused as error:
            raise StudyCloudError("waiting_online" if error.reason == "offline" else "consent_required") from None
        except NetError:
            raise StudyCloudError("waiting_online") from None
        if not cleanup:
            self.guard(conn)
            identity = request_id or (body.get("request_id") if isinstance(body, dict) else None)
            if identity:
                conn.execute(
                    "UPDATE study_cloud_cleanup SET expires_at=? WHERE request_id=?",
                    (self.layer.clock_ms() + 900000, identity),
                )
        if not 200 <= reply.status < 300:
            code = reply.body.get("error", {}).get("code", "") if isinstance(reply.body, dict) else ""
            raise StudyCloudError(
                code
                if code
                in (
                    "allowance_exhausted",
                    "consent_required",
                    "insufficient_evidence",
                    "source_too_large",
                    "encrypted_source",
                    "corrupt_source",
                    "unreadable_source",
                    "model_unavailable",
                    "safety_blocked",
                )
                else "processing_failed"
            )
        return reply.body

    def owe(self, conn: Any, jid: str, sources: list[dict[str, Any]]) -> None:
        # Opaque ids only. A receipt survives source erasure; it never contains source content or a credential.
        for source in sources:
            conn.execute(
                "INSERT INTO study_cloud_cleanup VALUES (?,?,?) "
                "ON CONFLICT(request_id,source_id) DO UPDATE SET expires_at=excluded.expires_at",
                (jid, source["source_id"], self.layer.clock_ms() + 900000),
            )

    async def cleanup(self, conn: Any) -> None:
        for jid, expiry in conn.execute("SELECT DISTINCT request_id,expires_at FROM study_cloud_cleanup").fetchall():
            if expiry > self.layer.clock_ms():
                try:
                    await self.send(conn, "DELETE", "/v1/study/requests/" + jid, cleanup=True)
                except Exception:  # noqa: S112 - retain receipt; transport bodies are never logged
                    continue
            conn.execute("DELETE FROM study_cloud_cleanup WHERE request_id=?", (jid,))

    async def process(
        self,
        conn: Any,
        jid: str,
        request: dict[str, Any],
        chunks: list[dict[str, Any]],
        attempt: int,
        batch_index: int = 0,
    ) -> dict[str, Any]:
        self.guard(conn)
        original_jid = jid
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        number = int(hashlib.sha256(f"{jid}:{batch_index}".encode()).hexdigest()[:32], 16)
        chars = []
        for _ in range(26):
            chars.append(alphabet[number % 32])
            number //= 32
        jid = "stj_" + "".join(reversed(chars))
        profile = conn.execute("SELECT display_name,profile_id FROM profile").fetchone()
        body: dict[str, Any] = {
            "request_id": jid,
            "kind": request["kind"],
            "chunks": chunks,
            "output_locale": "en",
            **{k: request[k] for k in ("prompt", "count", "settings", "syllabus_outline") if k in request},
        }
        if Redactor(profile or ()).blocks(body):
            raise StudyCloudError("safety_blocked")
        self.owe(conn, jid, request["sources"])
        output = await self.send(conn, "POST", "/v1/study/process", body, attempt=attempt)
        if errors("study/workspace#/$defs/ProcessingResponse", output):
            raise StudyCloudError("insufficient_evidence")
        if output["request_id"] != jid:
            raise StudyCloudError("insufficient_evidence")
        self.meter(conn, output)
        return {**output, "request_id": original_jid}

    async def extract(
        self, conn: Any, jid: str, request: dict[str, Any], source: dict[str, Any], data: bytes
    ) -> list[dict[str, Any]]:
        self.guard(conn)
        self.owe(conn, jid, request["sources"])
        attempt = conn.execute("SELECT attempt FROM study_jobs WHERE job_id=?", (jid,)).fetchone()[0]
        grant = await self.send(
            conn,
            "POST",
            "/v1/study/uploads",
            {
                "request_id": jid,
                "kind": source["kind"],
                "mime_type": "application/octet-stream",
                "byte_length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            attempt=attempt,
        )
        if errors("study/workspace#/$defs/CloudUploadGrant", grant):
            raise StudyCloudError("processing_failed")
        for offset in range(0, len(data), 1048576):
            part = data[offset : offset + 1048576]
            await self.send(
                conn,
                "PUT",
                f"/v1/study/uploads/{grant['upload_id']}/chunks/{offset // 1048576}",
                {
                    "offset": offset,
                    "sha256": hashlib.sha256(part).hexdigest(),
                    "data_base64": base64.b64encode(part).decode(),
                },
                attempt=attempt,
                request_id=jid,
            )
        page = await self.send(
            conn,
            "POST",
            "/v1/study/extract",
            {
                "request_id": jid,
                "upload_id": grant["upload_id"],
                "source_id": source["source_id"],
                "revision": source["revision"],
                "locale": "en",
            },
            attempt=attempt,
        )
        chunks, unreadable = [], []
        duration_ms = page.get("duration_ms")
        seen = set()
        while True:
            if (
                errors("study/workspace#/$defs/ExtractionResponse", page)
                or page["sha256"] != hashlib.sha256(data).hexdigest()
            ):
                raise StudyCloudError("processing_failed")
            chunks += page["chunks"]
            unreadable = page["unreadable_units"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
            if cursor in seen or len(chunks) > 10000:
                raise StudyCloudError("processing_failed")
            seen.add(cursor)
            page = await self.send(
                conn, "GET", f"/v1/study/extractions/{jid}/chunks?cursor={cursor}", attempt=attempt, request_id=jid
            )
        self.meter(conn, page)
        # The local store owns final chunk identities, normalization and redaction. Never trust remote offsets.
        units: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            if chunk["source_id"] != source["source_id"] or chunk["revision"] != source["revision"]:
                raise StudyCloudError("processing_failed")
            key = json.dumps(chunk["locator"], sort_keys=True)
            unit = units.setdefault(key, {"locator": chunk["locator"], "text": "", "ocr": True})
            unit["text"] += chunk["text"]
        result = list(units.values())
        for page_number in unreadable:
            result.insert(
                min(page_number - 1, len(result)),
                {
                    "locator": (
                        {
                            "kind": "time",
                            "start_ms": (page_number - 1) * 60000,
                            "end_ms": min(page_number * 60000, duration_ms),
                        }
                        if source["kind"] == "recording" and duration_ms
                        else {"kind": "page", "page": page_number}
                    ),
                    "text": "",
                    "ocr": True,
                },
            )
        return result
