"""G16, SEC-06 (TABLE SEC-06a Windows row), SEC-08: the Windows sandbox for the tool and perception workers.

The first part runs on every platform: the policy the core builds, the mapping of the configured limits onto the job
object, the structure layouts handed to Windows, the launcher's command line and environment, and the core's choice
between the sandbox and reduced protection. The second part needs Windows (an AppContainer and a job object) and is
skipped elsewhere with that reason; the windows-2025 CI runner runs it, together with `sec06_sandbox_escape_suite`
(test_m2b_sandbox.py), which uses the real worker under the real sandbox on every desktop OS."""

from __future__ import annotations

import asyncio
import ctypes
import importlib.util
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.tools.worker import WorkerSupervisor, sandbox, winsandbox
from agent_core.tools.worker.launch import process_factory
from jana_tools import REPO_ROOT

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="needs Windows: AppContainer and job-object calls (G16); runs on the windows-2025 CI runner",
)
HARNESS = REPO_ROOT / "services" / "tool-worker" / "tests" / "harness.py"
CHECK = "chk_01JZ0000000000000000000001"


# --- everywhere -----------------------------------------------------------------------------------------------------


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="the layouts checked are the 64-bit Windows ones")
def test_sec06_windows_structure_layouts():
    """The structures match the 64-bit Windows SDK layouts (sizes and the offsets Windows reads)."""
    w = winsandbox
    sizes = {
        w.JOBOBJECT_BASIC_LIMIT_INFORMATION: 64,
        w.IO_COUNTERS: 48,
        w.JOBOBJECT_EXTENDED_LIMIT_INFORMATION: 144,
        w.JOBOBJECT_CPU_RATE_CONTROL_INFORMATION: 8,
        w.JOBOBJECT_BASIC_UI_RESTRICTIONS: 4,
        w.SECURITY_CAPABILITIES: 24,
        w.STARTUPINFOW: 104,
        w.STARTUPINFOEXW: 112,
        w.PROCESS_INFORMATION: 24,
        w.TRUSTEE_W: 32,
        w.EXPLICIT_ACCESS_W: 48,
        w.ACL: 8,
        w.ACE_HEADER: 4,
        w.ACCESS_ALLOWED_ACE: 12,
    }
    assert {t.__name__: ctypes.sizeof(t) for t in sizes} == {t.__name__: n for t, n in sizes.items()}
    basic = w.JOBOBJECT_BASIC_LIMIT_INFORMATION
    assert (basic.LimitFlags.offset, basic.ActiveProcessLimit.offset, basic.PriorityClass.offset) == (16, 40, 56)
    extended = w.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    assert (extended.ProcessMemoryLimit.offset, extended.JobMemoryLimit.offset) == (112, 120)
    assert (w.STARTUPINFOW.dwFlags.offset, w.STARTUPINFOW.hStdInput.offset, w.STARTUPINFOW.hStdError.offset) == (
        60, 80, 96)  # fmt: skip
    assert w.EXPLICIT_ACCESS_W.Trustee.offset == 16 and w.TRUSTEE_W.ptstrName.offset == 24


