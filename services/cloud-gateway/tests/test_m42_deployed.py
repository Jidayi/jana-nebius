"""Opt-in synthetic M42 checks against an actual TLS gateway, never an in-process transport.

Operator files must live outside the repository. No development key or production licence hierarchy is loaded.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import time
from pathlib import Path

import httpx
import pytest
from agent_core.config import Settings
from agent_core.engine.study import StudyDesk
from agent_core.store.sqlite import open_database
from cloud_gateway.auth import signed_message
from gateway_stubs import Device
from test_m42_quality_corpus import CORPUS, walk

LIVE = os.environ.get("JANA_M42_DEPLOYED") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="Explicit deployed staging check only")


class StagingDevice(Device):
    async def register(self, client, licence="", document=None):
        entitlement = json.loads(Path(os.environ["JANA_STAGING_ENTITLEMENT"]).read_text())
        return await super().register(client, entitlement["licence_id"], entitlement)

    def sign(self, nonce, audience=""):
        return base64.b64encode(
            self.key.sign(signed_message(base64.b64decode(nonce), os.environ["JANA_STAGING_AUDIENCE"]))
        ).decode()


def tls_client():
    origin = os.environ["JANA_STAGING_ORIGIN"]
    assert origin.startswith("https://")
    certificate = Path(os.environ["JANA_STAGING_CA"]) if os.environ.get("JANA_STAGING_CA") else None
    if certificate is not None:
        assert certificate.is_absolute() and ".git" not in certificate.parts
    return httpx.AsyncClient(
        base_url=origin,
        verify=ssl.create_default_context(cafile=certificate),
        trust_env=False,
        follow_redirects=False,
        timeout=240,
    )


def test_deployed_full_quality_corpus(tmp_path):
    async def run():
        corpus = json.loads(CORPUS.read_text())
        selected = os.environ.get("JANA_M42_QUALITY_CASE")
        selected_ids = set(selected.split(",")) if selected else None
        cases = [c for c in corpus["cases"] if selected_ids is None or c["id"] in selected_ids]
        assert cases and (selected_ids is None or {c["id"] for c in cases} == selected_ids)
        workers = int(os.environ.get("JANA_M42_QUALITY_WORKERS", "2"))
        assert workers in (1, 2), "Use one or two workers within the approved reservation ceiling"
        destination = Path(os.environ["JANA_M42_QUALITY_REPORT"])
        assert not destination.exists(), "Preserve the previous live observations"
        report = {
            "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "model": "gemini-3.8-flash",
            "provider": "Vertex AI EU attached identity",
            "provider_endpoint": os.environ["JANA_STAGING_VERTEX_ENDPOINT"],
            "gateway": os.environ["JANA_STAGING_ORIGIN"],
            "transport": "TLS over IAP" if os.environ.get("JANA_STAGING_CA") else "public HTTPS/system CA",
            "synthetic": True,
            "full_corpus": selected is None,
            "independent_content_review": False,
            "cases": [],
            "max_usd": float(os.environ.get("JANA_M42_TEST_MAX_USD", "2")),
            "workers": workers,
            "complete": False,
            "passed": False,
        }

        def checkpoint():
            report["complete"] = len(report["cases"]) == len(corpus["cases"])
            report["passed"] = report["complete"] and all(c["passed"] for c in report["cases"])
            report["selection_passed"] = len(report["cases"]) == len(cases) and all(
                c["passed"] for c in report["cases"]
            )
            destination.write_text(json.dumps(report, indent=2) + "\n")

        queue = asyncio.Queue()
        for case in cases:
            queue.put_nowait(case)

        async def worker(index):
            conn, _ = open_database(tmp_path / f"core-{index}.db", "learner")
            desk = StudyDesk(conn, lambda: int(time.time() * 1000), Settings())
            async with tls_client() as client:
                device = StagingDevice()
                await device.login(client)
                while not queue.empty():
                    case = queue.get_nowait()
                    started = time.monotonic()
                    row = {k: case[k] for k in ("id", "kind", "subject", "expected")}
                    row["passed"] = False
                    jid = ""
                    try:
                        await device.login(client)
                        sources = [
                            desk.create({"kind": "text", "title": case["title"], "text": text})
                            for text in case["sources"]
                        ]
                        selections = [{"source_id": s["source_id"], "revision": 1} for s in sources]
                        request = {"kind": case["kind"], "sources": selections, "execution": "prefer_cloud"}
                        if case["prompt"] is not None:
                            request["prompt"] = case["prompt"]
                        if case["kind"] in ("quiz", "flashcards"):
                            request["count"] = 2
                        job = desk.create_job(request)
                        jid = job["job_id"]
                        job["state"] = "running"
                        desk.save_job(job)
                        chunks = desk.selected(selections)
                        body = {k: v for k, v in request.items() if k not in ("sources", "execution")}
                        body.update(request_id=jid, chunks=chunks, output_locale="en")
                        result = await client.post("/v1/study/process", json=body, headers=device.headers())
                        row["http_status"] = result.status_code
                        output = result.json()
                        row["response"] = output
                        if case["expected"] == "insufficient_evidence":
                            assert result.status_code == 422 and output["error"]["code"] == "insufficient_evidence"
                        else:
                            assert result.status_code == 200, output.get("error", {}).get("code")
                            groups = (
                                len(output["claims"])
                                + len(output.get("flashcards", []))
                                + len(output.get("quiz", {}).get("items", []))
                            )
                            aid = desk.commit_aid(job, output, [True] * groups)
                            assert aid["status"] == "ready" and aid["sources"] == selections
                            for value in walk(output):
                                for citation in value.get("citations", []):
                                    chunk = next(c for c in chunks if c["chunk_id"] == citation["chunk_id"])
                                    assert chunk["text"][citation["start"] : citation["end"]] == citation["quote"]
                            text = " ".join(str(v.get("text", "")) for v in walk(output)).lower()
                            assert any(concept.lower() in text for concept in case["concepts"])
                            for forbidden in case.get("forbidden", []):
                                assert forbidden.lower() not in json.dumps(output).lower()
                            if aid.get("quiz_id"):
                                student = desk.quiz(aid["quiz_id"])["view"]
                                assert "keys" not in student and all("explanation" not in i for i in student["items"])
                        row["passed"] = True
                    except Exception as error:
                        row["failure"] = type(error).__name__ + ": " + str(error)[:200]
                    finally:
                        if jid:
                            cleanup = await client.delete("/v1/study/requests/" + jid, headers=device.headers())
                            row["cleanup_ack"] = cleanup.status_code == 204
                            row["passed"] = row["passed"] and row["cleanup_ack"]
                        row["elapsed_s"] = round(time.monotonic() - started, 3)
                        report["cases"].append(row)
                        checkpoint()
                        print(
                            f"deployed {len(report['cases'])}/{len(cases)} {case['id']} "
                            f"{'PASS' if row['passed'] else 'FAIL'}",
                            flush=True,
                        )
                        if row.get("http_status") in (401, 403, 429, 502, 503):
                            # Stop on auth, spend or service faults; do not fan out a broken deployment.
                            raise AssertionError(row.get("failure", "deployment admission failed"))
            assert conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
            conn.close()

        await asyncio.gather(*(worker(index) for index in range(workers)))
        assert all(c["passed"] for c in report["cases"]), [c["id"] for c in report["cases"] if not c["passed"]]

    asyncio.run(run())


def test_deployed_uploads_ocr_recording_and_boundaries(tmp_path):
    import io
    import secrets
    import subprocess
    import sys
    import zipfile

    from PIL import Image, ImageDraw, ImageFont
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    text = "Enzymes are biological catalysts."
    image = Image.new("RGB", (1600, 500), "white")
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 55)
    ImageDraw.Draw(image).text((80, 150), text, font=font, fill="black")
    photo = io.BytesIO()
    image.save(photo, format="PNG")
    scanned = io.BytesIO()
    image.save(scanned, format="PDF", resolution=150)
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font_object = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font_object)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 18 Tf 40 700 Td (Enzymes are biological catalysts.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    pdf = io.BytesIO()
    writer.write(pdf)
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", f"<document><body><p><r><t>{text}</t></r></p></body></document>")
    samples = [
        ("text", "document", "text/plain", text.encode()),
        (
            "docx",
            "document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            docx.getvalue(),
        ),
        ("pdf", "pdf", "application/pdf", pdf.getvalue()),
        ("photo-ocr", "photo", "image/png", photo.getvalue()),
        ("scanned-pdf-ocr", "pdf", "application/pdf", scanned.getvalue()),
    ]
    if sys.platform == "darwin":
        recording = tmp_path / "synthetic.wav"
        subprocess.run(
            ["/usr/bin/say", "--file-format=WAVE", "--data-format=LEI16@16000", "-o", str(recording), text], check=True
        )
        samples.append(("recording", "recording", "audio/wav", recording.read_bytes()))

    async def run():
        report = {"synthetic": True, "gateway": os.environ["JANA_STAGING_ORIGIN"], "checks": []}
        destination = Path(os.environ["JANA_M42_UPLOAD_REPORT"])
        assert not destination.exists()
        async with tls_client() as client:
            one, two = StagingDevice(), StagingDevice()
            await one.login(client)
            await two.login(client)
            assert (await client.post("/v1/study/process", json={})).status_code == 401
            assert (await client.post("/v1/devices", json={"public_key": one.public_key()})).status_code == 403
            assert (await client.post("/v1/chat/completions", json={})).status_code == 404
            for name, kind, mime, raw in samples:
                row = {"name": name, "passed": False}
                jid = "stj_" + "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(26))
                sid = "src_" + "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(26))
                try:
                    digest = hashlib.sha256(raw).hexdigest()
                    grant = await client.post(
                        "/v1/study/uploads",
                        json={
                            "request_id": jid,
                            "kind": kind,
                            "mime_type": mime,
                            "byte_length": len(raw),
                            "sha256": digest,
                        },
                        headers=one.headers(),
                    )
                    assert grant.status_code == 200, grant.text
                    uid = grant.json()["upload_id"]
                    path = f"/v1/study/uploads/{uid}/chunks/0"
                    part = {"offset": 0, "sha256": digest, "data_base64": base64.b64encode(raw).decode()}
                    assert (await client.put(path, json=part, headers=two.headers())).status_code == 404
                    sent = await client.put(path, json=part, headers=one.headers())
                    assert sent.status_code == 200 and sent.json()["complete"]
                    assert (await client.put(path, json=part, headers=one.headers())).json() == sent.json()
                    body = {"request_id": jid, "upload_id": uid, "source_id": sid, "revision": 1, "locale": "en"}
                    result = await client.post("/v1/study/extract", json=body, headers=one.headers())
                    row["status"] = result.status_code
                    row["response"] = result.json()
                    assert result.status_code == 200, result.text
                    value = result.json()
                    assert "enzymes" in " ".join(c["text"] for c in value["chunks"]).lower()
                    assert not value["unreadable_units"]
                    assert (await client.post("/v1/study/extract", json=body, headers=one.headers())).json() == value
                    if kind == "recording":
                        assert value["duration_ms"] > 0 and value["chunks"][0]["locator"]["kind"] == "time"
                    row["passed"] = True
                except Exception as error:
                    row["failure"] = type(error).__name__ + ": " + str(error)[:200]
                finally:
                    row["cleanup_ack"] = (
                        await client.delete("/v1/study/requests/" + jid, headers=one.headers())
                    ).status_code == 204
                    row["passed"] = row["passed"] and row["cleanup_ack"]
                    report["checks"].append(row)
                    destination.write_text(json.dumps(report, indent=2) + "\n")
                    print(name, "PASS" if row["passed"] else "FAIL", flush=True)
        assert all(row["passed"] for row in report["checks"]), [
            row["name"] for row in report["checks"] if not row["passed"]
        ]

    asyncio.run(run())
