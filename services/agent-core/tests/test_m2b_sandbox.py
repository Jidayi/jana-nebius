"""M2.b: the worker sandbox, import allow-list and resource limits (SEC-06 to SEC-09; TOL-26 sandbox test)."""

import asyncio
import sys
import time
from pathlib import Path

from agent_core.config import Settings
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory, worker_argv
from jana_tools import REPO_ROOT
from jana_tools.codecheck import file_errors, tree_errors

HARNESS = REPO_ROOT / "services" / "tool-worker" / "tests" / "harness.py"
CHECK = "chk_01JZ0000000000000000000001"
WORKER = REPO_ROOT / "services" / "tool-worker" / "tool_worker"
AGENT_CORE = REPO_ROOT / "services" / "agent-core" / "agent_core"


def _settings(**overrides) -> Settings:
    return Settings(**{"worker_pool_size": 1, "worker_respawn_backoff_s": (0.0,), "worker_warm_target_s": 10.0,
                       **overrides})  # fmt: skip


async def _supervisor(argv: list[str], scratch_root: Path) -> WorkerSupervisor:
    # These tests trigger many recycles on purpose; the circuit itself is tested by tol26_circuit_opens.
    settings = _settings(worker_circuit_restarts=100)
    supervisor = WorkerSupervisor(process_factory(settings, argv, scratch_root), settings)
    await supervisor.start()
    return supervisor


OUTSIDE = REPO_ROOT / ".sandbox-escape-test"


def _escape_args(tmp_path: Path, home_file: Path) -> dict:
    learner_db = tmp_path / "learner.db"
    learner_db.write_bytes(b"SQLite format 3\x00")
    return {"home_file": str(home_file), "outside": str(OUTSIDE), "learner_db": str(learner_db)}


def sec06_sandbox_escape_suite(tmp_path: Path):
    assert sys.platform in ("darwin", "win32") or sys.platform.startswith("linux"), "an OS sandbox exists here"

    home_file = Path.home() / ".jana-sandbox-sentinel"
    home_file.write_text("private")

    async def scenario() -> None:
        for extra in (["--no-guard"], []):  # the OS sandbox alone, then with the in-process controls
            supervisor = await _supervisor([sys.executable, str(HARNESS), *extra], tmp_path / "scratch")
            assert not supervisor.reduced_protection
            outcome = await supervisor.call("escape", 1, _escape_args(tmp_path, home_file), CHECK, 10000)
            assert outcome.ok, outcome
            report = outcome.result["value"]
            assert report.pop("write_scratch") == "ALLOWED"
            assert {k: v.startswith("denied") for k, v in report.items()} == dict.fromkeys(report, True), report
            await supervisor.close()
        assert not OUTSIDE.exists()
        assert not list((tmp_path / "scratch").iterdir()), "scratch directories are deleted at exit"

    try:
        asyncio.run(scenario())
    finally:
        home_file.unlink(missing_ok=True)
        OUTSIDE.unlink(missing_ok=True)


def tol26_sandbox_denies_io(tmp_path: Path):
    async def scenario() -> None:
        supervisor = await _supervisor([sys.executable, str(HARNESS)], tmp_path / "scratch")
        socket_call = await supervisor.call("importer", 1, {"module": "socket"}, CHECK, 10000)
        assert socket_call.error == "policy_denied" and socket_call.action_taken is False
        home_call = await supervisor.call("readfile", 1, {"path": str(Path.home() / ".profile")}, CHECK, 10000)
        assert home_call.error == "policy_denied", home_call
        assert len(supervisor.restarts) == 2, "each refused attempt recycles the worker"
        assert (await supervisor.call("math_parse", 1, {"text": "x+1"}, CHECK, 10000)).ok
        await supervisor.close()

    asyncio.run(scenario())