def test_sec06_windows_limits_from_configuration():
    """The job object carries kill-on-close, one active process, the SEC-08 memory limit and a hard CPU cap, all from
    configuration keys; the perception worker gets its own memory and a per-page CPU time."""
    settings = Settings(worker_process_memory_mb=384, worker_cpu_rate_percent=40, perception_memory_mb=1024,
                        perception_page_s=12.5)  # fmt: skip
    tool = sandbox.tool_job_limits(settings)
    info = winsandbox.extended_limits(tool)
    flags = info.BasicLimitInformation.LimitFlags
    for flag in (winsandbox.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, winsandbox.JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
                 winsandbox.JOB_OBJECT_LIMIT_PROCESS_MEMORY, winsandbox.JOB_OBJECT_LIMIT_JOB_MEMORY,
                 winsandbox.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION):  # fmt: skip
        assert flags & flag
    assert not flags & winsandbox.JOB_OBJECT_LIMIT_PROCESS_TIME, "the tool worker is long-lived"
    assert info.BasicLimitInformation.ActiveProcessLimit == 1
    assert info.ProcessMemoryLimit == info.JobMemoryLimit == 384 * 1024 * 1024
    control, rate = winsandbox.cpu_rate_control(tool)
    assert control == winsandbox.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | winsandbox.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    assert rate == 4000  # hundredths of a percent of the machine
    perception = winsandbox.extended_limits(sandbox.perception_job_limits(settings))
    assert perception.BasicLimitInformation.LimitFlags & winsandbox.JOB_OBJECT_LIMIT_PROCESS_TIME
    assert perception.BasicLimitInformation.PerProcessUserTimeLimit == 125_000_000  # 12.5 s in 100 ns units
    assert perception.JobMemoryLimit == 1024 * 1024 * 1024
    defaults = Settings()
    assert sandbox.tool_job_limits(defaults).memory_bytes == defaults.worker_process_memory_mb * 1024 * 1024
    with pytest.raises(ValueError):
        winsandbox.JobLimits(memory_bytes=1, cpu_rate_percent=0)


def test_sec06_windows_access_entries():
    """Grants name the AppContainer's SID, allow (never deny-by-replace) and are inherited by everything below."""
    read = winsandbox.explicit_access(0x1234, winsandbox.FILE_GENERIC_READ_EXECUTE)
    assert (read.grfAccessMode, read.grfInheritance) == (winsandbox.GRANT_ACCESS,
                                                         winsandbox.SUB_CONTAINERS_AND_OBJECTS_INHERIT)  # fmt: skip
    assert (read.Trustee.TrusteeForm, read.Trustee.ptstrName) == (winsandbox.TRUSTEE_IS_SID, 0x1234)
    assert read.grfAccessPermissions & 0x2 == 0, "the bundle is never writable (FILE_WRITE_DATA)"
    assert winsandbox.FILE_ALL_ACCESS & 0x2


def test_sec06_windows_launcher_command(tmp_path: Path):
    policy = sandbox.windows_policy([tmp_path / "runtime"], tmp_path / "scratch", winsandbox.JobLimits(1 << 28, 50),
                                    sandbox.TOOL_PROFILE)  # fmt: skip
    worker = ["C:\\Jana\\python.exe", "-m", "tool_worker", "--limits", '{"a": 1}']
    dev = winsandbox.launcher_argv(policy, worker, python="C:\\Jana\\python.exe", frozen=False)
    assert dev[:3] == ["C:\\Jana\\python.exe", "-m", winsandbox.LAUNCHER_MODULE] and dev[-5:] == worker
    frozen = winsandbox.launcher_argv(policy, worker, python="C:\\Jana\\agent-core.exe", frozen=True)
    assert frozen[:2] == ["C:\\Jana\\agent-core.exe", winsandbox.FROZEN_FLAG]
    for argv in (dev[3:], frozen[1:]):
        decoded, command = winsandbox.parse_launcher_args(argv)
        assert decoded == policy and command == worker
    with pytest.raises(ValueError):
        winsandbox.parse_launcher_args(["--", *worker])
    assert winsandbox.main(["--nonsense"]) == 125, "a bad launch reports on stderr, never on the protocol stream"


def test_sec06_windows_virtual_environment_redirect():
    """A venv's python.exe starts the base interpreter as a child, which the one-process job refuses: the base
    interpreter runs directly and is told which environment it serves."""
    venv, base = "C:\\repo\\.venv\\Scripts\\python.exe", "C:\\py\\python.exe"
    argv = [venv, "-m", "tool_worker"]
    assert winsandbox.child_command(argv, venv, base) == ([base, "-m", "tool_worker"], {"__PYVENV_LAUNCHER__": venv})
    assert winsandbox.child_command(argv, venv, venv) == (argv, {})
    bundled = ["C:\\Jana\\tool-worker\\tool-worker.exe", "--limits", "{}"]
    assert winsandbox.child_command(bundled, venv, base) == (bundled, {})


