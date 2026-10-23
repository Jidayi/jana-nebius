"""M20.b: model packs, install sources, pack updates, the app channel and the packs/models API (PLT-10, PLT-12, PLT-13,
API-22, API-29, UXS-11; PLT-21 and the core half of PLT-23 from M20.a). Packs, models and kits are synthetic, signed
with the test hierarchy; the "weights" are random bytes; no test reaches a network."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agent_core.api.errors import ApiError
from agent_core.api.packs import PackDesk
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.config.trust import Purpose
from agent_core.contracts import errors as contract_errors
from agent_core.store import pack_diff
from agent_core.store.kit_install import MODEL_FILE, install_kit
from agent_core.store.model_pack_store import (
    ADAPTER_BASE,
    DAMAGED,
    TOO_SMALL,
    ModelPackError,
    ModelPackStore,
    sign_pack,
    weights_sha256,
)
from agent_core.store.pack_store import PackStore
from agent_core.store.packs import PackRejectedError, read_pack
from api_harness import Running, sse, start_core, stop_core
from m20_fixtures import SIGNED_AT, content_pack, empty_tables, model_pack
from signing_service.hierarchy import dev_signer
from signing_service.service import sign_kit
from test_m10a_profiles import Api, code

DEV = Environment.DEV
LOOP = asyncio.new_event_loop()


def test_download_without_transport_is_refused(tmp_path: Path) -> None:
    desk = PackDesk(
        tmp_path / "data", DEV, "1.0.0", lambda _: None, downloads_on=lambda: True, free_bytes=lambda: 10**12
    )
    source = tmp_path / "source" / "mp.synth.8b.q4_k_m.low"
    manifest = model_pack(source)
    desk.available = lambda: [
        {
            "model_pack_id": manifest["model_pack_id"],
            "manifest": manifest,
            "base_url": "https://downloads.dev.jana.invalid/models",
        }
    ]
    with pytest.raises(ApiError) as refused:
        desk.start_download(manifest["model_pack_id"])
    assert refused.value.code == "feature_disabled"
    assert desk.downloads == {}


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    """Networking disabled for the test: any connection to a non-loopback address fails, and so does a DNS lookup."""
    real_connect = socket.socket.connect
    real_lookup = socket.getaddrinfo

    def connect(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("networking is disabled for this test")
        return real_connect(sock, address)

    def lookup(host: Any, *args: Any, **kw: Any) -> Any:
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise OSError("networking is disabled for this test")
        return real_lookup(host, *args, **kw)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.getaddrinfo = lookup  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.getaddrinfo = real_lookup


# --- PLT-10 -------------------------------------------------------------------------------------------------------


def plt10_tampered_model_pack_refused(tmp_path: Path) -> None:
    """A pack whose file hash, file size or manifest signature does not match is refused before load with the
    damaged-file message; a pack under 7B is refused by the build and the device (D58)."""
    store = ModelPackStore(tmp_path / "models", DEV, "1.0.0")
    good = tmp_path / "src" / "mp.synth.8b.q4_k_m.low"
    model_pack(good)
    for name, damage in (
        ("hash", lambda f: f.write_bytes(b"\x00" + f.read_bytes()[1:])),
        ("size", lambda f: f.write_bytes(f.read_bytes() + b"\x00")),
        ("signature", None),
    ):
        copy = tmp_path / name / good.name
        shutil.copytree(good, copy)
        if damage is not None:
            damage(copy / "model.gguf")
        else:
            manifest = json.loads((copy / "manifest.json").read_text())
            manifest["tiers"] = ["fast", "strong", "judge"]  # a change after signing
            (copy / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ModelPackError) as refused:
            store.install(copy)
        assert refused.value.code == DAMAGED, name
        assert store.installed() == [], f"nothing installed after a bad {name}"

    store.install(good)
    installed = store.root / good.name / "model.gguf"
    installed.write_bytes(installed.read_bytes()[:-1] + b"\x01")  # damaged on disk after install
    with pytest.raises(ModelPackError) as refused:
        store.verify(good.name)
    assert refused.value.code == DAMAGED and store.installed()[0]["error_code"] == DAMAGED

    small = tmp_path / "small" / "mp.synth.3b.q4_k_m.low"
    model_pack(small, small.name)
    with pytest.raises(ModelPackError) as refused:
        store.install(small)
    assert refused.value.code == TOO_SMALL
    unsigned = {k: v for k, v in json.loads((small / "manifest.json").read_text()).items() if k != "signature"}
    with pytest.raises(ModelPackError):
        sign_pack(unsigned, lambda a, d: dev_signer(Purpose.MODEL).sign(a, d), lambda _: True)
    eight = {k: v for k, v in json.loads((good / "manifest.json").read_text()).items() if k != "signature"}
    with pytest.raises(ModelPackError):  # the evaluation report did not pass: not signed for release
        sign_pack(eight, lambda a, d: dev_signer(Purpose.MODEL).sign(a, d, now=SIGNED_AT), lambda _: False)
    assert sign_pack(eight, lambda a, d: dev_signer(Purpose.MODEL).sign(a, d, now=SIGNED_AT), lambda _: True)


def plt10_model_licence_shown(tmp_path: Path) -> None:
    """Every installed pack's licence and attribution reach Settings → About → Licences (through GET /v1/models)."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path)
        try:
            for pack_id in ("mp.synth.8b.q4_k_m.low", "mp.other.12b.q5_k_m.mid"):
                model_pack(tmp_path / "src" / pack_id, pack_id, licence="CC-BY-4.0")
                desk.models.install(tmp_path / "src" / pack_id)
            reply = await r.get("/v1/models")
            assert reply.status_code == 200
            listed = {row["model_pack_id"]: row for row in reply.json()["installed"] if "model_pack_id" in row}
            assert set(listed) == {"mp.synth.8b.q4_k_m.low", "mp.other.12b.q5_k_m.mid"}
            for row in listed.values():
                assert row["licence"] == "CC-BY-4.0" and row["attribution"].startswith("Synthetic")
            assert [x["model_pack_id"] for x in desk.models.licences()] == sorted(listed)
        finally:
            await stop_core(r)

    run(scenario())


