"""SEC-20: provider keys live only in the gateway's secret source, never in the repository, its history, a built
artefact, a log, a repr or an error."""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from cloud_gateway.config import load_config
from cloud_gateway.custody import (
    ChainedSecrets,
    DevEnvironmentSecrets,
    KeychainSecrets,
    MountedSecretFiles,
    Secret,
    secret_source,
)
from cloud_gateway.secret_scan import scan_artefact, scan_bytes, scan_history, scan_tracked
from gateway_stubs import FAKE_KEYS, Device, FakeSecrets, Output, gateway_config, harness

REPO = Path(__file__).resolve().parents[3]
PACKAGES = ("jana-cloud-gateway", "jana-agent-core")


def _canaries() -> list[str]:
    """Key-shaped values made at run time, so no key pattern is ever written in this file."""
    digits = "".join(secrets.choice("0123456789") for _ in range(35))
    return ["AI" + "za" + digits, "s" + "k-" + digits + "12345", "x-goog-api-key: " + digits]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=scanner",
            "-c",
            "user.email=scanner@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _build(package: str, out: Path) -> Path:
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv, "uv is needed to build the release artefacts"
    subprocess.run(
        [uv, "build", "--package", package, "--wheel", "--out-dir", str(out)], cwd=REPO, check=True, capture_output=True
    )
    return next(out.glob(package.replace("-", "_") + "-*.whl"))


def sec20_no_provider_keys_in_artefacts(tmp_path: Path) -> None:
    # The scanner catches a seeded key in a working tree, in history after the file is deleted, and in a wheel.
    seeded = tmp_path / "seeded"
    seeded.mkdir()
    _git(seeded, "init", "-q")
    for n, canary in enumerate(_canaries()):
        (seeded / "settings.py").write_text(f"VALUE = '{canary}'\n")
        _git(seeded, "add", "settings.py")
        _git(seeded, "commit", "-q", "-m", f"seed {n}")
        assert {f.pattern for f in scan_tracked(seeded)}, canary[:6]
    (seeded / "settings.py").unlink()
    _git(seeded, "commit", "-q", "-am", "remove")
    assert scan_tracked(seeded) == []
    caught = {f.pattern for f in scan_history(seeded)}
    assert caught == {"google_api_key", "openai_key", "goog_api_key_header"}
    assert all(c[6:20] not in str(f) for c in _canaries() for f in scan_history(seeded))  # findings are masked

    # The repository (tracked files and history) and every release artefact the gateway and core produce.
    assert scan_tracked(REPO) == []
    assert scan_history(REPO) == []
    wheels = tmp_path / "wheels"
    for package in PACKAGES:
        wheel = _build(package, wheels)
        assert scan_artefact(wheel) == [], package
        doctored = tmp_path / ("doctored-" + wheel.name)
        shutil.copy2(wheel, doctored)
        with zipfile.ZipFile(doctored, "a") as archive:
            archive.writestr("leak.txt", _canaries()[0])
        assert [f.pattern for f in scan_artefact(doctored)] == ["google_api_key"]


def test_fixture_values_are_not_findings() -> None:
    assert scan_bytes(b"key = 's" + b"k-canary0000000000secretkey'", "x") == []
    assert scan_bytes(b"s" + b"k-ant-" + b"api03-" + b"A" * 30, "x")[0].pattern == "anthropic_key"


def test_history_fixture_allowance_is_narrow(tmp_path: Path) -> None:
    """A listed history fixture is passed over in history only, and only that exact value: in a tracked file or an
    artefact it is still a finding, and a key one character different is caught in history too."""
    import hashlib

    from cloud_gateway.secret_scan import HISTORY_FIXTURES

    listed = b"s" + b"k-seededsecret" + b"value123"  # built here so this file never carries it whole
    assert hashlib.sha256(listed).hexdigest() in HISTORY_FIXTURES and all(HISTORY_FIXTURES.values())
    assert [f.pattern for f in scan_bytes(listed, "x")] == ["openai_key"]
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for n, value in enumerate((listed, listed[:-1] + b"4")):
        (repo / "settings.py").write_bytes(b"VALUE = '" + value + b"'\n")
        _git(repo, "add", "settings.py")
        _git(repo, "commit", "-q", "-m", f"seed {n}")
    assert [f.pattern for f in scan_tracked(repo)] == ["openai_key"]  # the near miss, still tracked
    (repo / "settings.py").write_bytes(b"VALUE = '" + listed + b"'\n")
    _git(repo, "commit", "-q", "-am", "back")
    assert [f.pattern for f in scan_tracked(repo)] == ["openai_key"], "a listed value in a tracked file is a finding"
    assert [f.pattern for f in scan_history(repo)] == ["openai_key", "openai_key"], "only the near miss, as + and -"


