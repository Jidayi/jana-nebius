"""SEC-12, SEC-16, OPS-35, D88: the key ceremony's tool. Every key here is a throwaway made in a temporary folder."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from agent_core.config.trust import ANCHORS, Purpose, TrustStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from signing_service.ceremony import DRY_RUN_PREFIX, RECORD, REVOCATION, CeremonyRefused, adopt, dry_run, issue
from signing_service.hierarchy import CommandSigner, public_b64

NOT_BEFORE = "2026-11-02T00:00:00.000Z"


def _key(folder: Path, name: str) -> tuple[str, CommandSigner]:
    key = Ed25519PrivateKey.generate()
    pem = folder / f"{name}.pem"
    pem.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    return public_b64(key), CommandSigner((sys.executable, "-m", "signing_service.ceremony", "sign-with-key", str(pem)))


def _intermediates(folder: Path, prefix: str) -> list[str]:
    return [f"{p.value}={prefix}{p.value}={_key(folder, p.value)[0]}" for p in Purpose]


def test_sec12_ceremony_dry_run_rehearses_every_step(tmp_path: Path) -> None:
    before = hashlib.sha256(ANCHORS.read_bytes()).hexdigest()
    said: list[str] = []
    folder = dry_run(tmp_path / "dry", say=said.append)
    assert hashlib.sha256(ANCHORS.read_bytes()).hexdigest() == before  # the repository's anchors never change
    record = json.loads((folder / "ceremony" / RECORD).read_text())
    assert record["dry_run"] is True and [r["root"] for r in record["roots"]] == ["release"]
    assert sorted(c["purpose"] for c in record["certificates"]) == sorted(p.value for p in Purpose)
    assert json.loads((folder / "ceremony" / REVOCATION).read_text())["signature"]["key_id"] == f"{DRY_RUN_PREFIX}root"
    adopted = TrustStore.from_document(json.loads((folder / "trust_anchors.json").read_text()))
    assert "key_root_test" in adopted.roots and f"{DRY_RUN_PREFIX}root" in adopted.roots  # test hierarchy kept
    assert any("refused at signing (D88)" in line for line in said)
    assert any("sign-speech-pack" in line for line in said) and any("anchors --write" in line for line in said)
    # A dry run's record never goes into the repository's anchors.
    with pytest.raises(CeremonyRefused, match="never go into the repository"):
        adopt(folder / "ceremony" / RECORD)


def test_sec12_ceremony_refuses_a_root_command_that_is_not_the_root(tmp_path: Path) -> None:
    root_public, _ = _key(tmp_path, "root")
    _, other = _key(tmp_path, "impostor")
    with pytest.raises(CeremonyRefused, match="does not verify"):
        issue(tmp_path / "out", root_key_id="key_root_release_2026", root_public_key=root_public, root_sign=other,
              intermediates=_intermediates(tmp_path, "key_"), not_before=NOT_BEFORE)  # fmt: skip
    assert not (tmp_path / "out").exists()


def test_sec12_ceremony_needs_every_purpose_and_new_real_key_ids(tmp_path: Path) -> None:
    root_public, root_sign = _key(tmp_path, "root")
    every = _intermediates(tmp_path, "key_")
    cases = {
        "no intermediate for licence": every[:-1],
        "test hierarchy id": [*every[:-1], every[-1].replace("=key_licence=", "=key_dev_licence=")],
        "only a dry run": [*every[:-1], every[-1].replace("=key_licence=", f"={DRY_RUN_PREFIX}licence=")],
    }
    for reason, intermediates in cases.items():
        with pytest.raises(CeremonyRefused, match=reason):
            issue(tmp_path / "out", root_key_id="key_root_release_2026", root_public_key=root_public,
                  root_sign=root_sign, intermediates=intermediates, not_before=NOT_BEFORE)  # fmt: skip
    with pytest.raises(CeremonyRefused, match="release or staging root"):
        issue(tmp_path / "out", root_key_id="key_root_release_2026", root_public_key=root_public, root_sign=root_sign,
              intermediates=every, not_before=NOT_BEFORE, root="test")  # fmt: skip


def test_sec12_adopt_keeps_what_is_there_and_refuses_reused_ids(tmp_path: Path) -> None:
    root_public, root_sign = _key(tmp_path, "root")
    every = _intermediates(tmp_path, "key_")
    sums = issue(tmp_path / "out", root_key_id="key_root_release_2026", root_public_key=root_public,
                 root_sign=root_sign, intermediates=every, not_before=NOT_BEFORE)  # fmt: skip
    assert set(sums) == {RECORD, REVOCATION}
    anchors = tmp_path / "trust_anchors.json"
    anchors.write_text(ANCHORS.read_text())
    store = adopt(tmp_path / "out" / RECORD, anchors)
    assert set(store.roots) == {"key_root_release_2026"} and len(store.certificates) == len(Purpose)
    assert "key_root_test" in TrustStore.from_document(json.loads(anchors.read_text())).roots
    with pytest.raises(CeremonyRefused, match="already in the anchors"):
        adopt(tmp_path / "out" / RECORD, anchors)