def plt10_adapter_requires_exact_base(tmp_path: Path) -> None:
    """An adapter pack whose `adapter_for` hash does not match the installed base's weights is refused before load,
    and so is one whose base is missing; on its exact base it installs."""
    store = ModelPackStore(tmp_path / "models", DEV, "1.0.0")
    base = model_pack(tmp_path / "src" / "mp.synth.8b.q4_k_m.low")
    adapter_id = "mp.synth.8b.q4_k_m.low.ft_2027_03"
    wrong = model_pack(tmp_path / "wrong" / adapter_id, adapter_id,
                       adapter_for={"model_pack_id": base["model_pack_id"], "weights_sha256": "0" * 64})  # fmt: skip
    assert wrong["adapter_for"]["weights_sha256"] != weights_sha256(base)
    right_dir = tmp_path / "right" / adapter_id
    exact = {"model_pack_id": base["model_pack_id"], "weights_sha256": weights_sha256(base)}
    model_pack(right_dir, adapter_id, adapter_for=exact)

    with pytest.raises(ModelPackError) as refused:
        store.install(right_dir)
    assert refused.value.code == ADAPTER_BASE, "no base installed yet"
    store.install(tmp_path / "src" / base["model_pack_id"])
    with pytest.raises(ModelPackError) as refused:
        store.install(tmp_path / "wrong" / adapter_id)
    assert refused.value.code == ADAPTER_BASE
    store.install(right_dir)
    weights = store.root / base["model_pack_id"] / "model.gguf"
    weights.write_bytes(b"swapped base weights")  # the base changed under the adapter
    with pytest.raises(ModelPackError):
        store.verify(adapter_id)


def test_failed_model_repair_preserves_installed_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ModelPackStore(tmp_path / "models", DEV, "1.0.0")
    source = tmp_path / "source" / "mp.synth.8b.q4_k_m.low"
    manifest = model_pack(source)
    store.install(source)
    target = store.root / manifest["model_pack_id"]
    before = (target / "model.gguf").read_bytes()
    original_replace = os.replace

    def fail_commit(src: Path, dst: Path) -> None:
        if src == store.root / ".staging" / manifest["model_pack_id"]:
            raise OSError("injected rename failure")
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_commit)
    with pytest.raises(OSError, match="injected rename failure"):
        store.install(source)
    assert (target / "model.gguf").read_bytes() == before
    assert store.verify(manifest["model_pack_id"]) == manifest


