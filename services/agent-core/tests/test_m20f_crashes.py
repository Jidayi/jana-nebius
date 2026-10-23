"""M20.f: local crash capture, opt-in crash upload and the debug bundle (OBS-16, OBS-17, OBS-18). Crashes are injected
on purpose; the "student", the secrets and every record are synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.net import crash_reports
from agent_core.store import egress as egress_store
from agent_core.store.exports import open_with_passphrase
from agent_core.store.keystore import MemoryKeyStore
from agent_core.trace.crashes import CrashStore, device_key
from agent_core.trace.debug_bundle import (
    CONVERSATION,
    BundleInputs,
    BundleRefused,
    SupportShares,
    bundle_files,
    preview,
    save_bundle,
)
from cryptography.exceptions import InvalidTag
from net_harness import HOSTS, FakeServices, enable, layer

STUDENT = "Ama Mensah-Testcase"  # a made-up name seeded to prove it never leaves
QUESTION = "a seeded question about a falling ball"
NOTE_PRIVATE = "a note the student kept private"
NOTE_SHARED = "a note the student allowed for support"
SECRETS = (b"seeded-keychain-secret-0001", b"seeded-profile-key-0002")
DAY_MS = 86_400_000
FAST = Settings(passphrase_argon2_memory_kib=8192, passphrase_argon2_iterations=1)
PASSPHRASE = "a long synthetic adult passphrase"  # noqa: S105 (a synthetic test passphrase)


def _store(tmp_path: Path, clock: list[int] | None = None) -> CrashStore:
    now = clock if clock is not None else [int(time.time() * 1000)]
    return CrashStore(tmp_path / "crashes", device_key(_keys(tmp_path)), "1.0.0", Settings(), clock_ms=lambda: now[0])


_KEYS: dict[str, MemoryKeyStore] = {}


def _keys(tmp_path: Path) -> MemoryKeyStore:
    return _KEYS.setdefault(str(tmp_path), MemoryKeyStore())


# --- OBS-16 -------------------------------------------------------------------------------------------------------

CRASHING_PROCESS = """
import sys, threading
from pathlib import Path
from agent_core.config import Settings
from agent_core.trace.crashes import CrashStore
store = CrashStore(Path(sys.argv[1]), b"k" * 32, "1.0.0", Settings())
store.install_hooks(sys.argv[2], correlation=lambda: {"epoch": "0123456789abcdef", "turn_id": "trn_TEST"})
def turn():
    student_text = "{question}"
    raise RuntimeError(student_text)
if sys.argv[3] == "exception":
    turn()
