"""Platform hardening from the launch-readiness review (wave A2): the loopback client takes literal addresses only
(MDL-01, ARC-18), the Seatbelt profile scopes metadata reads (SEC-06), the Linux tool worker fails closed without its
sandbox and has a Landlock fallback (TABLE SEC-06a), the speech sidecar loads its VAD weights without torch.hub
(SEC-09), and speech and perception packs never roll back (SEC-15, SEC-16)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.net.loopback import LoopbackClient, is_loopback
from agent_core.net.voice import LocalVoiceEndpoint, VoiceTransportError
from agent_core.net.voice_sidecar import allow_connection
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from agent_core.tools.worker.sandbox import metadata_literals, seatbelt_profile
from jana_tools import REPO_ROOT

HARNESS = REPO_ROOT / "services" / "tool-worker" / "tests" / "harness.py"
CHECK = "chk_01JZ0000000000000000000001"
TOKEN = "t" * 43


# --- loopback: literal addresses only -----------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://[::1]:8080"])
def test_arc18_loopback_literal_addresses_accepted(url: str) -> None:
    assert is_loopback(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080",  # a name: the hosts file or a resolver decides where it goes
        "http://LOCALHOST:8080",
        "http://127.0.0.2:8080",  # loopback, but not where any Jana service binds
        "http://127.1:8080",
        "http://0x7f000001:8080",
        "http://[::ffff:127.0.0.1]:8080",
        "http://[::1%25lo0]:8080",
        "http://192.168.1.10:8080",
        "http://[::1:8080",
    ],
)
def test_arc18_loopback_names_refused(url: str) -> None:
    assert not is_loopback(url)
    with pytest.raises(ValueError):
        LoopbackClient(url, "k")


def test_voc23_voice_endpoints_literal_loopback_only() -> None:
    LocalVoiceEndpoint("ws://127.0.0.1:9000/v1/realtime", TOKEN)
    for url in ("ws://localhost:9000/v1/realtime", "ws://127.0.0.2:9000/v1/realtime"):
        with pytest.raises(VoiceTransportError):
            LocalVoiceEndpoint(url, TOKEN)
    assert allow_connection(("127.0.0.1", 80)) and allow_connection(("::1", 80, 0, 0))
    for address in (("localhost", 80), ("127.0.0.2", 80), ("203.0.113.5", 80), "/tmp/socket", ()):  # noqa: S108
        assert not allow_connection(address), address


# --- Seatbelt: metadata only on and above the allowed paths -------------------------------------------------------


def test_sec06_seatbelt_metadata_scoped(tmp_path: Path) -> None:
    reads = [tmp_path / "runtime" / "lib"]
    profile = seatbelt_profile(reads, tmp_path / "scratch", tmp_path / "runtime" / "bin" / "python")
    assert "(allow file-read-metadata)" not in profile, "metadata reads are never granted everywhere"
    lines = profile.splitlines()
    start = lines.index("(allow file-read-metadata")
    granted = [
        line.removesuffix("))") + ")" if line.endswith("))") else line
        for line in lines[start + 1 : lines.index("(allow file-read*")]
    ]
    assert all(line.startswith("  (literal ") for line in granted), granted
    assert f'  (literal "{tmp_path}")' in granted and '  (literal "/")' in granted
    assert '  (literal "/usr")' in granted and '  (literal "/var")' in granted
    assert Path.home() / "Documents" not in metadata_literals(reads)


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS's sandbox")
def test_sec06_seatbelt_denies_metadata_outside_allowed_paths(tmp_path: Path) -> None:
    home_file = Path.home() / ".jana-sandbox-metadata-sentinel"
    home_file.write_text("private")
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=10.0,
                        worker_circuit_restarts=100)  # fmt: skip

    async def scenario() -> None:
        # The OS sandbox alone (no in-process guard): its own runtime is readable, the user's files are not.
        factory = process_factory(settings, [sys.executable, str(HARNESS), "--no-guard"], tmp_path / "scratch")
        supervisor = WorkerSupervisor(factory, settings)
        await supervisor.start()
        try:
            assert not supervisor.reduced_protection
            outside = await supervisor.call("statfile", 1, {"path": str(home_file)}, CHECK, 10000)
            assert not outside.ok, outside
            inside = await supervisor.call("statfile", 1, {"path": sys.executable}, CHECK, 10000)
            assert inside.ok, inside
        finally:
            await supervisor.close()

    try:
        asyncio.run(scenario())
    finally:
        home_file.unlink(missing_ok=True)


# --- the speech sidecar runs no Python from a pack ----------------------------------------------------------------


def test_sec09_silero_loads_without_torch_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from agent_core.net import voice_sidecar
    from agent_core.store.speech_packs import SpeechPackError

    hub_calls: list[tuple] = []
    loaded: list[str] = []

    class Model:
        def eval(self) -> None:
            loaded.append("eval")

    def hub_load(*args, **kwargs):  # torch.hub's own loader: would import and run the pack's hubconf.py
        hub_calls.append(args)
        raise AssertionError("torch.hub's loader is never reached")

    def jit_load(path: str, map_location: str) -> Model:
        loaded.append(path)
        return Model()

    torch = types.SimpleNamespace(
        hub=types.SimpleNamespace(load=hub_load, load_state_dict_from_url=hub_load, download_url_to_file=hub_load),
        jit=types.SimpleNamespace(load=jit_load),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    vad = tmp_path / "vad"
    vad.mkdir()
    (vad / "hubconf.py").write_text("raise SystemExit('pack code ran')\n")  # present, and never run
    with pytest.raises(SpeechPackError, match="voice_vad_weights_missing"):
        voice_sidecar.local_silero(vad)
    (vad / voice_sidecar.SILERO_WEIGHTS).write_bytes(b"synthetic torchscript")
    voice_sidecar.local_silero(vad)
    model, utilities = torch.hub.load("snakers4/silero-vad:master", "silero_vad")
    assert isinstance(model, Model) and utilities is None
    assert loaded == [str(vad / voice_sidecar.SILERO_WEIGHTS), "eval"]
    for repo, name, kwargs in (("snakers4/silero-vad", "silero_vad", {"source": "github", "onnx": True}),
                               ("someone/else", "silero_vad", {}), ("snakers4/silero-vad", "other", {})):  # fmt: skip
        with pytest.raises(SpeechPackError, match="voice_torch_hub_refused"):
            torch.hub.load(repo, name, **kwargs)
    with pytest.raises(SpeechPackError, match="voice_torch_hub_refused"):
        torch.hub.load_state_dict_from_url("https://example.invalid/weights.pt")
    assert hub_calls == []


@pytest.mark.parametrize("name", ["vad/hubconf.py", "vad/utils_vad.py", "stt/kernel.so", "tts/loader.pyc"])
def test_sec09_speech_model_components_carry_no_code(tmp_path: Path, name: str) -> None:
    from agent_core.store.speech_packs import SpeechManifest, SpeechPackError, check_components
    from test_m32_speech_packs import pack

    document = pack(tmp_path / "pack")
    role = name.split("/")[0]
    entry = next(f for f in document["files"] if f["role"] == role)
    entry["path"] = name
    with pytest.raises(SpeechPackError, match="speech_pack_component_refused"):
        check_components(SpeechManifest.model_validate(document))


# --- speech and perception packs roll forward only ----------------------------------------------------------------


def _speech_pack(folder: Path, version: str) -> dict:
    from test_m32_speech_packs import pack, signed

    document = pack(folder)
    document.pop("signature")
    document["speech_pack_id"] = f"sp.en.{version}"
    return signed(folder, document)


def test_sec15_speech_pack_downgrade_refused(tmp_path: Path) -> None:
    from agent_core.store.speech_packs import SpeechPackError
    from test_m32_speech_packs import store

    desk = store(tmp_path / "speech-packs")
    _speech_pack(tmp_path / "v2", "2_0")
    _speech_pack(tmp_path / "v1", "1_0")
    _speech_pack(tmp_path / "v3", "3_0")
    desk.install(tmp_path / "v2")
    with pytest.raises(SpeechPackError, match="speech_pack_older_than_installed"):
        desk.install(tmp_path / "v1")
    assert not (desk.root / "sp.en.1_0").exists()
    assert desk.install(tmp_path / "v2").name == "sp.en.2_0", "the same version again is not a downgrade"
    assert desk.remove("sp.en.2_0")
    with pytest.raises(SpeechPackError, match="speech_pack_older_than_installed"):
        desk.install(tmp_path / "v1")  # removing the newer pack does not reopen the older one
    assert desk.install(tmp_path / "v3").name == "sp.en.3_0"


def test_sec16_speech_newest_refused_no_fallback(tmp_path: Path) -> None:
    from agent_core.net.voice_launch import VoiceLaunch
    from signing_service.hierarchy import dev_trust
    from test_m32_speech_packs import store

    root = tmp_path / "speech-packs"
    desk = store(root)
    _speech_pack(tmp_path / "v1", "1_0")
    _speech_pack(tmp_path / "v2", "2_0")
    desk.install(tmp_path / "v1")
    link = VoiceLaunch(root, "mid", "linux-x86_64", "0.0.0", Environment.DEV, "http://127.0.0.1:1/v1/voice/llm",
                       "t" * 32, lambda frame: None, trust=dev_trust())  # fmt: skip
    assert link.scan() and link.selected is not None and link.selected[0].name == "sp.en.1_0"
    desk.install(tmp_path / "v2")
    assert link.scan() and link.selected is not None and link.selected[0].name == "sp.en.2_0"
    (root / "sp.en.2_0" / "sidecar" / "jana-voice").write_bytes(b"synthetic tamper")  # the newest fails its checks
    assert not link.scan() and link.selected is None, "the older pack is not offered in its place"


def _perception_pack(folder: Path, release: str) -> dict:
    import json

    from agent_core.store.perception_packs import ARTEFACT, target
    from signing_service.hierarchy import dev_signer
    from signing_service.keys import Purpose
    from test_m21_perception_pack import NOW, pack

    _, manifest = pack(folder)
    os_name, arch = target()
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    unsigned["version"] = release
    unsigned["perception_pack_id"] = f"pp.printed.v{release.split('.')[0]}.{os_name}.{arch}"
    signed: dict = dev_signer(Purpose.UPDATER).sign(ARTEFACT, unsigned, now=NOW)
    (folder / "manifest.json").write_text(json.dumps(signed))
    return signed


def test_sec15_perception_pack_downgrade_refused(tmp_path: Path) -> None:
    from agent_core.store.perception_packs import PerceptionPackError, PerceptionPackStore

    store = PerceptionPackStore(tmp_path / "installed", Environment.DEV, "1.0.0")
    newer = _perception_pack(tmp_path / "v2", "2.0.0")
    older = _perception_pack(tmp_path / "v1", "1.0.0")
    assert store.install(tmp_path / "v2") == newer["perception_pack_id"]
    with pytest.raises(PerceptionPackError, match="older than the installed"):
        store.install(tmp_path / "v1")
    assert not (store.root / older["perception_pack_id"]).exists()
    assert store.remove(newer["perception_pack_id"])
    with pytest.raises(PerceptionPackError, match="older than the installed"):
        store.install(tmp_path / "v1")


def test_sec16_perception_newest_revoked_no_fallback(tmp_path: Path) -> None:
    from agent_core.config.trust import SignatureRefused, bundled_trust
    from agent_core.store.perception_packs import PerceptionPackStore

    revoked: set[str] = set()

    class Revoking:
        """The bundled trust, with the signatures of the packs in `revoked` refused (as a revocation list would)."""

        def verify(self, artefact: str, document: dict, environment: Environment, signed_at: str) -> None:
            if document.get("perception_pack_id") in revoked:
                raise SignatureRefused("synthetic revocation")
            bundled_trust().verify(artefact, document, environment, signed_at=signed_at)

    store = PerceptionPackStore(tmp_path / "installed", Environment.DEV, "1.0.0", trust=Revoking)  # type: ignore[arg-type]
    older = _perception_pack(tmp_path / "v1", "1.0.0")
    newer = _perception_pack(tmp_path / "v2", "2.0.0")
    store.install(tmp_path / "v1")
    store.install(tmp_path / "v2")
    command = store.command("mid")
    assert command is not None and newer["perception_pack_id"] in command[0]
    revoked.add(newer["perception_pack_id"])
    assert store.command("mid") is None, "the older build is never launched in place of a revoked newer one"
    revoked.clear()
    revoked.add(older["perception_pack_id"])
    command = store.command("mid")
    assert command is not None and newer["perception_pack_id"] in command[0]


# --- Linux: bubblewrap, the Landlock fallback, and no unsandboxed worker in a release ----------------------------


def _linux(monkeypatch: pytest.MonkeyPatch, *, bwrap: bool, usable: bool = True, abi: int = 0) -> None:
    """The Linux branch of `sandboxed` on any host: bubblewrap present or not, usable or not, a Landlock ABI."""
    from agent_core.tools.worker import landlock, sandbox

    real_which = sandbox.shutil.which
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" and bwrap
                        else None if name == "bwrap" else real_which(name))  # fmt: skip
    monkeypatch.setattr(sandbox, "bubblewrap_usable", lambda path: usable)
    monkeypatch.setattr(landlock, "abi", lambda platform=sys.platform: abi)


def test_sec06_linux_landlock_fallback_selected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.tools.worker import landlock
    from agent_core.tools.worker.sandbox import sandboxed

    argv = [sys.executable, "-m", "tool_worker"]
    for bwrap, usable, reason in ((False, True, "bubblewrap is not installed"),
                                  (True, False, "bubblewrap cannot create its namespaces")):  # fmt: skip
        _linux(monkeypatch, bwrap=bwrap, usable=usable, abi=3)
        wrapped = sandboxed(argv, tmp_path / "scratch", "linux")
        assert (wrapped.mechanism, wrapped.reduced_protection, wrapped.reason) == ("landlock", False, reason)
        assert wrapped.argv[:3] == [sys.executable, "-m", landlock.LAUNCHER_MODULE] and wrapped.argv[-3:] == argv
        policy, worker = landlock.parse_launcher_args(wrapped.argv[3:])
        assert worker == argv
        assert policy.write_paths == (str((tmp_path / "scratch").resolve()), "/dev/null")
        assert "/usr" in policy.read_paths and str(Path.home()) not in policy.read_paths
    _linux(monkeypatch, bwrap=True, usable=True, abi=3)
    assert sandboxed(argv, tmp_path / "scratch", "linux").mechanism == "bubblewrap", "bubblewrap is preferred"
    _linux(monkeypatch, bwrap=False, abi=0)
    wrapped = sandboxed(argv, tmp_path / "scratch", "linux")
    assert wrapped.reduced_protection and wrapped.reason == "bubblewrap is not installed and Landlock is unavailable"
    frozen = landlock.launcher_argv(policy, argv, python="/opt/jana/agent-core", frozen=True)
    assert frozen[:2] == ["/opt/jana/agent-core", landlock.FROZEN_FLAG]
    assert landlock.parse_launcher_args(frozen[1:]) == (policy, argv)


def test_sec06_release_worker_never_unsandboxed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.tools.worker import launch, sandbox
    from agent_core.tools.worker.launch import SandboxUnavailable

    _linux(monkeypatch, bwrap=False, abi=0)  # a Linux machine with neither bubblewrap nor Landlock
    monkeypatch.setattr(
        launch, "sandboxed", lambda argv, scratch, **kw: sandbox.sandboxed(argv, scratch, "linux", **kw)
    )
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=10.0)
    argv = [sys.executable, str(HARNESS)]
    with pytest.raises(SandboxUnavailable, match="bubblewrap is not installed"):
        process_factory(settings, argv, tmp_path / "scratch", require_sandbox=True)()
    assert not list((tmp_path / "scratch").iterdir()), "the refused worker's scratch directory is removed"

    async def scenario() -> None:
        supervisor = WorkerSupervisor(process_factory(settings, argv, tmp_path / "scratch", require_sandbox=True),
                                      settings)  # fmt: skip
        await supervisor.start()
        assert not supervisor.compute_available(), "compute tools stay hidden"
        assert supervisor.reduced_protection, "the health panel shows the sandbox degraded"
        outcome = await supervisor.call("math_parse", 1, {"text": "x+1"}, CHECK, 10000)
        assert outcome.error == "worker_unavailable"
        await supervisor.close()

    asyncio.run(scenario())


def test_sec06_release_pool_requires_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from agent_core.engine import assembly
    from agent_core.tools.worker.launch import SandboxUnavailable

    seen: list[bool] = []

    def refuse() -> None:
        raise SandboxUnavailable("test")

    def factory(settings: Settings, scratch_root: Path, require_sandbox: bool = False):
        seen.append(require_sandbox)
        return refuse

    monkeypatch.setattr(assembly, "process_factory", factory)
    settings = Settings(worker_pool_size=1)
    for release in (True, False):
        supervisor = asyncio.run(assembly.start_worker_pool(settings, tmp_path, release=release))
        assert supervisor.sandbox_refused == "test"
    assert seen == [True, False]


def test_sec06_landlock_structures() -> None:
    import ctypes

    from agent_core.tools.worker import landlock

    assert ctypes.sizeof(landlock.PathBeneathAttr) == 12, "packed, as linux/landlock.h declares it"
    assert ctypes.sizeof(landlock.RulesetAttr) == 24 and ctypes.sizeof(landlock.SockFilter) == 8
    assert [landlock.ruleset_size(v) for v in (1, 3, 4, 5, 6, 7)] == [8, 8, 16, 16, 24, 24]
    assert landlock.handled(1).handled_access_fs == (1 << 13) - 1 and landlock.handled(1).handled_access_net == 0
    assert landlock.handled(4).handled_access_net == 3 and landlock.handled(6).scoped == 3
    assert landlock.handled(9).handled_access_fs == (1 << 16) - 1, "a newer kernel gets every right this build knows"
    write_all = landlock.FS_BY_ABI[5]
    assert landlock.rule_rights(5, write_all, directory=False) & ~landlock.FILE_RIGHTS == 0
    assert landlock.rule_rights(1, landlock.READ_RIGHTS, directory=True) == landlock.READ_RIGHTS
    assert landlock.abi("darwin") == 0 and landlock.abi("win32") == 0
    policy = landlock.policy_for([Path("/opt/runtime")], Path("/srv/scratch"))
    assert landlock.LandlockPolicy.decode(policy.encode()) == policy


def _run_filter(code: bytes, nr: int, arch: int, args: tuple[int, ...] = ()) -> int:
    """A tiny classic-BPF interpreter for the instructions `seccomp.program` emits, over a `seccomp_data`."""
    import struct

    from agent_core.tools.worker import seccomp

    data = struct.pack("<IIQ6Q", nr, arch, 0, *(list(args) + [0] * (6 - len(args))))
    insns = [struct.unpack("<HBBI", code[i : i + 8]) for i in range(0, len(code), 8)]
    pc, accumulator = 0, 0
    while True:
        op, jt, jf, k = insns[pc]
        pc += 1
        if op == seccomp.LD_W_ABS:
            accumulator = struct.unpack("<I", data[k : k + 4])[0]
        elif op == seccomp.JEQ_K:
            pc += jt if accumulator == k else jf
        elif op == seccomp.JSET_K:
            pc += jt if accumulator & k else jf
        elif op == seccomp.RET_K:
            return k
        else:
            raise AssertionError(f"unexpected instruction {op:#x}")


@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
def test_sec06_seccomp_filters(machine: str) -> None:
    import errno

    from agent_core.tools.worker import seccomp

    arch, numbers = seccomp.ARCHES[machine]
    allow, deny = seccomp.SECCOMP_RET_ALLOW, seccomp.SECCOMP_RET_ERRNO | errno.EPERM
    af_inet, read_call = 2, 0 if machine == "x86_64" else 63
    bubblewrap = seccomp.program(machine)
    landlocked = seccomp.program(machine, own_pid=4321)
    for code in (bubblewrap, landlocked):
        assert _run_filter(code, read_call, arch) == allow
        assert _run_filter(code, numbers["clone"], arch, (seccomp.CLONE_THREAD,)) == allow, "threads"
        assert _run_filter(code, numbers["clone"], arch, (0,)) == deny, "new processes"
        assert _run_filter(code, numbers["clone3"], arch) == seccomp.SECCOMP_RET_ERRNO | errno.ENOSYS
        assert _run_filter(code, numbers["ptrace"], arch) == deny
        assert _run_filter(code, numbers["socket"], arch, (af_inet,)) == deny
        assert _run_filter(code, read_call, 0xDEADBEEF) == seccomp.SECCOMP_RET_KILL_PROCESS
    # Inside bubblewrap's empty namespaces: Unix sockets and signals reach nothing outside.
    assert _run_filter(bubblewrap, numbers["socket"], arch, (seccomp.AF_UNIX,)) == allow
    assert _run_filter(bubblewrap, numbers["kill"], arch, (1,)) == allow
    # Under Landlock, on the host's namespaces: no socket at all, signals to itself only, no reaching into others.
    assert _run_filter(landlocked, numbers["socket"], arch, (seccomp.AF_UNIX,)) == deny
    assert _run_filter(landlocked, numbers["kill"], arch, (4321, 9)) == allow
    assert _run_filter(landlocked, numbers["tgkill"], arch, (4321, 4322, 6)) == allow
    for target in (1, 4320, 0, 0xFFFFFFFF):
        assert _run_filter(landlocked, numbers["kill"], arch, (target, 9)) == deny, target
        assert _run_filter(landlocked, numbers["tgkill"], arch, (target, target, 9)) == deny, target
    for name in seccomp.CROSS_PROCESS:
        assert _run_filter(landlocked, numbers[name], arch, (4321,)) == deny, name


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Landlock is a Linux kernel feature (Linux runner)")
def test_sec06_landlock_escape_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`sec06_sandbox_escape_suite` with the Landlock fallback instead of bubblewrap (the Linux CI runner)."""
    from agent_core.tools.worker import landlock, sandbox

    if landlock.abi() < 1:
        pytest.skip("this kernel has no Landlock (5.13 or later with Landlock enabled)")
    monkeypatch.setattr(sandbox, "bubblewrap_usable", lambda path: False)
    home_file = Path.home() / ".jana-landlock-sentinel"
    home_file.write_text("private")
    outside = REPO_ROOT / ".landlock-escape-test"
    learner_db = tmp_path / "learner.db"
    learner_db.write_bytes(b"SQLite format 3\x00")
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=10.0,
                        worker_circuit_restarts=100)  # fmt: skip

    async def scenario() -> None:
        for extra in (["--no-guard"], []):
            factory = process_factory(settings, [sys.executable, str(HARNESS), *extra], tmp_path / "scratch",
                                      require_sandbox=True)  # fmt: skip
            supervisor = WorkerSupervisor(factory, settings)
            await supervisor.start()
            assert supervisor._all and supervisor._all[0].sandbox_mechanism == "landlock"
            args = {"home_file": str(home_file), "outside": str(outside), "learner_db": str(learner_db)}
            outcome = await supervisor.call("escape", 1, args, CHECK, 10000)
            assert outcome.ok, outcome
            report = outcome.result["value"] if outcome.result else {}
            assert report.pop("write_scratch") == "ALLOWED"
            assert all(v.startswith("denied") for v in report.values()), report
            await supervisor.close()
        assert not outside.exists()

    try:
        asyncio.run(scenario())
    finally:
        home_file.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def test_sec06_deb_depends_on_bubblewrap() -> None:
    import json

    config = json.loads((REPO_ROOT / "apps/desktop/src-tauri/tauri.release.conf.json").read_text())
    assert "bubblewrap" in config["bundle"]["linux"]["deb"]["depends"]