def test_sec06_windows_environment():
    """The worker's environment is built, not inherited: scratch as home and temp, and the system root only."""
    host = {"SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows", "APPDATA": "C:\\Users\\a\\AppData\\Roaming",
            "USERNAME": "someone", "PATH": "C:\\anything"}  # fmt: skip
    env = winsandbox.worker_environment("C:\\scratch\\w1", host)
    assert env["SYSTEMROOT"] == "C:\\Windows" and env["TEMP"] == env["USERPROFILE"] == "C:\\scratch\\w1"
    assert not {"APPDATA", "USERNAME", "PATH"} & set(env)
    block = winsandbox.environment_block({"b": "2", "A": "1", "c": "3"})
    assert block == "A=1\0b=2\0c=3\0\0"
    with pytest.raises(ValueError):
        winsandbox.environment_block({"A=B": "1"})
    assert winsandbox.command_line(["C:\\Program Files\\x.exe", 'a "b"']) == '"C:\\Program Files\\x.exe" "a \\"b\\""'


def test_sec06_windows_core_chooses_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """On Windows the core wraps the worker in the launcher once the AppContainer is prepared; the tool and
    perception workers get separate containers, and only perception may read its model files."""
    prepared: list[winsandbox.WindowsPolicy] = []
    monkeypatch.setattr(winsandbox, "prepare", prepared.append)
    argv = [sys.executable, "-m", "tool_worker"]
    wrapped = sandbox.sandboxed(argv, tmp_path / "w1", platform="win32", limits=sandbox.tool_job_limits(Settings()))
    assert (wrapped.mechanism, wrapped.reduced_protection, wrapped.pass_fds) == ("appcontainer", False, ())
    policy, command = winsandbox.parse_launcher_args(wrapped.argv[wrapped.argv.index("--policy") :])
    assert command == argv and prepared == [policy]
    assert policy.profile == sandbox.TOOL_PROFILE and policy.write_paths == (str((tmp_path / "w1").resolve()),)
    spec = importlib.util.find_spec("tool_worker")
    assert spec is not None and spec.origin is not None
    worker_code = Path(spec.origin).resolve().parent.parent
    assert any(worker_code.is_relative_to(p) for p in map(Path, policy.read_paths))
    assert not any(Path.home() == Path(p) for p in policy.read_paths), "never the whole home directory"
    models = tmp_path / "models"
    perception = sandbox.sandboxed(["C:\\pp\\perception.exe"], tmp_path / "p1", platform="win32", reads=[models],
                                   limits=sandbox.perception_job_limits(Settings()),
                                   profile=sandbox.PERCEPTION_PROFILE, env={"OMP_THREAD_LIMIT": "1"})  # fmt: skip
    p_policy, _ = winsandbox.parse_launcher_args(perception.argv[perception.argv.index("--policy") :])
    assert p_policy.profile != policy.profile and p_policy.read_paths == (str(models),)
    assert p_policy.env["OMP_THREAD_LIMIT"] == "1" and p_policy.limits.user_time_ms is not None


def test_sec06_windows_reduced_protection_when_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When the AppContainer cannot be prepared the worker still starts, reporting reduced protection and why."""

    def refuse(policy: winsandbox.WindowsPolicy) -> None:
        raise winsandbox.SandboxUnavailable("CreateAppContainerProfile failed")

    monkeypatch.setattr(winsandbox, "prepare", refuse)
    wrapped = sandbox.sandboxed([sys.executable, "-m", "tool_worker"], tmp_path / "w", platform="win32")
    assert wrapped.reduced_protection and wrapped.mechanism == "none"
    assert "CreateAppContainerProfile" in wrapped.reason and wrapped.argv[0] == sys.executable
    monkeypatch.undo()
    if sys.platform != "win32":  # the real preparation refuses off Windows instead of half-applying
        assert sandbox.sandboxed([sys.executable], tmp_path / "x", platform="win32").reduced_protection


def test_sec06_windows_host_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
    env = sandbox.host_environment(tmp_path, platform="win32")
    assert env["SYSTEMROOT"] == "C:\\Windows" and env["PATH"].endswith("System32") and env["TEMP"] == str(tmp_path)
    assert sandbox.host_environment(tmp_path, platform="linux")["PATH"] == "/usr/bin:/bin"


# --- on Windows -----------------------------------------------------------------------------------------------------


def _run_sandboxed(tmp_path: Path, code: str, *, memory_mb: int = 256, timeout: float = 60) -> int:
    """Run `python -c code` in the tool worker's AppContainer and job, as the launcher does; return its exit code."""
    scratch = tmp_path / f"scratch-{time.monotonic_ns()}"
    argv = [sys.executable, "-c", code]
    wrapped = sandbox.sandboxed(argv, scratch, limits=winsandbox.JobLimits(memory_mb * 1024 * 1024, 50))
    assert wrapped.mechanism == "appcontainer", wrapped.reason
    return subprocess.run(wrapped.argv, env=sandbox.host_environment(scratch), cwd=scratch, timeout=timeout,
                          capture_output=True).returncode  # fmt: skip