@pytest.mark.parametrize("committed", [False, True])
def test_model_repair_recovers_after_power_loss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               committed: bool) -> None:  # fmt: skip
    class PowerLoss(BaseException):
        pass

    source = tmp_path / "source" / "mp.synth.8b.q4_k_m.low"
    first = model_pack(source, weights=b"original synthetic weights")
    store = ModelPackStore(tmp_path / "models", DEV, "1.0.0")
    store.install(source)
    second = model_pack(source, weights=b"replacement synthetic weights")
    original_replace = os.replace

    def power_pull(src: Path, dst: Path) -> None:
        if src == store.root / ".staging" / first["model_pack_id"]:
            if committed:
                original_replace(src, dst)
            raise PowerLoss
        original_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", power_pull)
        with pytest.raises(PowerLoss):
            store.install(source)
    recovered = ModelPackStore(store.root, DEV, "1.0.0")
    assert recovered.verify(first["model_pack_id"]) == (second if committed else first)
    assert not list((store.root / ".previous").iterdir())


def test_model_packs_feed_the_launch_plan(tmp_path: Path) -> None:
    """Without an M11 models manifest, the installed PLT-10 packs that verify are linked for the runtime and planned;
    a pack damaged on disk is left out with the damaged-file code."""
    from agent_core.engine.runtime_link import write_launch_plan
    from agent_core.router.probe import Probe
    from jana_tools import REPO_ROOT

    probe_file = REPO_ROOT / "services" / "agent-core" / "tests" / "fixtures" / "probe" / "low.json"
    from jana_tools.fakes.models import _header

    probe = Probe.from_json(json.loads(probe_file.read_text())["probe"])
    _header(tmp_path / "weights.gguf", 2 * 1024 * 1024)  # a synthetic GGUF header, padded: no real weights
    weights = (tmp_path / "weights.gguf").read_bytes()
    store = ModelPackStore(tmp_path / "models" / "packs", DEV, "0.0.0")
    for pack_id in ("mp.synth.8b.q4_k_m.low", "mp.broken.8b.q4_k_m.low"):
        model_pack(tmp_path / "src" / pack_id, pack_id, weights=weights, chunk_bytes=1024 * 1024)
        store.install(tmp_path / "src" / pack_id)
    damaged = store.root / "mp.broken.8b.q4_k_m.low" / "model.gguf"
    damaged.write_bytes(b"changed")
    plan = write_launch_plan(tmp_path, Settings(), False, "0123456789abcdef", probe=probe)
    assert plan["model"] == "mp.synth.8b.q4_k_m.low", plan
    assert ["mp.broken.8b.q4_k_m.low", DAMAGED] in plan["left_out"]
    linked = Path(plan["models_dir"]) / "mp.synth.8b.q4_k_m.low" / "model.gguf"
    assert linked.is_symlink() and linked.resolve() == (store.root / "mp.synth.8b.q4_k_m.low" / "model.gguf").resolve()


# --- PLT-12 -------------------------------------------------------------------------------------------------------


def _kit(tmp_path: Path, subjects: tuple[str, ...] = ("phy", "mth", "chm"), model_bytes: int = 4 * 1024 * 1024,
         revocation_list: dict[str, Any] | None = None) -> Path:  # fmt: skip
    kit = tmp_path / "kit"
    (kit / "packs").mkdir(parents=True)
    files = []
    for subject in subjects:
        content_pack(kit / "packs" / f"pack.{subject}.o.pack", f"pack.{subject}.o")
        files.append((f"packs/pack.{subject}.o.pack", "content_pack"))
    pack_id = "mp.synth.8b.q4_k_m.low"
    model_pack(kit / "models" / pack_id, weights=bytes(model_bytes), chunk_bytes=1024 * 1024)
    files += [(f"models/{pack_id}/{name}", MODEL_FILE) for name in ("manifest.json", "model.gguf")]
    sign_kit(kit, files, revocation_list=revocation_list)
    return kit