import faulthandler
faulthandler._sigsegv()
""".replace("{question}", QUESTION)


def _crash(folder: Path, process: str, how: str) -> int:
    done = subprocess.run([sys.executable, "-c", CRASHING_PROCESS, str(folder), process, how], capture_output=True,
                          timeout=60, check=False)  # fmt: skip
    return done.returncode


def obs16_crash_record_per_process(tmp_path: Path) -> None:
    """An injected crash in each process leaves a crash record with a stack and correlation ids: an uncaught exception
    in the core, a fatal error in the worker (faulthandler, taken in at the next start), a runtime exit with its
    stderr tail, a worker limit kill, and the shell's panic record from its inbox. No record keeps the error message
    (it may quote student text)."""
    store = _store(tmp_path)
    assert _crash(store.folder, "core", "exception") != 0
    assert _crash(store.folder, "worker", "fatal") != 0
    faults = store.ingest_faults()
    assert [r["process"] for r in faults] == ["worker"] and faults[0]["kind"] == "fatal_error"
    assert faults[0]["stack"], "the fatal error's frames"

    store.record_runtime_exit(139, [f"llama line {i}" for i in range(500)], model="qwen3-vl-8b",
                              correlation={"epoch": "0123456789abcdef"})  # fmt: skip
    store.record_worker_kill("sympy_solve", "cpu_seconds", correlation={"turn_id": "trn_TEST", "call_id": "call_1"})
    shell = {"process": "shell", "kind": "panic", "version": "1.0.0", "error_type": "panic",
             "stack": [{"module": "jana_shell::supervisor", "offset": "supervise"}],
             "correlation": {"epoch": "0123456789abcdef"}, "log_tail": [], "detail": {}}  # fmt: skip
    (store.folder / "inbox" / "1-1.json").write_text(json.dumps(shell))
    store.ingest_inbox()

    records = {r["process"]: r for r in store.records()}
    assert set(records) == {"core", "worker", "runtime", "shell"}
    core = records["core"]
    assert core["kind"] == "exception" and core["error_type"] == "RuntimeError"
    assert any(frame["function"] == "turn" for frame in core["stack"])
    assert core["correlation"] == {"epoch": "0123456789abcdef", "turn_id": "trn_TEST"}
    assert len(records["runtime"]["log_tail"]) == Settings().crash_stderr_tail_lines
    assert records["runtime"]["detail"]["exit_code"] == 139
    assert records["shell"]["stack"][0]["module"] == "jana_shell::supervisor"
    worker = [r for r in store.records() if r["process"] == "worker"]
    assert {r["kind"] for r in worker} == {"fatal_error", "worker_limit"}
    assert QUESTION not in json.dumps(store.records()), "no record quotes the error message"

    # The supervisor reports a worker it kills for a limit (here a timeout) with the tool and the call id only.
    killed: list[tuple[str, str, str]] = []
    asyncio.run(_timeout_kill(killed))
    assert killed == [("sympy_solve", "timeout", "call_obs16")]


class _StuckWorker:
    """A stand-in worker process that never answers a call (the supervisor's limit path, no real process)."""

    alive = True
    reduced_protection = False

    async def start(self) -> None:
        return None

    async def hello(self, placement: str, timeout: float) -> dict[str, Any]:
        return {"functions": [{"name": "sympy_solve"}]}

    async def request(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        raise TimeoutError

    def kill(self) -> None:
        self.alive = False

    async def close(self, grace: float = 0.0) -> None:
        return None


async def _timeout_kill(killed: list[tuple[str, str, str]]) -> None:
    from agent_core.tools.worker.supervisor import WorkerSupervisor

    supervisor = WorkerSupervisor(lambda: _StuckWorker(), Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,)))  # type: ignore[arg-type, return-value]
    supervisor.on_recycle = lambda tool, code, call: killed.append((tool, code, call))
    await supervisor.start()
    outcome = await supervisor.call("sympy_solve", 1, {"x": "synthetic"}, "chk_obs16", 100, call_id="call_obs16")
    assert outcome.error == "timeout"


def obs16_minidump_encrypted_and_bounded(tmp_path: Path) -> None:
    """A minidump on disk is unreadable without the device database key, holds none of the seeded keychain secrets,
    and is gone after its retention; its record outlives it until the record's own retention."""
    clock = [int(time.time() * 1000)]
    store = _store(tmp_path, clock)
    record = store.record("shell", "signal", [{"module": "jana_shell", "offset": "0x1f00"}])
    raw = b"MDMP" + os.urandom(64) + SECRETS[0] + b"stack memory" + SECRETS[1] + os.urandom(64)
    path = store.store_minidump(record["crash_id"], raw, SECRETS)
    sealed = path.read_bytes()
    assert b"MDMP" not in sealed and b"stack memory" not in sealed
    assert not any(secret in sealed for secret in SECRETS)
    with pytest.raises(InvalidTag):
        CrashStore(store.folder, b"\x00" * 32, "1.0.0", Settings()).read_minidump(path)
    opened = store.read_minidump(path)
    assert opened.startswith(b"MDMP") and b"stack memory" in opened
    assert not any(secret in opened for secret in SECRETS), "the secrets were zeroised before sealing"
    assert device_key(_keys(tmp_path)) == store.key, "the key lives in the key store, not the data folder"
    assert not any(store.key in p.read_bytes() for p in store.folder.rglob("*") if p.is_file())

    settings = Settings()
    day = DAY_MS
    old = (clock[0] - (settings.crash_minidump_retention_days + 1) * day) / 1000
    os.utime(path, (old, old))
    assert store.prune() == 1 and not path.exists(), "the minidump is gone after its retention"
    assert store.records(), "the record stays for its own retention"
    clock[0] += (settings.crash_record_retention_days + 1) * day
    store.prune()
    assert store.records() == []