@WINDOWS_ONLY
def test_sec06_windows_worker_runs_sandboxed(tmp_path: Path):
    """The real tool worker starts in its AppContainer, is not reported as reduced protection, and answers."""
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=30.0)

    async def scenario() -> None:
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path / "scratch"), settings)
        await supervisor.start()
        try:
            assert supervisor.compute_available() and not supervisor.reduced_protection
            assert all(w.sandbox_mechanism == "appcontainer" for w in supervisor._all)
            outcome = await supervisor.call("math_parse", 1, {"text": "x+1"}, CHECK, 20000)
            assert outcome.ok, outcome
        finally:
            await supervisor.close()

    asyncio.run(scenario())


@WINDOWS_ONLY
def test_sec06_windows_denials(tmp_path: Path):
    """Each exit code says the attempt was refused (3) rather than allowed (0): no loopback socket, no home read,
    no write outside scratch, no child process; a write to scratch works."""
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    secret = Path.home() / ".jana-g16-sentinel"
    secret.write_text("private")
    outside = tmp_path / "outside.txt"
    attempt = "import sys\ntry:\n    {action}\nexcept BaseException:\n    sys.exit(3)\nsys.exit(0)\n"
    try:
        actions = {
            "loopback": f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=2)",
            "home": f"open({str(secret)!r}).read()",
            "outside": f"open({str(outside)!r}, 'w').write('x')",
            "child": "import subprocess; subprocess.run([sys.executable, '-c', 'pass'], check=True)",
        }
        results = {name: _run_sandboxed(tmp_path, attempt.format(action=a)) for name, a in actions.items()}
        assert results == dict.fromkeys(actions, 3), results
        assert not outside.exists()
        assert _run_sandboxed(tmp_path, attempt.format(action="open('ok.txt', 'w').write('x')")) == 0
    finally:
        listener.close()
        secret.unlink(missing_ok=True)


@WINDOWS_ONLY
def test_sec06_windows_memory_limit(tmp_path: Path):
    """An allocation over the job's memory limit fails inside the worker (SEC-08)."""
    assert _run_sandboxed(tmp_path, "b = bytearray(512 * 1024 * 1024)", memory_mb=128) != 0
    assert _run_sandboxed(tmp_path, "b = bytearray(16 * 1024 * 1024)", memory_mb=128) == 0


@WINDOWS_ONLY
def test_sec06_windows_kill_on_close(tmp_path: Path):
    """Killing the launcher (as the supervisor does) ends the worker: the job is closed with kill-on-close."""
    scratch = tmp_path / "scratch"
    code = "import os, time; open('pid', 'w').write(str(os.getpid())); time.sleep(120)"
    wrapped = sandbox.sandboxed([sys.executable, "-c", code], scratch)
    launcher = subprocess.Popen(
        wrapped.argv,
        env=sandbox.host_environment(scratch),
        cwd=scratch,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file = scratch / "pid"
    deadline = time.monotonic() + 30
    while not pid_file.exists() or not pid_file.read_text():
        assert time.monotonic() < deadline, "the sandboxed child never started"
        time.sleep(0.1)
    pid = int(pid_file.read_text())
    launcher.kill()
    launcher.wait(10)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:  # still openable for a moment: it must end promptly
        try:
            assert kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 10_000) == 0
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
