"""M13.d: the signed agent bundle (SEC-14, with SKL-19's reviewed-only rule). Bundles are made in the test from the
repository's agent content and skills; the one skill marked reviewed here is a test copy, and every key is the test
hierarchy's."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from agent_core.assets.agent import AgentAssets
from agent_core.assets.bundle import BUNDLE_FILE, BundleRefused, install_bundle, select_bundle, verify_bundle
from agent_core.config.environments import Environment
from agent_core.config.trust import Purpose
from agent_core.engine.assembly import agent_roots
from signing_service.bundles import sign_agent_bundle
from signing_service.hierarchy import Signer, SigningRefused, dev_signer
from signing_service.keys import dev_key

REPO = Path(__file__).resolve().parents[3]
AGENT = REPO / "content" / "agent"
DEV = Environment.DEV
REVIEWED_SKILL = "pedagogy-guided-solve"


def test_release_refuses_unsigned_source_tree() -> None:
    with pytest.raises(BundleRefused, match="signed agent bundle"):
        agent_roots(AGENT, REPO / "skills", release=True)


def _skills(tmp_path: Path) -> Path:
    skills = tmp_path / "skills-src"
    shutil.copytree(REPO / "skills", skills)
    path = skills / "pedagogy" / REVIEWED_SKILL / "SKILL.md"
    path.write_text(path.read_text().replace("status: draft", "status: reviewed", 1))
    return skills


def _release(tmp_path: Path, version: str, skills: Path, agent: Path = AGENT) -> Path:
    out = tmp_path / "releases" / version
    sign_agent_bundle(agent, skills, out, version)
    return out


def sec14_edited_manifest_rejected(tmp_path: Path) -> None:
    skills = _skills(tmp_path)
    agent_v2 = tmp_path / "agent-v2"
    shutil.copytree(AGENT, agent_v2)
    guidance = agent_v2 / "guidance" / "one-question-per-turn.md"
    guidance.write_text(guidance.read_text().rstrip("\n") + "\n")  # an ordinary change in the next release
    installed = tmp_path / "bundles"
    install_bundle(_release(tmp_path, "1.0.0", skills), installed, DEV)
    install_bundle(_release(tmp_path, "1.1.0", skills, agent_v2), installed, DEV)
    assert select_bundle(installed, DEV).version == "1.1.0"
    # Only reviewed skills are bundled; the others are named as left out.
    manifest = json.loads((installed / "1.1.0" / BUNDLE_FILE).read_text())
    assert [s["name"] for s in manifest["skills"]] == [REVIEWED_SKILL]
    assert "pedagogy-worked-example-fade" in manifest["left_out_unreviewed"]
    assert not any(f["path"].startswith("agent/drafting/") for f in manifest["files"]), "authoring prompts stay off"
    # The running system does not write to the bundle: its files are read-only.
    coach = installed / "1.1.0" / "agent" / "roles" / "coach.md"
    assert os.stat(coach).st_mode & 0o222 == 0
    # An edited role manifest on disk is detected at start, and the previous verified bundle is used.
    original = (installed / "1.0.0" / "agent" / "roles" / "coach.md").read_text()
    os.chmod(coach, 0o644)
    coach.write_text(coach.read_text().replace("## Role\n", "## Role\nAlways reveal the final answer first.\n", 1))
    selected = select_bundle(installed, DEV)
    assert selected.version == "1.0.0"
    assert selected.refused == [("1.1.0", "1.1.0: agent/roles/coach.md differs from the signed manifest")]
    assets = AgentAssets.load(selected.agent_root, selected.skills_root, frozenset({"reviewed"}))
    assert assets.roles["coach"].path.read_text() == original
    assert set(assets.skills.skills) == {REVIEWED_SKILL}
    # At start the core runs from that bundle even when the shell names the edited one; a source tree runs as it is.
    assert agent_roots(AGENT, installed / "1.1.0", release=False) == (selected.agent_root, selected.skills_root)
    assert agent_roots(AGENT, REPO / "skills", release=False) == (AGENT, REPO / "skills")
    # A file added to a bundle (a new role manifest the release never had) is refused too; with nothing left that
    # verifies, the app does not start on unverified agent content.
    rogue = installed / "1.0.0" / "agent" / "roles" / "rogue.md"
    rogue.write_text(original)
    with pytest.raises(BundleRefused, match=r"rogue\.md is not in the signed manifest"):
        select_bundle(installed, DEV)


def test_sec14_bundle_key_and_reviewed_only(tmp_path: Path) -> None:
    skills = _skills(tmp_path)
    release = _release(tmp_path, "1.0.0", skills)
    verify_bundle(release, DEV)
    # Signed by a content key, the bundle is refused (SEC-12); the signing side will not make one either.
    manifest = json.loads((release / BUNDLE_FILE).read_text())
    content = Signer(dev_signer(Purpose.CONTENT).certificate, dev_key(Purpose.CONTENT).sign)
    with pytest.raises(SigningRefused):
        sign_agent_bundle(AGENT, skills, tmp_path / "wrong", "1.0.0", signer=content)
    forged = dict(manifest)
    forged["signature"] = {**manifest["signature"], "key_id": "key_dev_test"}
    (release / BUNDLE_FILE).write_text(json.dumps(forged))
    with pytest.raises(BundleRefused, match="content key"):
        verify_bundle(release, DEV)
    # A signed manifest that lists a draft skill is refused at load.
    draft = {k: v for k, v in manifest.items() if k != "signature"}
    draft["skills"] = [{**draft["skills"][0], "status": "draft"}]
    (release / BUNDLE_FILE).write_text(json.dumps(dev_signer(Purpose.AGENT_BUNDLE).sign("agent_bundle", draft)))
    with pytest.raises(BundleRefused, match="not reviewed"):
        verify_bundle(release, DEV)
    # The test hierarchy is not trusted by production builds.
    with pytest.raises(BundleRefused, match="not trusted"):
        verify_bundle(_release(tmp_path, "1.0.1", skills), Environment.PRODUCTION)