def plt12_usb_install_time_offline(tmp_path: Path) -> None:
    """With networking disabled, a USB-kit install of three subject packs and the low-class model finishes within the
    budget, through the same verification as a download. The full-size run on the low-class reference laptop is the
    device lab's (JANA_DEVLAB_RESULTS); here the kit is synthetic and the timing is this machine's."""
    budget_s = Settings().usb_install_budget_min * 60
    kit = _kit(tmp_path)
    packs = PackStore(tmp_path / "data" / "packs", DEV)
    models = ModelPackStore(tmp_path / "data" / "models" / "packs", DEV, "1.0.0")
    with no_network():
        started = time.monotonic()
        report = install_kit(kit, packs, models, DEV)
        elapsed = time.monotonic() - started
    assert report.refused == []
    assert sorted(report.content) == ["pack.chm.o", "pack.mth.o", "pack.phy.o"]
    assert report.models == ["mp.synth.8b.q4_k_m.low"]
    assert elapsed < budget_s
    assert packs.load_all()[1] == [] and models.installed()[0]["state"] == "installed"

    (kit / "packs" / "pack.mth.o.pack").write_bytes(b"not the file the kit lists")
    again = install_kit(kit, PackStore(tmp_path / "other" / "packs", DEV), None, DEV)
    assert ("pack.mth.o", "pack.damaged") in again.refused and len(again.content) == 2

    lab = os.environ.get("JANA_DEVLAB_RESULTS")
    runs = [json.loads(p.read_text()) for p in sorted(Path(lab).glob("*.json"))] if lab else []
    timed = [r for r in runs if r.get("hardware_class") == "low" and "usb_install_s" in r]
    if not timed:
        pytest.skip("the full-size kit's install time on the low-class reference laptop is the device lab's "
                    "(JANA_DEVLAB_RESULTS: usb_install_s)")  # fmt: skip
    assert all(r["usb_install_s"] < budget_s for r in timed), timed


def test_kit_listing_outside_its_contract_is_refused(tmp_path: Path) -> None:
    """A kit listing correctly signed by a content key but not matching the `ops/usb-kit` contract (each file's size
    named `bytes` instead of `size_bytes`) is refused like a bad signature, before anything is copied (D39)."""
    from agent_core.store.pack_channels import KIT_ARTEFACT, KIT_FILE, ChannelError, kit_listing

    kit = _kit(tmp_path, subjects=("phy",), model_bytes=1024)
    listing = json.loads((kit / KIT_FILE).read_text())
    assert contract_errors("ops/usb-kit", listing) == [] and kit_listing(kit, DEV).files[0].size_bytes > 0
    renamed = [{("bytes" if k == "size_bytes" else k): v for k, v in f.items()} for f in listing["files"]]
    resigned = dev_signer(Purpose.CONTENT).sign(KIT_ARTEFACT, {**listing, "files": renamed}, now=listing["created_at"])
    (kit / KIT_FILE).write_text(json.dumps(resigned))
    with pytest.raises(ChannelError, match="contract"):
        kit_listing(kit, DEV)
    packs = PackStore(tmp_path / "data" / "packs", DEV)
    with pytest.raises(ChannelError):
        install_kit(kit, packs, None, DEV)
    assert packs.load_all()[0] == {}


# --- PLT-13 -------------------------------------------------------------------------------------------------------


def _store_with_v1(tmp_path: Path, **kw: Any) -> tuple[PackStore, dict[str, Any]]:
    store = PackStore(tmp_path / "packs", DEV, **kw)
    v1 = content_pack(tmp_path / "v1.pack")
    store.install(tmp_path / "v1.pack")
    return store, v1


def plt13_failed_diff_keeps_previous(tmp_path: Path) -> None:
    """A diff that fails (a result that does not match the signed new manifest, or a diff for another version) leaves
    the previous pack loaded and byte-for-byte unchanged."""
    store, v1 = _store_with_v1(tmp_path)
    before = store.active_path("pack.phy.o").read_bytes()
    v2 = content_pack(tmp_path / "v2.pack", version="0.2.0", title="Synthetic phy pack, revised")
    bad_rows = pack_diff.make_diff(v1, empty_tables(), v2, empty_tables(), SIGNED_AT)
    bad_rows["changes"] = [{"table": "kcs", "delete": [], "upsert": [{"id": "kc.phy.o.synthetic.0001"}]}]
    signed = dev_signer().sign(pack_diff.ARTEFACT, bad_rows, now=SIGNED_AT)
    with pytest.raises(PackRejectedError):
        store.apply_diff(signed)
    other = dict(pack_diff.make_diff(v1, empty_tables(), v2, empty_tables(), SIGNED_AT), from_version="0.0.9")
    with pytest.raises(PackRejectedError):
        store.apply_diff(dev_signer().sign(pack_diff.ARTEFACT, other, now=SIGNED_AT))
    assert store.active_path("pack.phy.o").read_bytes() == before
    assert store.installed("pack.phy.o")["version"] == "0.1.0"  # type: ignore[index]
    assert read_pack(store.load("pack.phy.o"))[0]["version"] == "0.1.0"
    assert not list((tmp_path / "packs" / ".staging").glob("*")), "no half-applied copy is left"


