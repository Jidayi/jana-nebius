"""Crash records and logs keep no prompt, answer or student text (OBS-16, OBS-17, OBS-19, PRV-09). A synthetic distress
sentence is pushed through every way text reaches a log line or a crash record, and must never come out."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.security import LaunchSecret
from agent_core.config import Settings
from agent_core.net.crash_reports import build_report
from agent_core.store.sessions import SessionStore
from agent_core.trace.crashes import CrashStore
from agent_core.trace.logs import DIAGNOSTIC_WORDS, DiagnosticFormatter, diagnostic, diagnostic_lines
from api_harness import cli
from pydantic import BaseModel, ValidationError

DISTRESS = "I want to hurt myself and I can't do this anymore"
WORDS = Path(__file__).resolve().parents[1] / "agent_core" / "trace" / "diagnostic_words.json"


def _store(tmp_path: Path) -> CrashStore:
    return CrashStore(tmp_path / "crashes", b"k" * 32, "1.0.0", Settings(), clock_ms=lambda: int(time.time() * 1000))


def test_runtime_stderr_tail_withholds_content(tmp_path: Path) -> None:
    """llama-server's stderr may echo a prompt: only diagnostic lines enter the record, and the report built from it
    for upload carries none of the sentence."""
    store = _store(tmp_path)
    stderr = ["llama_model_load: loaded meta data with 33 key-value pairs",
              f"slot update_slots: id 0 | task 3 | prompt: {DISTRESS}", DISTRESS.upper(),
              "GGML_ASSERT(ctx) failed", "main: exiting due to model loading error"]  # fmt: skip
    record = store.record_runtime_exit(134, stderr, model="test-model")
    assert record["log_tail"] == ["llama_model_load: loaded meta data with 33 key-value pairs", "[withheld 2 lines]",
                                  "GGML_ASSERT(ctx) failed", "[withheld 1 line]"]  # fmt: skip
    dumped = json.dumps(store.records()) + json.dumps(build_report(record, "mid"))
    assert "hurt" not in dumped.lower()


def test_inbox_records_are_filtered_again(tmp_path: Path) -> None:
    """A record another process wrote (the shell's inbox) goes through the same allow-list when taken in."""
    store = _store(tmp_path)
    raw = {"process": "shell", "kind": "panic", "version": "1.0.0", "stack": [], "log_tail": [DISTRESS, "done"]}
    (store.folder / "inbox" / "1.json").write_text(json.dumps(raw))
    (taken,) = store.ingest_inbox()
    assert taken["log_tail"] == ["[withheld 1 line]", "done"]


def test_uncaught_exception_never_prints_its_message(tmp_path: Path) -> None:
    """The core's crash hook prints an uncaught exception as its type and frames: the message (which may quote the
    student) reaches neither stderr nor the record."""
    script = f"""
import logging, sys
from pathlib import Path
from agent_core.config import Settings
from agent_core.trace.crashes import CrashStore
from agent_core.trace.logs import diagnostic_logging
diagnostic_logging()
store = CrashStore(Path(sys.argv[1]), b"k" * 32, "1.0.0", Settings())
store.install_hooks("core")
logging.getLogger("agent_core.test").warning("answer %s", {DISTRESS!r})
logging.getLogger("agent_core.test").warning(f"answer {DISTRESS}")
raise RuntimeError({DISTRESS!r})
"""
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path / "crashes")], capture_output=True, text=True,
                          timeout=60, check=False)  # fmt: skip
    assert done.returncode != 0
    assert "RuntimeError" in done.stderr and "hurt" not in done.stderr.lower()
    records = list((tmp_path / "crashes" / "records").glob("*.json"))
    assert records and "hurt" not in records[0].read_text().lower()


def test_logging_never_writes_arguments_or_messages() -> None:
    """A log record's arguments and an exception's message are never written; a validation error quoting its input
    (pydantic's `input_value`) leaves only its type and frames."""

    class Body(BaseModel):
        n: int

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(DiagnosticFormatter())
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    try:
        logger.error("request body %s", {"text": DISTRESS})
        try:
            Body.model_validate({"n": DISTRESS})
        except ValidationError:
            logger.exception("Exception in ASGI application")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "ValidationError" in out and "Exception in ASGI application" in out
    assert "hurt" not in out.lower() and "input_value" not in out


def test_error_messages_never_echo_the_body(tmp_path: Path) -> None:
    """A body that breaks its contract is refused with the path and the rule, never the value (API-32: messages are
    for logs)."""
    core = CoreService(Settings(), lambda entry: None, SessionStore(tmp_path / "sessions"))
    app = create_app(core, LaunchSecret("launch-secret"), lambda: 8765)

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            body = {"client_session_id": cli(), "mode": DISTRESS, "subject": "physics", "level": "O",
                    "origin": {"kind": "ask", "ref": None}}  # fmt: skip
            headers = {"authorization": "Bearer launch-secret", "idempotency-key": cli()}
            return await client.post("/v1/sessions", json=body, headers=headers)

    import asyncio

    reply = asyncio.run(scenario())
    assert reply.status_code == 422 and "$.mode" in reply.text
    assert "hurt" not in reply.text.lower()


@pytest.mark.parametrize(
    "line",
    [DISTRESS, DISTRESS.upper(), "my teacher hits me", "please help", "he said I am stupid", "x = 3 because I guessed"],
)
def test_content_lines_are_withheld(line: str) -> None:
    assert not diagnostic(line)
    assert diagnostic_lines([line]) == ["[withheld 1 line]"]


def test_vocabulary_has_no_words_of_feeling_or_harm() -> None:
    """The vocabulary the shell and the core share holds technical words only: none a student would use to say how
    they feel or what happened to them (the distress patterns' words, pronouns for people)."""
    banned = {"i", "me", "my", "myself", "you", "your", "he", "she", "him", "her", "they", "them", "we", "us", "want",
              "help", "hurt", "kill", "killed", "die", "dead", "cut", "harm", "suicide", "abuse", "bully", "hit",
              "beat", "touch", "safe", "home", "live", "alive", "afraid", "scared", "please", "sad",
              "hate"}  # fmt: skip
    assert not banned & DIAGNOSTIC_WORDS
    assert json.loads(WORDS.read_text())["words"] == sorted(DIAGNOSTIC_WORDS)