# --- OBS-17 -------------------------------------------------------------------------------------------------------


def _record(store: CrashStore) -> dict[str, Any]:
    frame = {"file": "agent_core/engine/turn.py", "line": 10, "function": "run"}
    record = store.record("core", "exception", [frame], error_type="RuntimeError",
                          correlation={"session_id": "ses_TEST", "turn_id": "trn_TEST"},
                          log_tail=['{"event": "turn.start"}'],
                          detail={"exit_code": None, "student": STUDENT})  # fmt: skip
    record["minidump"] = "minidumps/x.dmp.enc"
    return record


def obs17_no_upload_when_off(tmp_path: Path) -> None:
    """With `crash_reports` off no report is queued and no request is ever made, even online with other features on;
    turning it off again deletes what was queued."""

    async def scenario() -> None:
        store = _store(tmp_path)
        report = crash_reports.build_report(_record(store), "low")
        async with FakeServices(tmp_path) as fake:
            online = layer(tmp_path, fake)
            try:
                enable(online, "update_checks", "telemetry")
                online.connectivity.features_changed()
                assert await online.connectivity.check() == "online"
                with pytest.raises(crash_reports.CrashReportRefused):
                    crash_reports.approve(online, report, [STUDENT], 20, 10**15)
                await online.drain_once(force=True)
                assert not [r for r in fake.requests if r.host == HOSTS["crash"]], "no crash request when off"
                assert egress_store.counts(online.device).get("crash_reports", 0) == 0

                enable(online, "crash_reports")
                crash_reports.approve(online, report, [STUDENT], 20, 10**15)
                enable(online, "crash_reports", on=False)
                await online.switched({"crash_reports": False})
                assert egress_store.counts(online.device).get("crash_reports", 0) == 0, "queued reports deleted"
                await online.drain_once(force=True)
                assert not [r for r in fake.requests if r.host == HOSTS["crash"]]
            finally:
                await online.stop()

    asyncio.run(scenario())


def obs17_upload_content_allow_list(tmp_path: Path) -> None:
    """An uploaded report holds only the allowed fields (no correlation ids, no minidump, no unlisted detail) and
    passes the redaction scanner; a report with a contact detail or the student's name is refused. What is sent is
    exactly what the adult was shown."""

    async def scenario() -> None:
        store = _store(tmp_path)
        report = crash_reports.build_report(_record(store), "low")
        assert set(report) <= set(crash_reports.ALLOWED)
        assert "correlation" not in report and "minidump" not in report and "student" not in report["detail"]
        assert crash_reports.report_problems(report, [STUDENT]) == []
        leaky = dict(report, log_tail=["reach me at someone@example.com"])
        assert crash_reports.report_problems(leaky, [STUDENT])
        named = dict(report, log_tail=[f"hello {STUDENT}"])
        assert crash_reports.report_problems(named, [STUDENT])
        assert crash_reports.report_problems(dict(report, correlation={"turn_id": "x"}), [])

        async with FakeServices(tmp_path) as fake:
            online = layer(tmp_path, fake)
            try:
                enable(online, "crash_reports")
                online.connectivity.features_changed()
                assert await online.connectivity.check() == "online"
                with pytest.raises(crash_reports.CrashReportRefused):
                    crash_reports.approve(online, leaky, [STUDENT], 20, 10**15)
                crash_reports.approve(online, report, [STUDENT], 20, 10**15)
                await online.drain_once(force=True)
                sent = [r for r in fake.requests if r.host == HOSTS["crash"] and r.path.startswith("/v1/outbox/")]
                assert len(sent) == 1
                assert json.loads(sent[0].body) == report, "exactly the report the adult saw"
            finally:
                await online.stop()

    asyncio.run(scenario())