def plt13_no_mid_session_swap(tmp_path: Path) -> None:
    """A pack update that arrives while a practice set is open is verified at once but applies only at the next
    session start; the open session keeps reading the version it started with."""
    practising = {"open": True}
    store, v1 = _store_with_v1(tmp_path, busy=lambda: practising["open"])
    v2 = content_pack(tmp_path / "v2.pack", version="0.2.0", title="Synthetic phy pack, revised")
    diff = dev_signer().sign(pack_diff.ARTEFACT, pack_diff.make_diff(v1, empty_tables(), v2, empty_tables(),
                                                                     SIGNED_AT), now=SIGNED_AT)  # fmt: skip
    store.apply_diff(diff)
    assert store.ready_updates() == {"pack.phy.o": "0.2.0"}
    assert read_pack(store.load("pack.phy.o"))[0]["version"] == "0.1.0", "the practice set keeps its content"

    practising["open"] = False  # the session ended; the next one starts
    applied = store.apply_ready()
    assert [m["version"] for m in applied] == ["0.2.0"] and store.ready_updates() == {}
    assert read_pack(store.load("pack.phy.o"))[0]["version"] == "0.2.0"
    assert PackStore(tmp_path / "packs", DEV).installed("pack.phy.o")["version"] == "0.2.0"  # type: ignore[index]


# --- the API (API-22, API-29, UXS-11) ------------------------------------------------------------------------------


