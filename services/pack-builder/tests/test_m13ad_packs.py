"""M13.a and M13.d: pack versions and diffs, size budgets, the signing key hierarchy and pack verification hardening
(CUR-09, CUR-10, CUR-34, SEC-12, SEC-13). Packs are built from the S1 physics source and then changed by hand; every
key is generated in the test or derived from the published test-root phrases, and every record is test data."""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.config.trust import ARTEFACT_PURPOSE, Purpose, RootKey, SignatureRefused, TrustStore, bundled_trust
from agent_core.store import pack_diff
from agent_core.store.model_packs import ModelManifestError, verify_manifest
from agent_core.store.pack_channels import ChannelError, from_kit, resume_download
from agent_core.store.pack_index import PackIndex
from agent_core.store.pack_store import PackStore, file_sha256
from agent_core.store.packs import (
    DAMAGED_MESSAGE_KEY,
    TABLES,
    PackRejectedError,
    PackShelf,
    open_pack,
    read_pack,
    table_sha256,
    verify,
    write_pack,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pack_builder import versioning
from pack_builder.build import build
from signing_service.hierarchy import (
    DEV_NOT_AFTER,
    DEV_NOT_BEFORE,
    Signer,
    SigningRefused,
    anchors_text,
    dev_signer,
    dev_trust,
    issue_certificate,
    public_b64,
    root_record,
)
from signing_service.keys import DEV_KEY_IDS, dev_key
from signing_service.service import sign_kit
from test_m8_authoring import repo as authoring_repo  # noqa: F401 - the authoring repository fixture

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "content" / "curriculum" / "phy" / "o"
SIGNED_AT = "2026-10-12T09:00:00.000Z"
DEV = Environment.DEV

Tables = dict[str, list[dict[str, Any]]]


@pytest.fixture(scope="module")
def release(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Tables]:
    """The physics pack built and signed as the signing service signs it, as release 0.1.0 whatever the source's own
    version, so the update tests always have a 0.1.0 to move on from."""
    out = tmp_path_factory.mktemp("built")
    built = build(SOURCE, out, sign_with=lambda m: dev_signer().sign("content_pack", m, now=SIGNED_AT))
    manifest, tables = read_pack(built.pack_path)
    if manifest["version"] == "0.1.0":
        return manifest, tables
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    return _signed(unsigned, tables, version="0.1.0"), tables


def _signed(manifest: dict[str, Any], tables: Tables, **fields: Any) -> dict[str, Any]:
    unsigned = {**manifest, **fields,
                "tables": [{"name": t, "sha256": table_sha256(t, tables[t]), "rows": len(tables[t])}
                           for t in TABLES if t in tables]}  # fmt: skip
    return dev_signer().sign("content_pack", unsigned, now=SIGNED_AT)


def _write(path: Path, manifest: dict[str, Any], tables: Tables) -> Path:
    write_pack(path, manifest, tables)
    return path


def _next_version(manifest: dict[str, Any], tables: Tables, version: str = "0.2.0") -> tuple[dict[str, Any], Tables]:
    """A minor release: one item withdrawn, one misconception corrected, one item added."""
    tables = copy.deepcopy(tables)
    items = sorted(tables["items"], key=lambda r: r["id"])
    withdrawn, template = items[0], items[1]
    tables["items"] = [r for r in tables["items"] if r["id"] != withdrawn["id"]]
    added = copy.deepcopy(template)
    added["id"] = template["id"].rsplit(".", 1)[0] + ".9001"
    tables["items"].append(added)
    corrected = sorted(tables["misconceptions"], key=lambda r: r["id"])[0]
    corrected["description"] = corrected["description"].rstrip(".") + " (corrected)."
    return _signed(manifest, tables, version=version), tables


def _diff(old: tuple[dict[str, Any], Tables], new: tuple[dict[str, Any], Tables],
          signer: Signer | None = None) -> dict[str, Any]:  # fmt: skip
    unsigned = pack_diff.make_diff(old[0], old[1], new[0], new[1], SIGNED_AT)
    return (signer or dev_signer()).sign(pack_diff.ARTEFACT, unsigned, now=SIGNED_AT)


def _store_with(folder: Path, pack: Path, **kw: Any) -> PackStore:
    store = PackStore(folder, DEV, **kw)
    store.install(pack)
    return store


def _foreign_sign(document: dict[str, Any], key: Ed25519PrivateKey, key_id: str) -> dict[str, Any]:
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    body = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {**unsigned, "signature": {"alg": "ed25519", "key_id": key_id, "value": base64.b64encode(key.sign(body))
                                      .decode()}}  # fmt: skip


# --- SEC-12 ---------------------------------------------------------------------------------------------------------


def sec12_key_purpose_enforced(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    trust = bundled_trust()
    # The bundled anchors are exactly the test hierarchy (and no private key material).
    assert json.loads(anchors_text()) == {**json.loads((REPO / "services" / "agent-core" / "agent_core" / "config" /
                                                        "trust_anchors.json").read_text())}  # fmt: skip
    assert "PRIVATE" not in anchors_text() and all("private" not in k for k in json.loads(anchors_text()))
    # Every artefact type verifies with its own intermediate, chained to the bundled root, and with no other.
    for artefact, purpose in ARTEFACT_PURPOSE.items():
        document = {"artefact": artefact, "created_at": SIGNED_AT}
        trust.verify(artefact, dev_signer(purpose).sign(artefact, document, now=SIGNED_AT), DEV, signed_at=SIGNED_AT)
        for other in Purpose:
            if other is purpose:
                continue
            wrong = _foreign_sign(document, dev_key(other), DEV_KEY_IDS[other])
            with pytest.raises(SignatureRefused, match="needs a"):
                trust.verify(artefact, wrong, DEV)
            with pytest.raises(SigningRefused):  # the signing side refuses too
                dev_signer(other).sign(artefact, document, now=SIGNED_AT)
    # The real verification paths refuse the wrong intermediate: a pack signed by the model key, a model manifest
    # signed by the content key, a diff signed by the agent-bundle key, a kit listing signed by the updater key.
    manifest, tables = release
    as_model = _foreign_sign(manifest, dev_key(Purpose.MODEL), DEV_KEY_IDS[Purpose.MODEL])
    with pytest.raises(PackRejectedError, match="model key"):
        verify(_write(tmp_path / "model-signed.pack", as_model, tables), DEV)
    models = {"pack_id": "models.synthetic", "version": "0.1.0", "synthetic": True, "models": []}
    verify_manifest(dev_signer(Purpose.MODEL).sign("model_manifest", models, now=SIGNED_AT), DEV)
    with pytest.raises(ModelManifestError, match="content key"):
        verify_manifest(_foreign_sign(models, dev_key(Purpose.CONTENT), DEV_KEY_IDS[Purpose.CONTENT]), DEV)
    store = _store_with(tmp_path / "store", _write(tmp_path / "v1.pack", manifest, tables))
    new = _next_version(manifest, tables)
    with pytest.raises(PackRejectedError, match="agent_bundle key"):
        store.apply_diff(_foreign_sign(_diff(release, new), dev_key(Purpose.AGENT_BUNDLE),
                                       DEV_KEY_IDS[Purpose.AGENT_BUNDLE]))  # fmt: skip
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "update.diff.json").write_bytes(pack_diff.diff_bytes(_diff(release, new)))
    listing = sign_kit(kit, [("update.diff.json", "content_diff")])
    (kit / "kit.json").write_text(json.dumps(_foreign_sign(listing, dev_key(Purpose.UPDATER),
                                                          DEV_KEY_IDS[Purpose.UPDATER])))  # fmt: skip
    with pytest.raises(ChannelError, match="updater key"):
        from_kit(kit, "update.diff.json", tmp_path / "in" / "update.diff.json", DEV)
    # A certificate from a root the app does not bundle, an edited certificate, and the test root outside dev.
    rogue_root = Ed25519PrivateKey.generate()
    rogue = issue_certificate(RootKey("key_root_rogue", public_b64(rogue_root), "release", DEV_NOT_BEFORE,
                                      DEV_NOT_AFTER), rogue_root.sign, "key_rogue_content", Purpose.CONTENT,
                              public_b64(dev_key()), DEV_NOT_BEFORE, "2027-01-01T00:00:00.000Z")  # fmt: skip
    with_rogue = TrustStore(trust.roots, {**trust.certificates, rogue.key_id: rogue})
    with pytest.raises(SignatureRefused, match="does not chain"):
        with_rogue.key_for(rogue.key_id, "content_pack", DEV)
    model_cert = trust.certificates[DEV_KEY_IDS[Purpose.MODEL]]
    edited = TrustStore(trust.roots, {**trust.certificates, model_cert.key_id: type(model_cert)(
        model_cert.key_id, Purpose.CONTENT, model_cert.public_key, model_cert.root_key_id, model_cert.not_before,
        model_cert.not_after, model_cert.signature)})  # fmt: skip
    with pytest.raises(SignatureRefused, match="does not verify"):
        edited.key_for(model_cert.key_id, "content_pack", DEV)
    for environment in (Environment.PILOT, Environment.PRODUCTION):
        with pytest.raises(PackRejectedError, match="not trusted"):
            verify(tmp_path / "v1.pack", environment)
    # A release hierarchy made in the test: the production build accepts it; rotation limits are enforced at issue;
    # a key signs only while its certificate is valid, and an artefact made outside that window is refused.
    root_key, content_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    root = root_record("key_root_release_test", public_b64(root_key), "release", "2026-01-01T00:00:00.000Z",
                       "2031-01-01T00:00:00.000Z")  # fmt: skip
    with pytest.raises(SigningRefused, match="at most 5 years"):
        root_record("key_root_long", public_b64(root_key), "release", "2026-01-01T00:00:00.000Z",
                    "2032-01-01T00:00:00.000Z")  # fmt: skip
    with pytest.raises(SigningRefused, match="at most 1 year"):
        issue_certificate(root, root_key.sign, "key_content_long", Purpose.CONTENT, public_b64(content_key),
                          "2026-01-01T00:00:00.000Z", "2027-06-01T00:00:00.000Z")  # fmt: skip
    licence = issue_certificate(root, root_key.sign, "key_licence_2026", Purpose.LICENCE, public_b64(content_key),
                                "2026-01-01T00:00:00.000Z", "2028-01-01T00:00:00.000Z")  # fmt: skip
    assert licence.purpose is Purpose.LICENCE, "a licence key may live two years"
    certificate = issue_certificate(root, root_key.sign, "key_content_2026", Purpose.CONTENT,
                                    public_b64(content_key), "2026-01-01T00:00:00.000Z",
                                    "2027-01-01T00:00:00.000Z")  # fmt: skip
    production = TrustStore({root.key_id: root}, {certificate.key_id: certificate})
    signer = Signer(certificate, content_key.sign)
    signed = signer.sign("content_pack", {**manifest, "created_at": SIGNED_AT}, now=SIGNED_AT)
    verify(_write(tmp_path / "release.pack", signed, tables), Environment.PRODUCTION, production)
    with pytest.raises(SigningRefused, match="not valid"):
        signer.sign("content_pack", manifest, now="2027-03-01T00:00:00.000Z")
    late = signer.sign("content_pack", {**manifest, "created_at": "2027-03-01T00:00:00.000Z"}, now=SIGNED_AT)
    with pytest.raises(PackRejectedError, match="was not valid"):
        verify(_write(tmp_path / "late.pack", late, tables), Environment.PRODUCTION, production)
    with pytest.raises(PackRejectedError, match="revoked"):
        verify(tmp_path / "release.pack", Environment.PRODUCTION, production.with_revoked([certificate.key_id]))
    assert dev_trust().document() == {k: v for k, v in json.loads(anchors_text()).items() if k != "$comment"}


# --- SEC-13 ---------------------------------------------------------------------------------------------------------


def _flip_table_byte(path: Path, table: str) -> None:
    os.chmod(path, 0o644)
    conn = sqlite3.connect(path)
    row_id, record = conn.execute(f"SELECT id, record FROM {table} ORDER BY id LIMIT 1").fetchone()  # noqa: S608
    index = record.index('":"') + 3
    flipped = record[:index] + ("B" if record[index] != "B" else "C") + record[index + 1 :]
    conn.execute(f"UPDATE {table} SET record = ? WHERE id = ?", (flipped, row_id))  # noqa: S608
    conn.commit()
    conn.close()


def sec13_tampered_pack_refused(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    manifest, tables = release
    maths = _signed(manifest, tables, pack_id="pack.mth.o", subject="mth", title="Mathematics (O level)")
    folder = tmp_path / "packs"
    store = _store_with(folder, _write(tmp_path / "phy.pack", manifest, tables))
    store.install(_write(tmp_path / "mth.pack", maths, tables))
    assert os.stat(store.active_path("pack.phy.o")).st_mode & 0o222 == 0, "installed packs are read-only"
    for table in [t["name"] for t in manifest["tables"] if t["rows"]]:
        work = tmp_path / table
        shutil.copytree(folder, work)
        _flip_table_byte(work / "pack.phy.o.pack", table)
        restarted = PackStore(work, DEV)  # the next load, after a restart
        with pytest.raises(PackRejectedError) as refused:
            restarted.load("pack.phy.o")
        assert refused.value.message_key == DAMAGED_MESSAGE_KEY
        loaded, failed = restarted.load_all()
        assert list(loaded) == ["pack.mth.o"] and [p for p, _ in failed] == ["pack.phy.o"], "other subjects work"
        index = PackIndex.load(sorted(work.glob("*.pack")), DEV)
        assert [name for name, _ in index.rejected] == ["pack.phy.o.pack"], table
    # Swapping in another validly signed file (an older or different version) is caught by the installed record.
    swapped = tmp_path / "swapped"
    shutil.copytree(folder, swapped)
    os.chmod(swapped / "pack.phy.o.pack", 0o644)
    other = _signed(manifest, tables, title="Physics (O level), another build")
    _write(swapped / "pack.phy.o.pack", other, tables)
    verify(swapped / "pack.phy.o.pack", DEV)  # it verifies on its own...
    with pytest.raises(PackRejectedError, match="changed since it was verified"):
        PackStore(swapped, DEV).load("pack.phy.o")  # ...but it is not the pack that was installed
    assert PackStore(folder, DEV).load_all()[1] == [], "the untouched installation still loads"


def sec13_pack_sqlite_hardening(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    manifest, tables = release
    good = _write(tmp_path / "good.pack", manifest, tables)
    hostile = {
        "trigger": "CREATE TRIGGER t AFTER INSERT ON items BEGIN SELECT 1; END",
        "view with function calls": "CREATE VIEW v AS SELECT upper(record), random() FROM items",
        "extension load": "CREATE VIEW x AS SELECT load_extension('payload')",
        "extra table": "CREATE TABLE notes (id TEXT PRIMARY KEY, body TEXT)",
        "index": "CREATE INDEX i ON items (record)",
    }
    for name, sql in hostile.items():
        path = tmp_path / f"{name.replace(' ', '_')}.pack"
        shutil.copy(good, path)
        conn = sqlite3.connect(path)
        conn.execute(sql)
        conn.commit()
        conn.close()
        assert read_pack(good)[1] == tables  # the signed rows are untouched: only the schema differs
        shelf = PackShelf(DEV)
        assert not shelf.install(path), name
        assert "not written by the pack builder" in shelf.rejected[-1][1] or "loads an extension" in \
            shelf.rejected[-1][1], name  # fmt: skip
        with pytest.raises(PackRejectedError):
            PackStore(tmp_path / f"store-{name.replace(' ', '_')}", DEV).install(path)
    shelf = PackShelf(DEV)
    shelf.install(tmp_path / "extension_load.pack")
    assert "loads an extension" in shelf.rejected[-1][1]
    # Packs are opened read-only, with extension loading off and untrusted schema functions.
    conn = open_pack(good)
    try:
        assert conn.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO items VALUES ('x', '{}')")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT load_extension('payload')")
    finally:
        conn.close()
    # Pack data is data: a record that breaks the content contract is refused at install even when it is signed.
    bad_tables = copy.deepcopy(tables)
    bad_tables["lessons"][0]["blocks"][0]["kind"] = "script"
    bad = _write(tmp_path / "contract.pack", _signed(manifest, bad_tables), bad_tables)
    verify(bad, DEV)  # signature and hashes hold...
    assert not PackShelf(DEV).install(bad)  # ...but the record is not a valid lesson block


# --- CUR-09 ---------------------------------------------------------------------------------------------------------


class PowerLoss(Exception):
    """Stands for the power going off at a fault point."""


def _at(point: str) -> Callable[[str], None]:
    def fault(reached: str) -> None:
        if reached == point:
            raise PowerLoss(point)

    return fault


def _state(folder: Path, pack_id: str) -> tuple[str, dict[str, str]]:
    store = PackStore(folder, DEV)  # restart: recovery runs
    path = store.load(pack_id)
    manifest, tables = read_pack(path)
    assert store.installed(pack_id)["version"] == manifest["version"]  # type: ignore[index]
    return manifest["version"], {t: table_sha256(t, rows) for t, rows in tables.items()}


def cur09_atomic_diff_apply(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    old = release
    new = _next_version(*old)
    v1 = _write(tmp_path / "v1.pack", *old)
    diff = _diff(old, new)
    old_hashes = {t["name"]: t["sha256"] for t in old[0]["tables"]}
    new_hashes = {t["name"]: t["sha256"] for t in new[0]["tables"]}
    assert old_hashes != new_hashes
    outcomes = {}
    for point in ("rows", "staged", "pending", "previous", "swap", "commit"):
        folder = tmp_path / point
        _store_with(folder, v1)
        with pytest.raises(PowerLoss):
            PackStore(folder, DEV, fault=_at(point)).apply_diff(diff)
        version, hashes = _state(folder, "pack.phy.o")
        assert hashes in (old_hashes, new_hashes), f"a mix of versions after power loss at {point}"
        assert (version, hashes) in (("0.1.0", old_hashes), ("0.2.0", new_hashes)), point
        assert not any((folder / ".staging").iterdir()), "nothing half-made is left"
        outcomes[point] = version
        if version == "0.1.0":  # the update can simply be applied again
            PackStore(folder, DEV).apply_diff(diff)
            assert _state(folder, "pack.phy.o") == ("0.2.0", new_hashes)
    assert outcomes["rows"] == outcomes["staged"] == outcomes["pending"] == "0.1.0"
    assert outcomes["swap"] == outcomes["commit"] == "0.2.0"
    # A diff that does not apply leaves the installed version active and unchanged.
    folder = tmp_path / "refused"
    store = _store_with(folder, v1)
    before = file_sha256(store.active_path("pack.phy.o"))
    wrong_rows = copy.deepcopy(diff)
    wrong_rows["changes"][0]["upsert"] = wrong_rows["changes"][0]["upsert"][:-1] or [{"id": "x"}]
    for bad in (_foreign_sign(diff, Ed25519PrivateKey.generate(), DEV_KEY_ID_CONTENT),
                dev_signer().sign(pack_diff.ARTEFACT, wrong_rows, now=SIGNED_AT),
                dev_signer().sign(pack_diff.ARTEFACT, {**diff, "from_version": "0.0.9"}, now=SIGNED_AT)):  # fmt: skip
        with pytest.raises(PackRejectedError):
            store.apply_diff(bad)
        assert file_sha256(store.active_path("pack.phy.o")) == before
        assert _state(folder, "pack.phy.o") == ("0.1.0", old_hashes)
    # The previous version is kept until the new one has loaded once (PLT-13).
    store.apply_diff(diff)
    assert (folder / "previous" / "pack.phy.o-0.1.0.pack").is_file()
    store.load("pack.phy.o")
    assert not (folder / "previous" / "pack.phy.o-0.1.0.pack").exists()
    # A lower version is never installed over a higher one.
    with pytest.raises(PackRejectedError, match="not newer"):
        store.install(v1)


DEV_KEY_ID_CONTENT = DEV_KEY_IDS[Purpose.CONTENT]


def cur09_two_channels_equal(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    old = release
    new = _next_version(*old)
    v1 = _write(tmp_path / "v1.pack", *old)
    published = tmp_path / "cdn" / "pack.phy.o-0.2.0.diff.json"
    published.parent.mkdir()
    published.write_bytes(pack_diff.diff_bytes(_diff(old, new)))
    data = published.read_bytes()
    # Download: chunked range reads; the connection drops part way, and the next attempt resumes from the .part file.
    dropped = {"after": len(data) // 3}
    requests = []

    def read(offset: int, length: int) -> bytes:
        requests.append(offset)
        if dropped["after"] is not None and offset >= dropped["after"]:
            dropped["after"] = None
            return b""
        return data[offset : offset + length]

    downloaded = tmp_path / "downloads" / "update.diff.json"
    chunk = max(1, len(data) // 10)
    assert resume_download(read, len(data), downloaded, chunk) is None, "interrupted"
    partial = (tmp_path / "downloads" / "update.diff.json.part").stat().st_size
    assert 0 < partial < len(data)
    assert resume_download(read, len(data), downloaded, chunk, sha256=file_sha256(published)) == downloaded
    assert requests[requests.index(partial, 1)] == partial, "the second attempt resumed where the first stopped"
    # USB kit: the same file in a kit folder with a signed kit.json.
    kit = tmp_path / "usb"
    kit.mkdir()
    shutil.copy(published, kit / "pack.phy.o-0.2.0.diff.json")
    sign_kit(kit, [("pack.phy.o-0.2.0.diff.json", "content_diff")])
    imported = from_kit(kit, "pack.phy.o-0.2.0.diff.json", tmp_path / "imports" / "update.diff.json", DEV)
    assert downloaded.read_bytes() == imported.read_bytes() == data
    # The same diff installs identically from either channel.
    results = []
    for name, path in (("download", downloaded), ("usb", imported)):
        store = _store_with(tmp_path / name, v1)
        store.apply_diff(pack_diff.read_diff(path.read_bytes()))
        active = store.load("pack.phy.o")
        results.append((file_sha256(active), read_pack(active)))
    assert results[0] == results[1]
    manifest, tables = results[0][1]
    assert manifest == new[0]
    assert {t: table_sha256(t, rows) for t, rows in tables.items()} == {t["name"]: t["sha256"] for t in
                                                                        new[0]["tables"]}  # fmt: skip
    # A changed kit file, or a kit listing not signed by a content key, is refused before it reaches the store.
    (kit / "pack.phy.o-0.2.0.diff.json").write_bytes(data.replace(b'"0.2.0"', b'"0.2.1"', 1))
    with pytest.raises(ChannelError, match="does not match"):
        from_kit(kit, "pack.phy.o-0.2.0.diff.json", tmp_path / "imports" / "again.json", DEV)


# --- CUR-09, CUR-10, CUR-34 at release ----------------------------------------------------------------------------


def test_cur09_version_bump_follows_the_change(release: tuple[dict[str, Any], Tables]) -> None:
    manifest, tables = release
    minor = _next_version(manifest, tables)[1]
    diff = versioning.semantic_diff(tables, minor)
    assert diff.required_bump() == "minor"
    assert versioning.version_problems(manifest, {**manifest, "version": "0.1.1"}, diff)
    assert not versioning.version_problems(manifest, {**manifest, "version": "0.2.0"}, diff)
    assert versioning.version_problems(manifest, {**manifest, "version": "0.1.0"}, diff), "the version must grow"
    marking = copy.deepcopy(tables)
    item = next(i for i in marking["items"] if i["parts"][0]["answer"]["kind"] == "numeric")
    item["parts"][0]["marks"] += 1
    changed = versioning.semantic_diff(tables, marking)
    assert changed.required_bump() == "major" and item["id"] in changed.marking_changed
    assert versioning.version_problems(manifest, {**manifest, "version": "0.2.0"}, changed)
    wording = copy.deepcopy(tables)
    wording["misconceptions"][0]["description"] += " Reworded."
    assert versioning.semantic_diff(tables, wording).required_bump() == "patch"


def test_cur09_follow_through_is_marking_quantities_are_not(release: tuple[dict[str, Any], Tables]) -> None:
    """A follow-through recipe changes the marks a carried error earns, so adding or changing one needs a major
    version; an item's quantities only let a signature name a misconception in feedback, a patch."""
    manifest, tables = release
    target = next(i for i in tables["items"] if i["parts"][-1]["answer"]["kind"] == "numeric")
    recipe = copy.deepcopy(tables)
    part = next(i for i in recipe["items"] if i["id"] == target["id"])["parts"][-1]
    part["follow_through"] = {"expression": "x * 2", "symbols": {"x": "a"}}
    added = versioning.semantic_diff(tables, recipe)
    assert added.required_bump() == "major" and target["id"] in added.marking_changed
    assert versioning.version_problems(manifest, {**manifest, "version": "0.1.1"}, added)
    changed = copy.deepcopy(recipe)
    next(i for i in changed["items"] if i["id"] == target["id"])["parts"][-1]["follow_through"]["expression"] = "x * 3"
    assert versioning.semantic_diff(recipe, changed).required_bump() == "major"
    given = copy.deepcopy(tables)
    next(i for i in given["items"] if i["id"] == target["id"])["quantities"] = {"d": "1200", "t": "0.2"}
    quantities = versioning.semantic_diff(tables, given)
    assert quantities.required_bump() == "patch" and target["id"] in quantities.changed["items"]
    assert not quantities.marking_changed
    assert not versioning.version_problems(manifest, {**manifest, "version": "0.1.1"}, quantities)


def test_cur10_split_needs_a_migration(release: tuple[dict[str, Any], Tables]) -> None:
    _, tables = release
    split = copy.deepcopy(tables)
    old = next(k for k in split["kcs"] if k["status"] == "active")
    old["status"] = "retired"
    parts = []
    for n in (1, 2):
        part = copy.deepcopy(old)
        part.update(id=f"{old['id']}_part{n}", code=old["code"][:-2] + f"{90 + n}", status="active", version="1.0.0")
        parts.append(part)
    split["kcs"] += parts
    diff = versioning.semantic_diff(tables, split)
    assert old["id"] in diff.kcs_dropped and diff.required_bump() == "major"
    problems = versioning.migration_problems(split, "1.0.0", tables)
    assert any("retired without a KC migration" in p for p in problems)
    row = {"from_kc_id": old["id"], "from_version": "0.1.0", "to_version": "1.0.0",
           "to": [{"kc_id": parts[0]["id"], "weight": 0.6}, {"kc_id": parts[1]["id"], "weight": 0.4}]}  # fmt: skip
    split["kc_migrations"] = [row]
    assert versioning.migration_problems(split, "1.0.0", tables) == []
    assert versioning.semantic_diff(tables, split).kcs_migrated == [old["id"]]
    split["kc_migrations"] = [{**row, "to": [{"kc_id": parts[0]["id"], "weight": 0.6}]}]
    assert any("weights sum" in p for p in versioning.migration_problems(split, "1.0.0", tables))
    split["kc_migrations"] = [{**row, "to_version": "0.2.0"}]
    assert any("major version" in p for p in versioning.migration_problems(split, "1.0.0", tables))


def test_cur34_size_report(release: tuple[dict[str, Any], Tables], tmp_path: Path) -> None:
    manifest, tables = release
    path = _write(tmp_path / "p.pack", manifest, tables)
    report = versioning.size_report(path.stat().st_size, 2048, tables)
    assert report["tables"][0]["name"] == "diagrams", "diagrams are budgeted first"
    assert report["over_budget"] == [] and report["pack_budget_bytes"] == 80 * 1024 * 1024
    tight = Settings(pack_size_budget_mb=1.0, pack_diff_budget_mb=0.1)
    over = versioning.size_report(2 * 1024 * 1024, 1024 * 1024, tables, tight)["over_budget"]
    assert len(over) == 2 and "budget 1 MB" in over[0]


def test_cur09_signing_service_releases_row_diffs(authoring_repo: Any, tmp_path: Path) -> None:  # noqa: F811
    """The signing service refuses a version that does not grow, signs a row-level diff from the previous release
    with a content key, and records the sizes against their budgets (CUR-09, CUR-34)."""
    from signing_service.service import Refused, handle
    from test_m8_authoring import _commit, _ready_to_publish

    repo = authoring_repo
    _ready_to_publish(repo)

    def request(version: str) -> dict[str, Any]:
        text = (repo.pack / "pack.yaml").read_text()
        (repo.pack / "pack.yaml").write_text(re.sub(r"(?m)^version: .*$", f"version: {version}", text))
        commit = _commit(repo, f"release {version}")
        return {"request_id": f"pubreq_{version.replace('.', '_')}", "commit": commit, "pack_id": "pack.phy.o",
                "pack_dir": "content/curriculum/phy/o", "version": version, "channel": "dev",
                "requested_by": {"role_id": repo.ctx("lead").need().rev_id}}  # fmt: skip

    out = repo.root / "out"
    first = handle(request("0.1.0"), repo.root, out, authoring_home=repo.home)
    assert first.diff_path is None and first.record["size"]["over_budget"] == []
    with pytest.raises(Refused, match=r"not greater than the released 0\.1\.0"):
        handle(request("0.1.0"), repo.root, out, authoring_home=repo.home)
    text = (repo.pack / "pack.yaml").read_text()
    (repo.pack / "pack.yaml").write_text(text.replace("title: Physics (O level)", "title: Physics (O level), 2027"))
    second = handle(request("0.1.1"), repo.root, out, authoring_home=repo.home)
    assert second.diff_path is not None and second.record["changes"]["required_bump"] == "patch"
    diff = pack_diff.read_diff(second.diff_path.read_bytes())
    bundled_trust().verify(pack_diff.ARTEFACT, diff, DEV)
    store = _store_with(tmp_path / "device", first.pack_path)
    store.apply_diff(diff)
    assert read_pack(store.load("pack.phy.o")) == read_pack(second.pack_path)
    assert second.record["size"]["diff_bytes"] == second.diff_path.stat().st_size