def test_crash_report_upload_matches_the_outbox_contract(tmp_path: Path) -> None:
    """A built report is an outbox `CrashReport` (D39); one the contract refuses (a hardware class it does not list)
    is not queued, even with only allowed fields and nothing the redaction scanner flags."""
    from agent_core.contracts import errors as contract_errors

    async def scenario() -> None:
        store = _store(tmp_path)
        report = crash_reports.build_report(_record(store), "low")
        assert contract_errors(crash_reports.CONTRACT, report) == []
        odd = dict(report, hardware_class="workstation")
        assert crash_reports.report_problems(odd, [STUDENT]) == []
        async with FakeServices(tmp_path) as fake:
            online = layer(tmp_path, fake)
            try:
                enable(online, "crash_reports")
                with pytest.raises(crash_reports.CrashReportRefused) as refused:
                    crash_reports.approve(online, odd, [STUDENT], 20, 10**15)
                assert refused.value.code == "invalid_report"
                assert egress_store.counts(online.device).get("crash_reports", 0) == 0
            finally:
                await online.stop()

    asyncio.run(scenario())


# --- OBS-18 -------------------------------------------------------------------------------------------------------


def _inputs(tmp_path: Path) -> BundleInputs:
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    now = 1_800_000_000_000
    lines = [{"ts": now - 10 * DAY_MS, "event": "old"}, {"ts": now - DAY_MS, "event": "turn.start", "text": QUESTION,
             "authorization": "Bearer seeded-token-abcdef123456"}]  # fmt: skip
    (logs / "core.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    store = _store(tmp_path)
    crash = store.record("core", "exception", [{"file": "x.py", "line": 1, "function": "f"}])
    crash["minidump"] = "minidumps/secret.dmp.enc"
    reports = [
        {"report_id": "01JREPORT00000000000000001", "session_id": "ses_1", "created_at": now - DAY_MS,
         "content": json.dumps({"category": "wrong_answer", "turn_id": "trn_1", "note": NOTE_PRIVATE,
                                "allow_support_export": False})},
        {"report_id": "01JREPORT00000000000000002", "session_id": "ses_2", "created_at": now - 2 * DAY_MS,
         "content": json.dumps({"category": "confusing", "turn_id": "trn_2", "note": NOTE_SHARED,
                                "allow_support_export": True})},
    ]  # fmt: skip
    return BundleInputs(
        summary={"app": "1.0.0", "build": "dev", "hardware_class": "low"},
        config={"online_downloads": True, "export_support_public_key": "", "launch_token": "seeded-launch-secret",
                "nested": {"api_key": "sk-fakeseededsecretvalue123"}},
        health={"core": "ok"}, log_dir=logs,
        traces=[{"turn_id": f"trn_{i}", "duration_ms": i} for i in range(80)],
        crash_records=[crash], ledger=[{"feature": "downloads", "bytes": 10}], packs=["pack.phy.o"],
        models=["mp.synth.8b.q4_k_m.low"], problem_reports=reports, now_ms=now,
        conversations=lambda session: [{"role": "student", "text": QUESTION, "name": STUDENT}],
    )  # fmt: skip


def obs18_default_bundle_clean(tmp_path: Path) -> None:
    """A default bundle contains no student text, names or secrets, never a minidump, and its manifest hashes verify;
    the preview lists every file before saving."""
    files = bundle_files(_inputs(tmp_path), Settings())
    everything = b"".join(files.values())
    for seeded in (QUESTION, STUDENT, NOTE_PRIVATE, "seeded-launch-secret", "sk-fakeseededsecretvalue123",
                   "seeded-token-abcdef123456"):  # fmt: skip
        assert seeded.encode() not in everything, seeded
    assert CONVERSATION not in files and not any(name.endswith(".dmp.enc") for name in files)
    assert len(json.loads(files["traces.json"])) == Settings().debug_bundle_trace_turns
    assert b'"old"' not in files["logs/core.jsonl"], "only the last days of logs"
    manifest = json.loads(files["manifest.json"])["files"]
    assert set(manifest) == set(files) - {"manifest.json"}
    for name, digest in manifest.items():
        assert hashlib.sha256(files[name]).hexdigest() == digest
    assert {row["name"] for row in preview(files)} == set(files)
    saved = save_bundle(files, tmp_path, FAST)
    with zipfile.ZipFile(saved) as archive:
        assert set(archive.namelist()) == set(files)


def obs18_problem_reports_included(tmp_path: Path) -> None:
    """Every saved problem report is listed by category, date and turn reference; a note only where the stored
    `allow_support_export` is true."""
    listed = json.loads(bundle_files(_inputs(tmp_path), Settings())["problem_reports.json"])
    assert [r["category"] for r in listed] == ["wrong_answer", "confusing"]
    assert [r["turn_id"] for r in listed] == ["trn_1", "trn_2"]
    assert all(len(r["date"]) == 10 for r in listed)
    assert "note" not in listed[0] and listed[1]["note"] == NOTE_SHARED


def obs18_conversation_requires_encryption(tmp_path: Path) -> None:
    """With the conversation included the bundle must be sealed with the adult's passphrase; without one it is not
    saved, and the sealed file opens only with that passphrase."""
    shares = SupportShares(tmp_path / "profile")
    shares.confirm("ses_1", acting_profile="prf_student", owner_profile="prf_student")
    files = bundle_files(_inputs(tmp_path), Settings(), conversation_session="ses_1", shares=shares)
    assert CONVERSATION in files
    with pytest.raises(BundleRefused) as refused:
        save_bundle(files, tmp_path, FAST, passphrase=None, shares=shares)
    assert refused.value.code == "passphrase_required"
    assert not list(tmp_path.glob("jana-support-report-*"))
    saved = save_bundle(files, tmp_path, FAST, passphrase=PASSPHRASE, shares=shares)
    assert QUESTION.encode() not in saved.read_bytes()
    opened = open_with_passphrase(saved.read_bytes(), PASSPHRASE)
    with zipfile.ZipFile(io.BytesIO(opened)) as archive:
        assert QUESTION in archive.read(CONVERSATION).decode()
    assert shares.included_notices() == ["ses_1"], "the student is told the session was included"


def obs18_conversation_needs_student_action(tmp_path: Path) -> None:
    """Without the student's own per-session confirmation the conversation cannot be included; an adult (any request
    not made with the student's profile token) cannot confirm for them, and a confirmation covers only its session."""
    shares = SupportShares(tmp_path / "profile")
    with pytest.raises(BundleRefused) as refused:
        bundle_files(_inputs(tmp_path), Settings(), conversation_session="ses_1", shares=shares)
    assert refused.value.code == "student_confirmation_required"
    for acting in (None, "prf_adult_or_other"):
        with pytest.raises(BundleRefused):
            shares.confirm("ses_1", acting_profile=acting, owner_profile="prf_student")
    assert not shares.confirmed("ses_1")
    shares.confirm("ses_2", acting_profile="prf_student", owner_profile="prf_student")
    with pytest.raises(BundleRefused):
        bundle_files(_inputs(tmp_path), Settings(), conversation_session="ses_1", shares=shares)
    assert CONVERSATION in bundle_files(_inputs(tmp_path), Settings(), conversation_session="ses_2", shares=shares)