class FakeShell:
    """Stands in for the shell's download manager over the control channel: it "fetches" each file from a local
    folder (the stand-in CDN) and reports states as the shell does. `cut_at` drops the connection once, mid-file."""

    def __init__(self, desk: PackDesk, served: Path, cut_at: float | None = None) -> None:
        self.desk = desk
        self.served = served
        self.cut_at = cut_at
        self.started: list[dict[str, Any]] = []
        self.actions: list[tuple[str, str]] = []
        self.tasks: list[asyncio.Task[Any]] = []

    def start(self, request: dict[str, Any]) -> None:
        self.started.append(request)
        self.tasks.append(asyncio.get_running_loop().create_task(self._run(request)))

    def control(self, download_id: str, action: str) -> None:
        self.actions.append((download_id, action))

    async def _run(self, request: dict[str, Any]) -> None:
        target = Path(request["target"])
        target.mkdir(parents=True, exist_ok=True)
        total = sum(int(f["size_bytes"]) for f in request["files"])
        done = 0

        def state(name: str, **extra: Any) -> None:
            self.desk.on_shell_state({"download_id": request["download_id"], "state": name, "bytes_done": done,
                                      "bytes_total": total, **extra})  # fmt: skip

        for spec in request["files"]:
            data = (self.served / spec["name"]).read_bytes()
            (target / spec["name"]).write_bytes(data)
            for _ in range(4):
                await asyncio.sleep(0.01)
                done = min(total, done + len(data) // 4)
                state("downloading", eta_s=1)
                if self.cut_at is not None and done >= total * self.cut_at:
                    self.cut_at = None
                    state("waiting_for_network")
                    await asyncio.sleep(0.02)
        done = total
        state("installing")
        state("done")
        await self.desk.close_downloads()


def test_download_reconnect_and_install_only_after_final_rename(tmp_path: Path) -> None:
    async def scenario() -> None:
        frames: list[dict[str, Any]] = []
        from agent_core.api.packs import ControlDownloads

        data = tmp_path / "data"
        desk = PackDesk(data, DEV, "1.0.0", lambda _: None, shell=ControlDownloads(frames.append),
                        downloads_on=lambda: True, free_bytes=lambda: 10**12)  # fmt: skip
        source = _offer(tmp_path, desk)
        manifest = json.loads((source / "manifest.json").read_text())
        first = desk.start_download(source.name)
        assert desk.start_download(source.name) == first
        assert len(frames) == 1, "repeated requests reconnect to the existing job"
        download_id = first["download_id"]
        desk.on_shell_state({"download_id": download_id, "state": "installing"})
        await asyncio.sleep(0)
        assert desk.models.installed() == [], "installing precedes the shell's atomic final rename"
        assert not Path(frames[0]["target"]).exists()

        recovered = PackDesk(data, DEV, "1.0.0", lambda _: None, shell=ControlDownloads(frames.append),
                             downloads_on=lambda: True, free_bytes=lambda: 10**12)  # fmt: skip
        recovered.recover_downloads()
        assert frames[-1] == frames[0], "a core restart hands back the identical journal job"
        assert recovered.catalogue({})["available"][0]["download"]["download_id"] == download_id
        incoming = Path(frames[0]["target"])
        incoming.mkdir(parents=True)
        for file in manifest["files"]:
            shutil.copyfile(source / file["path"], incoming / file["path"])
        recovered.on_shell_state({"download_id": download_id, "state": "done"})
        await recovered.close_downloads()
        assert recovered.state(download_id)["state"] == "done"
        assert recovered.models.verify(source.name) == manifest
        again = PackDesk(data, DEV, "1.0.0", lambda _: None)
        assert again.state(download_id)["state"] == "done"

    run(scenario())


def test_download_recovery_finishes_files_renamed_before_core_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        from agent_core.api.packs import ControlDownloads

        frames: list[dict[str, Any]] = []
        data = tmp_path / "data"
        desk = PackDesk(data, DEV, "1.0.0", lambda _: None, shell=ControlDownloads(frames.append),
                        downloads_on=lambda: True, free_bytes=lambda: 10**12)  # fmt: skip
        source = _offer(tmp_path, desk)
        download_id = desk.start_download(source.name)["download_id"]
        shutil.copytree(source, frames[0]["target"])
        # The core never saw the terminal shell frame, but the final folder is already in place.
        recovered = PackDesk(data, DEV, "1.0.0", lambda _: None, shell=ControlDownloads(frames.append))
        recovered.recover_downloads()
        await recovered.close_downloads()
        assert recovered.state(download_id)["state"] == "done"
        assert len(frames) == 1, "the model is verified locally rather than downloaded again"

    run(scenario())


async def _core(tmp_path: Path, downloads: bool = True, free: int = 10**12) -> tuple[Running, PackDesk]:
    r = await start_core(tmp_path / "data", worker=False)
    flags = {"downloads": downloads}
    desk = PackDesk(tmp_path / "data", DEV, "1.0.0", r.core.publish_app, downloads_on=lambda: flags["downloads"],
                    online=lambda: True, free_bytes=lambda: free)  # fmt: skip
    desk.flags = flags  # type: ignore[attr-defined]
    r.core.pack_desk = desk
    return r, desk


def _offer(tmp_path: Path, desk: PackDesk) -> Path:
    served = tmp_path / "cdn" / "mp.synth.8b.q4_k_m.low"
    manifest = model_pack(served, weights=bytes(range(256)) * 512, chunk_bytes=8192)
    base_url = f"https://downloads.dev.jana.invalid/models/{served.name}"
    desk.available = lambda: [{"model_pack_id": manifest["model_pack_id"], "manifest": manifest, "base_url": base_url}]
    return served


async def _app_events(r: Running, until: Any, cursor: str | None = None, timeout: float = 10.0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    headers = r.headers(**({"last-event-id": cursor} if cursor else {}))

    async def read() -> None:
        async with r.client.stream("GET", f"{r.base}/v1/events", headers=headers) as resp:
            assert resp.status_code == 200
            async for frame in sse(resp):
                if frame.comment or frame.event == "control":
                    continue
                envelope = frame.json()
                found.append(envelope)
                if until(envelope):
                    return

    await asyncio.wait_for(read(), timeout)
    return found


def api22_app_channel_download(tmp_path: Path) -> None:
    """A model download started from Settings, with no session open, reports its progress on the app channel in
    sequence, each envelope valid against the contract and carrying no profile data; a reconnect replays from the
    cursor."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path)
        try:
            served = _offer(tmp_path, desk)
            desk.shell = FakeShell(desk, served)
            assert r.core.sessions == {}
            listen = asyncio.create_task(_app_events(r, lambda e: e["event"].get("state") == "done"))
            await asyncio.sleep(0.05)
            reply = await r.post("/v1/models/mp.synth.8b.q4_k_m.low/download")
            assert reply.status_code == 202, reply.text
            events = await listen
            downloads = [e["event"] for e in events if e["event"]["type"] == "model.download"]
            assert downloads[0]["state"] == "queued" and downloads[-1]["state"] == "done"
            assert any(d["state"] == "downloading" and 0 < d["bytes_done"] < d["bytes_total"] for d in downloads)
            seqs = [e["seq"] for e in events]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
            for envelope in events:
                assert envelope["channel"] == "app" and envelope["session_id"] is None
                assert contract_errors("api/events", envelope) == []
            replay = await _app_events(r, lambda e: e["event"].get("state") == "done",
                                       cursor=f"{events[0]['epoch']}:{events[0]['seq']}")  # fmt: skip
            assert [e["seq"] for e in replay] == seqs[1:]
            assert desk.models.installed()[0]["state"] == "installed"
        finally:
            await stop_core(r)

    run(scenario())


def api29_usb_install_offline(tmp_path: Path) -> None:
    """`POST /v1/packs/install` from the USB kit succeeds with networking disabled, reported on the app channel."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path, downloads=False)
        try:
            kit = _kit(tmp_path)
            with no_network():
                reply = await r.post("/v1/packs/install", {"source": {"kind": "usb", "path": str(kit)}})
                assert reply.status_code == 202, reply.text
                accepted = reply.json()
                assert accepted["queued_until_online"] is False
                for _ in range(500):
                    job = (await r.get(f"/v1/jobs/{accepted['job_id']}")).json()
                    if job["state"] in ("done", "failed"):
                        break
                    await asyncio.sleep(0.02)
            assert job["state"] == "done", job
            assert contract_errors("api/commands#/$defs/Job", job) == []
            packs = (await r.get("/v1/packs")).json()["packs"]
            assert sorted(p["pack_id"] for p in packs) == ["pack.chm.o", "pack.mth.o", "pack.phy.o"]
            assert all(p["signature_ok"] for p in packs)
            assert desk.models.installed()[0]["model_pack_id"] == "mp.synth.8b.q4_k_m.low"
        finally:
            await stop_core(r)

    run(scenario())


def api29_launch_token_only(tmp_path: Path) -> None:
    """Model assignment, pack install, pack removal and model download succeed with the launch token and no adult
    token; with `downloads` off a download answers `feature_disabled`, and an adult token changes nothing."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path, downloads=True)
        api = Api(r)
        try:
            served = _offer(tmp_path, desk)
            desk.shell = FakeShell(desk, served)
            content_pack(tmp_path / "phy.pack")
            reply = await r.post("/v1/packs/install", {"source": {"kind": "file", "path": str(tmp_path / "phy.pack")}})
            assert reply.status_code == 202
            for _ in range(200):
                if desk.packs.installed("pack.phy.o"):
                    break
                await asyncio.sleep(0.02)
            assert (await r.post("/v1/models/mp.synth.8b.q4_k_m.low/download")).status_code == 202
            for _ in range(300):
                if desk.models.installed():
                    break
                await asyncio.sleep(0.02)
            choice = {"tier": "fast", "model_id": "mp.synth.8b.q4_k_m.low"}
            assigned = await api.call("PUT", "/v1/models/assignment", choice)
            assert assigned.status_code == 200, assigned.text
            removed = await api.call("DELETE", "/v1/packs/pack.phy.o")
            assert removed.status_code == 204 and desk.packs.installed("pack.phy.o") is None

            desk.flags["downloads"] = False  # type: ignore[attr-defined]
            refused = await api.call("POST", "/v1/models/mp.synth.8b.q4_k_m.low/download")
            assert refused.status_code == 403 and code(refused) == "feature_disabled"
            with_adult = await api.call("POST", "/v1/models/mp.synth.8b.q4_k_m.low/download")
            assert with_adult.status_code == 403 and code(with_adult) == "feature_disabled"
            download = {"source": {"kind": "download", "pack_id": "pack.phy.o"}}
            via_install = await api.call("POST", "/v1/packs/install", download)
            assert code(via_install) == "feature_disabled"
        finally:
            await stop_core(r)

    run(scenario())


def uxs11_integrity_rejects_bad_file(tmp_path: Path) -> None:
    """A truncated or tampered model file is rejected before loading with the damaged-file message: at install from
    USB, after a download, and when an installed file changes; the model manager lists it in the error state."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path)
        try:
            served = _offer(tmp_path, desk)
            weights = served / "model.gguf"
            weights.write_bytes(weights.read_bytes()[:-100])  # the "server" now serves a truncated file
            desk.shell = FakeShell(desk, served)
            listen = asyncio.create_task(_app_events(r, lambda e: e["event"].get("state") == "failed"))
            await asyncio.sleep(0.05)
            assert (await r.post("/v1/models/mp.synth.8b.q4_k_m.low/download")).status_code == 202
            events = await listen
            assert events[-1]["event"]["error_code"] == DAMAGED and desk.models.installed() == []

            tampered = tmp_path / "usb" / "mp.synth.8b.q4_k_m.low"
            model_pack(tampered)
            (tampered / "model.gguf").write_bytes(b"x" + (tampered / "model.gguf").read_bytes()[1:])
            reply = await r.post("/v1/packs/install", {"source": {"kind": "file", "path": str(tampered)}})
            for _ in range(200):
                job = (await r.get(f"/v1/jobs/{reply.json()['job_id']}")).json()
                if job["state"] != "running" and job["state"] != "queued":
                    break
                await asyncio.sleep(0.02)
            assert job["state"] == "failed" and job["error"]["message"] == DAMAGED
            assert desk.models.installed() == []
        finally:
            await stop_core(r)

    run(scenario())


# --- PLT-21 (M20.a) and PLT-23's core half -------------------------------------------------------------------------

STAFF_WORDS = ("teacher", "class", "roster", "staff", "school-policy", "remote-wipe", "seat")


def plt21_bulk_install_student_only(tmp_path: Path) -> None:
    """Two installs from the same USB kit, offline, have their own device identity and profile store, and neither
    exposes a teacher console, class roster, school policy, remote wipe or seat issuer."""

    async def scenario() -> None:
        kit = _kit(tmp_path, subjects=("phy",), model_bytes=64 * 1024)
        ids, profiles = [], []
        with no_network():
            for n in (1, 2):
                r, desk = await _core(tmp_path / f"laptop{n}", downloads=False)
                api = Api(r)
                try:
                    install_kit(kit, desk.packs, desk.models, DEV)
                    reply = await api.call(
                        "POST",
                        "/v1/profiles",
                        {
                            "display_name": f"Student {n}",
                            "avatar": "a1",
                            "level": "O",
                            "subjects": ["physics"],
                            "age_band": "13_15",
                            "exam_date": None,
                        },
                    )
                    assert reply.status_code == 200, reply.text
                    profiles.append(
                        {p["profile_id"] for p in (await api.call("GET", "/v1/profiles")).json()["profiles"]}
                    )
                    ids.append(r.runtime.stores.device_id)  # type: ignore[union-attr]
                    routes = [getattr(route, "path", "") for route in _routes(r)]
                    assert not [p for p in routes if any(w in p for w in STAFF_WORDS)], routes
                finally:
                    await stop_core(r)
        assert ids[0] != ids[1], "each install has its own device identity"
        assert profiles[0].isdisjoint(profiles[1]), "each install has its own profiles"

    run(scenario())


def _routes(r: Running) -> list[Any]:
    app = r.server.config.app if r.server is not None else None  # type: ignore[union-attr]
    while app is not None and not hasattr(app, "routes"):
        app = getattr(app, "app", None)
    return list(getattr(app, "routes", []))


def plt23_low_disk_behaviour(tmp_path: Path) -> None:
    """Core half: with free disk at the threshold, a new download is refused with `storage_full` and the size needed,
    while a practice session still starts and answers (the shell's half pauses running downloads, in Rust)."""

    async def scenario() -> None:
        threshold = int(Settings().download_pause_free_mb * 1024 * 1024)
        r, desk = await _core(tmp_path, free=threshold)
        try:
            _offer(tmp_path, desk)
            reply = await r.post("/v1/models/mp.synth.8b.q4_k_m.low/download")
            assert reply.status_code == 507 and code(reply) == "storage_full"
            assert reply.json()["error"]["details"]["free_bytes"] == threshold
            session = await r.session()
            assert session.startswith("ses_")
            assert (await r.get(f"/v1/sessions/{session}/snapshot")).status_code == 200
        finally:
            await stop_core(r)

    run(scenario())
