"""Native policy exceptions require the exact reviewed platform, binary and licence inventory."""

import shutil
import tomllib

from jana_tools import REPO_ROOT
from jana_tools.study_licences import audit, native_component, record
from jana_tools.supply_chain import Component, _site_packages, licence_errors


def test_native_review_hashes_and_scoped_policy_exception(tmp_path):
    site = _site_packages(REPO_ROOT)
    assert not audit(site)
    native = native_component()
    component = Component("generic", native["name"], native["version"], native["licence"])
    assert not licence_errors([component], set())
    assert licence_errors([Component("generic", native["name"], "unreviewed", native["licence"])], set())
    assert licence_errors([Component("pypi", "other", "1", "FTL")], set())
    assert site is not None
    target = tmp_path / "site"
    shutil.copytree(site / "pypdfium2-5.13.0.dist-info", target / "pypdfium2-5.13.0.dist-info")
    shutil.copytree(site / "pypdfium2_raw", target / "pypdfium2_raw")
    assert not audit(target)
    binary = target / "pypdfium2_raw/libpdfium.dylib"
    binary.write_bytes(b"changed binary")
    assert any("binary differs" in e for e in audit(target))
    (target / "pypdfium2-5.13.0.dist-info/licenses/new.txt").write_text("unreviewed library")
    assert any("inventory differs" in e for e in audit(target))


def test_all_supported_wheel_audits_name_lockfile_hashed_downloads():
    reviewed = record()
    platforms = reviewed["platforms"]
    assert {p["platform"] for p in platforms} == {"macos-arm64", "macos-x86_64", "linux-x86_64", "windows-x86_64"}
    package = next(p for p in tomllib.loads((REPO_ROOT / "uv.lock").read_text())["package"] if p["name"] == "pypdfium2")
    locked = {w["url"]: w["hash"].removeprefix("sha256:") for w in package["wheels"]}
    licence_texts = platforms[0]["normalised_licence_sha256"]
    for platform in platforms:
        assert locked[platform["wheel_url"]] == platform["wheel_sha256"]
        assert platform["normalised_licence_sha256"] == licence_texts