def sec07_no_dynamic_evaluation(tmp_path: Path):
    assert tree_errors([WORKER]) == []
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "import sympy as sp\nfrom sympy.parsing.sympy_parser import parse_expr\n"
        "def f(text):\n    eval(text)\n    exec(text)\n    compile(text, 'x', 'eval')\n"
        "    sp.sympify(text)\n    sp.S(text)\n    parse_expr(text)\n    sp.lambdify(['x'], text)\n"
        "    return sp.sympify(2)\n"
    )
    assert [e.split(": ", 1)[1] for e in file_errors(seeded)] == [
        "imports parse_expr",
        "calls eval",
        "calls exec",
        "calls compile",
        "calls sympify on something that may be a string",
        "calls S on something that may be a string",
        "calls parse_expr",
        "calls lambdify",
    ]


def sec07_import_allow_list_enforced(tmp_path: Path):
    async def scenario() -> None:
        supervisor = await _supervisor([sys.executable, str(HARNESS)], tmp_path / "scratch")
        for module in (
            "subprocess",
            "socket",
            "ctypes",
            "pickle",
            "http.client",
            "multiprocessing",
            "sqlite3",
            "tkinter",
        ):
            outcome = await supervisor.call("importer", 1, {"module": module}, CHECK, 10000)
            assert outcome.error == "policy_denied", (module, outcome)
        for module in ("fractions", "sympy.matrices"):
            assert (await supervisor.call("importer", 1, {"module": module}, CHECK, 10000)).ok, module
        # Sockets, processes and native libraries stay unusable through references taken before the guard
        # installed (after SymPy and Pint loaded): refused as policy_denied, and the worker is recycled.
        for action in ("socket", "process", "native"):
            before = {w.process.pid for w in supervisor._all if w.process}
            outcome = await supervisor.call("operate", 1, {"action": action}, CHECK, 10000)
            assert outcome.error == "policy_denied" and outcome.action_taken is False, (action, outcome)
            after = {w.process.pid for w in supervisor._all if w.process}
            assert before and after and not (before & after), (action, "the worker was not recycled")
        await supervisor.close()

    asyncio.run(scenario())


NETWORK_MODULES = ("urllib.request", "urllib3", "http.client", "httpx", "requests", "aiohttp", "websockets", "socket")
BINDINGS_RUNTIME = ("pydantic", "pydantic_core", "annotated_types", "typing_extensions", "typing_inspection",
                    "jsonschema", "jsonschema_specifications", "referencing", "rpds", "attrs", "attr")  # fmt: skip