def test_secret_never_shows_its_value() -> None:
    secret = Secret("value-that-must-not-print")
    for shown in (repr(secret), str(secret), f"{secret}", f"{secret!r}", repr({"k": secret})):
        assert "value-that" not in shown
    assert secret.reveal() == "value-that-must-not-print"
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(secret)


def test_environment_keys_only_in_dev(tmp_path: Path) -> None:
    environ = {"JANA_DEV_GEMINI_API_KEY": "dev-own-key"}
    none = KeychainSecrets(system="Plan9")
    for environment in ("staging", "pilot", "production"):
        source = secret_source(load_config(None, environment=environment), environ, none)
        assert source.get("gemini_api_key") is None
    dev = secret_source(load_config(None, environment="dev"), environ, none)
    found = dev.get("gemini_api_key")
    assert found is not None and found.reveal() == "dev-own-key"
    assert DevEnvironmentSecrets({}).get("gemini_api_key") is None


def test_mounted_secret_files(tmp_path: Path) -> None:
    mount = tmp_path / "mount"
    mount.mkdir()
    (mount / "gemini_api_key").write_text("mounted-key\n")
    source = secret_source(load_config(None, environment="production", secrets_dir=mount))
    found = source.get("gemini_api_key")
    assert found is not None and found.reveal() == "mounted-key"
    assert source.get("../gemini_api_key") is None and source.get("missing") is None
    with pytest.raises(ValueError, match="git working tree"):
        MountedSecretFiles(REPO / "services")


def test_keychain_lookup_commands() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "keychain-key\n", "")

    mac = KeychainSecrets(system="Darwin", run=run).get("gemini_api_key")
    linux = KeychainSecrets(system="Linux", run=run).get("gemini_api_key")
    assert mac is not None and linux is not None and mac.reveal() == "keychain-key"
    assert calls == [
        ["security", "find-generic-password", "-s", "jana.cloud-gateway", "-a", "gemini_api_key", "-w"],
        ["secret-tool", "lookup", "service", "jana.cloud-gateway", "account", "gemini_api_key"],
    ]
    missing = KeychainSecrets(system="Darwin", run=lambda argv: subprocess.CompletedProcess(argv, 44, "", "nope"))
    assert ChainedSecrets((missing,)).get("gemini_api_key") is None


def test_keys_stay_out_of_logs_errors_and_storage(tmp_path: Path) -> None:
    storage, log = tmp_path / "storage", tmp_path / "logs" / "gateway.log"

    async def main() -> list[str]:
        h = harness(gateway_config(storage, log_path=log), secrets=FakeSecrets())
        device = Device()
        await device.login(h.client)
        texts = []
        for out in (
            Output(text="fine"),
            Output(error=(403, {"error": {"message": "bad key"}})),
            Output(error=(400, {"error": {"message": "API key not valid."}})),
        ):
            h.stubs["gemini"].say(out)
            reply = await device.chat(
                h.client, {"model": "primary/fast-model", "messages": [{"role": "user", "content": "hi"}]}
            )
            texts.append(reply.text)
        assert h.stubs["gemini"].seen[0].headers["x-goog-api-key"] == FAKE_KEYS["gemini_api_key"]
        return texts

    texts = asyncio.run(main())
    written = [p.read_bytes() for p in [*storage.rglob("*"), log] if p.is_file()]
    for key in FAKE_KEYS.values():
        assert all(key not in t for t in texts)
        assert all(key.encode() not in data for data in written)