def _module_level_network_imports(package: str) -> list[str]:
    """Network-client imports at the top level of a package's modules (never inside a function)."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None, package
    root = Path(spec.origin).parent if spec.submodule_search_locations else Path(spec.origin)
    files = [root] if root.suffix == ".py" else [f for f in root.rglob("*.py") if "tests" not in f.parts]
    found = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"))
        for node in tree.body:
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])  # fmt: skip
            for name in names:
                if any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES):
                    found.append(f"{file.name}: {name}")
    return found


def sec07_bindings_runtime_allowed(tmp_path: Path):
    # The inventory: no package of the bindings' runtime imports a network client when it loads.
    assert {package: _module_level_network_imports(package) for package in BINDINGS_RUNTIME} == {
        package: [] for package in BINDINGS_RUNTIME}  # fmt: skip

    async def scenario() -> None:
        supervisor = await _supervisor([sys.executable, str(HARNESS)], tmp_path / "scratch")
        # The generated bindings and their runtime load under the allow-list...
        for module in ("tool_worker.contracts", "tool_worker.contracts.tools.worker_protocol", *BINDINGS_RUNTIME):
            outcome = await supervisor.call("importer", 1, {"module": module}, CHECK, 10000)
            assert outcome.ok, (module, outcome)
        # ...and the one network path in that runtime (a lazy import in a deprecated resolver) is refused if reached.
        fetch = await supervisor.call("operate", 1, {"action": "fetch"}, CHECK, 10000)
        assert fetch.error == "policy_denied", fetch
        await supervisor.close()

    asyncio.run(scenario())


PATHOLOGICAL = [
    "2^(10^10)", "9^9^9^9", "(" * 80 + "x" + ")" * 80, "1" * 31, "x" * 2001, "x!!!!", "sin(" * 70 + "x" + ")" * 70,
    "10^300^2", "e^(e^(e^(e^(e^100))))", "-" * 1500 + "1", "\\frac{" * 70 + "1}{2}" * 70, "|" * 300,
]  # fmt: skip


def sec08_pathological_inputs_bounded(tmp_path: Path):
    async def scenario() -> None:
        supervisor = await _supervisor(worker_argv(_settings()), tmp_path / "scratch")
        for text in PATHOLOGICAL:
            began = time.monotonic()
            outcome = await supervisor.call("math_parse", 1, {"text": text}, CHECK, 2000)
            elapsed = time.monotonic() - began
            assert elapsed < 2.5, (text[:30], elapsed)
            if not outcome.ok:
                assert outcome.error in ("limit_exceeded", "invalid_args", "timeout"), (text[:30], outcome.error)
            nxt = await supervisor.call("math_parse", 1, {"text": "x+1"}, CHECK, 5000)
            assert nxt.ok, (text[:30], nxt)
        await supervisor.close()

    asyncio.run(scenario())


def sec09_no_runtime_code_execution():
    errors = tree_errors([WORKER, AGENT_CORE])
    assert errors == []


def sec09_no_python_run_on_device():
    from tool_worker.functions import FUNCTIONS
    from tool_worker.server import Server

    assert "python_run" not in FUNCTIONS
    assert not [name for name in dir(Server) if name.startswith("exec")]
    from agent_core.tools.generated.register import REGISTER
    from agent_core.tools.registry import register_entries

    for stage in ("S1", "S2", "S3", "S4", "S5"):
        assert "python_run" not in register_entries(REGISTER, stage, device=True), stage
    assert "python_run" in register_entries(REGISTER, "S3", device=False), "the cloud build keeps it"


def arc21_worker_cannot_open_learner_db(tmp_path: Path):
    """ARC-21: the learner database is outside the worker's sandbox, and the worker is given no path or key to it."""
    import sqlite3

    from agent_core.store.local import open_local

    data_dir = tmp_path / "app-data"  # the app data directory the shell passes in control.config (data_dir)
    stores = open_local(data_dir, app_version="0.0.0", now_ms=1_760_000_000_000)
    learner_db, profile_id = stores.learner_path, stores.profile_id
    stores.close()
    assert learner_db == data_dir / "profiles" / profile_id / "learner.db"
    with sqlite3.connect(f"file:{learner_db}?mode=ro", uri=True) as db:  # the core itself can open it
        assert db.execute("SELECT profile_id FROM meta").fetchone() == (profile_id,)
    probe = {"learner_db": str(learner_db), "profiles": str(learner_db.parent.parent)}
    scratch_root = data_dir / "scratch"  # where start_worker_pool puts worker scratch: beside profiles/

    async def scenario() -> None:
        for extra in (["--no-guard"], []):  # the OS sandbox alone, then with the in-process controls
            supervisor = await _supervisor([sys.executable, str(HARNESS), *extra], scratch_root)
            assert not supervisor.reduced_protection
            worker = supervisor._all[0]
            # Nothing the worker is started with names the learner store or carries a key.
            launch = " ".join([*worker.argv, *(worker.env or {}).values()])
            assert str(learner_db.parent.parent) not in launch and profile_id not in launch
            assert set(worker.env or {}) == {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONDONTWRITEBYTECODE"}
            outcome = await supervisor.call("learner_probe", 1, probe, CHECK, 10000)
            assert outcome.ok, outcome
            report = outcome.result["value"] if outcome.result else {}
            assert report.pop("control") == "ALLOWED ('ok')", "the probe can open files inside its scratch"
            assert set(report) == {"read_bytes", "open_database", "list_profiles"}
            assert all(v.startswith("denied") for v in report.values()), (extra, report)
            read = await supervisor.call("readfile", 1, {"path": str(learner_db)}, CHECK, 10000)
            assert not read.ok and profile_id not in str(read), read
            if not extra or sys.platform == "darwin":  # Seatbelt and the audit hook refuse; bubblewrap hides it
                assert read.error == "policy_denied", read
            await supervisor.close()

    asyncio.run(scenario())
