"""Offline authoring boundaries with an invented author and a throwaway content repository."""

from __future__ import annotations

import copy
import io
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pack_builder import api, cli, source
from pack_builder.accounts import Accounts, chain_errors
from pack_builder.studio import Workspace, handle
from pack_builder.studio_io import Conflict, atomic_write, revision

REPO = Path(__file__).resolve().parents[3]
ITEM = "itm.phy.o.motion.0001"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    pack = root / "content/curriculum/phy/o"
    original = REPO / "content/curriculum/phy/o"
    pack.mkdir(parents=True)
    for name in ("pack.yaml", "map.yaml"):
        shutil.copy(original / name, pack / name)
    shutil.copytree(original / "kcs", pack / "kcs")
    shutil.copytree(source.ref_dir(original), source.ref_dir(pack))
    for table, identity in (("items", ITEM), ("worked_examples", "wex.phy.o.motion.0001")):
        directory = source.PER_RECORD[table]
        (pack / directory).mkdir()
        shutil.copy(original / directory / f"{identity}.yaml", pack / directory)
    (pack / "misconceptions").mkdir()
    shutil.copy(original / "misconceptions/mc.phy.o.time_over_distance.yaml", pack / "misconceptions")
    home = tmp_path / "authors"
    monkeypatch.setenv("JANA_AUTHORING_HOME", str(home))
    Accounts(home).create("lead", "Synthetic Lead", "lead@example.test", ["curriculum_lead"])
    Accounts(home).create("writer", "Synthetic Writer", "writer@example.test", ["subject_author"])
    monkeypatch.setenv("JANA_AUTHOR", "lead")
    return Workspace(root)


def opened(w, table="items", identity=ITEM):
    return w.open_record("pack.phy.o", table, identity)


def save(w, value, **overrides):
    return w.save({"op": "save", **value, "id": value["record"]["id"], **overrides})


def aut04_offline_editing(workspace):
    w = workspace
    item = opened(w)
    item["record"]["stem"] += " Compare the result."
    with patch("socket.socket", side_effect=AssertionError("offline editing must not open a socket")):
        saved = save(w, item)
        assert w.candidate("pack.phy.o", "items", saved["record"])["checks"]
        assert w.candidate("pack.phy.o", "items", saved["record"])["preview"]["lesson"]
    path = w.root / saved["path"]
    assert path.read_text() == source.canonical(saved["record"], "items")
    source.save_record(w.pack("pack.phy.o"), "items", saved["record"])
    assert path.read_text() == source.canonical(saved["record"], "items")
    assert "Synthetic Lead" not in path.read_text() and "example.test" not in path.read_text()
    assert not chain_errors(w.ctx().audit.entries())


def aut07_invalid_not_submittable(workspace):
    item = opened(workspace)
    old_version = item["record"]["version"]
    item["record"]["review"]["status"] = "published"
    item["record"]["version"] = "999.0.0"
    item["record"]["parts"] = []
    saved = save(workspace, item)
    assert saved["record"]["review"]["status"] == "drafted"
    assert saved["record"]["version"] != "999.0.0"
    assert saved["record"]["version"] != old_version  # published source starts one new patch
    assert not workspace.candidate("pack.phy.o", "items", saved["record"])["ok"]
    refused = workspace.dispatch({"op": "promote", "pack": "pack.phy.o", "id": ITEM})
    assert not refused["ok"] and refused["held"]
    again = save(workspace, saved)
    assert again["record"]["version"] == saved["record"]["version"]


def test_stale_editor_cannot_overwrite_external_edits(workspace):
    item = opened(workspace)
    path = workspace.root / item["path"]
    external = copy.deepcopy(item["record"])
    external["stem"] = "An external edit"
    source.save_record(workspace.pack("pack.phy.o"), "items", external)
    item["record"]["stem"] = "A stale editor edit"
    with pytest.raises(Conflict):
        save(workspace, item)
    assert yaml.safe_load(path.read_text())["stem"] == "An external edit"


def test_failed_replace_leaves_the_entire_original_file_and_no_temp(workspace):
    item = opened(workspace)
    path = workspace.root / item["path"]
    before = path.read_bytes()
    with patch("pack_builder.studio_io.os.replace", side_effect=OSError("simulated disk failure")):
        with pytest.raises(OSError):
            atomic_write(path, "replacement", revision(path))
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".studio-*"))


def test_ids_and_workspace_boundaries_are_enforced(workspace, tmp_path):
    item = opened(workspace)
    item["record"]["id"] = "../../escape"
    with pytest.raises(ValueError, match="immutable"):
        save(workspace, {**item, "id": ITEM})
    assert handle(workspace, {"op": "open", "pack": str(tmp_path), "table": "items", "id": ITEM})["error"]
    (workspace.content / "foreign").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        workspace.preflight()


def test_symlinked_content_root_is_refused(tmp_path):
    (tmp_path / "foreign/curriculum").mkdir(parents=True)
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo/content").symlink_to(tmp_path / "foreign", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        Workspace(tmp_path / "repo")


def test_author_role_refusal_is_audited(workspace):
    _, found = workspace.records("pack.phy.o")
    item = opened(workspace, "kcs", found["kcs"][0].record["id"])
    result = handle(workspace, {"op": "save", **item, "id": item["record"]["id"], "author": "writer"})
    assert result["error"] == "forbidden"
    assert workspace.ctx().audit.entries()[-1]["outcome"] == "forbidden"


def aut09_cycle_refused_with_path(workspace):
    _, found = workspace.records("pack.phy.o")
    first, second = found["kcs"][:2]
    for item in found["kcs"]:
        item.record["prerequisites"] = []
        source.save_record(workspace.pack("pack.phy.o"), "kcs", item.record)
    a = opened(workspace, "kcs", first.record["id"])
    a["record"]["prerequisites"] = [{"kc_id": second.record["id"], "strength": "required"}]
    save(workspace, a)
    b = opened(workspace, "kcs", second.record["id"])
    b["record"]["prerequisites"] = [{"kc_id": first.record["id"], "strength": "required"}]
    before = (workspace.root / b["path"]).read_bytes()
    with pytest.raises(ValueError, match=r"prerequisite cycle:.* -> "):
        save(workspace, b)
    assert (workspace.root / b["path"]).read_bytes() == before


def test_multirecord_file_revision_protects_other_kcs(workspace):
    _, found = workspace.records("pack.phy.o")
    first = found["kcs"][0]
    second = next(i for i in found["kcs"][1:] if i.path == first.path)
    a = opened(workspace, "kcs", first.record["id"])
    b = opened(workspace, "kcs", second.record["id"])
    a["record"]["statement"] += " precisely"
    save(workspace, a)
    b["record"]["statement"] += " safely"
    with pytest.raises(Conflict):
        save(workspace, b)
    rows = yaml.safe_load(first.path.read_text())
    assert next(r for r in rows if r["id"] == first.record["id"])["statement"].endswith("precisely")


def aut11_live_verification(workspace):
    item = opened(workspace)["record"]
    original = item["parts"][0]["answer"]["value"]
    item["parts"][0]["answer"]["value"] = "999999"
    result = workspace.candidate("pack.phy.o", "items", item)
    assert not result["ok"] and result["checks"]
    assert any(original in p and "999999" in p for p in result["problems"])


def test_early_hint_answer_leak_is_rejected(workspace):
    item = opened(workspace)["record"]
    value = item["parts"][0]["answer"]["value"]
    item["parts"][0]["hints"][0]["text"]["en"] = f"The answer is {value}."
    result = workspace.candidate("pack.phy.o", "items", item)
    assert not result["ok"]
    assert any("hint" in p for p in result["problems"])


@pytest.mark.parametrize("category", ["validate", "verify", "lint"])
def test_aut05_cli_studio_parity(workspace, category, monkeypatch, capsys):
    request = {"op": "check", "pack": "pack.phy.o", "category": category}
    expected = api.check(category, workspace.pack("pack.phy.o"))
    assert workspace.dispatch(request) == expected
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    assert cli.main(["--json", "studio", "--workspace", str(workspace.root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"result": expected}


def test_new_draft_code_and_identity_are_unique_and_not_saved_until_save(workspace):
    item = workspace.duplicate({"pack": "pack.phy.o", "table": "items", "id": ITEM, "title": "A new item"})
    assert item["record"]["id"] != ITEM and item["new"]
    assert not (workspace.root / item["path"]).exists()
    result = save(workspace, item)
    assert (workspace.root / result["path"]).is_file()
    assert result["record"]["review"]["status"] == "drafted"


def aut11_sandbox_case_saved(workspace):
    item = opened(workspace)["record"]
    answer = item["parts"][0]["answer"]
    response = answer["value"] + (" " + answer["unit"] if answer["unit"] else "")
    result = workspace.golden({"pack": "pack.phy.o", "id": ITEM, "part": item["parts"][0]["id"], "response": response})
    assert result["case"]["expected"]["outcome"] == "correct"
    run = workspace.goldens()
    assert run["ok"] and len(run["cases"]) == 1
    assert (workspace.root / result["path"]).is_file()
    item["stem"] += " Changed."
    source.save_record(workspace.pack("pack.phy.o"), "items", item)
    assert not workspace.goldens()["ok"]  # a changed key/context cannot silently inherit a case


def aut12_signature_test_bench(workspace):
    import asyncio

    from pack_builder.studio_bench import signature_bench

    record = opened(workspace)["record"]
    record["quantities"] = {"d": "1200", "t": "150"}
    mc = {
        "id": "mc.phy.o.inverse",
        "kc_ids": record["kc_ids"],
        "signatures": [{"kind": "answer_transform", "expression": "t/d"}],
        "probe_item_ids": [ITEM],
    }
    other = {**mc, "id": "mc.phy.o.collision"}

    async def offline():
        with patch("socket.create_connection", side_effect=AssertionError("bench must stay offline")):
            return await signature_bench([record], [mc, other], {}, mc["id"])

    result = asyncio.run(offline())
    assert float(result["items"][0]["predictions"][0]["wrong_answer"]) == 0.125
    assert result["items"][0]["probe"]
    assert result["items"][0]["checks"][0]["function"] == "math_evaluate"
    assert result["collisions"][0]["misconceptions"] == [mc["id"], other["id"]]
    # The key itself must never be labelled a misconception.
    mc["signatures"] = [{"kind": "answer_transform", "expression": "d/t"}]
    result = asyncio.run(signature_bench([record], [mc], {}, mc["id"]))
    assert result["items"][0]["predictions"][0]["wrong_answer"] is None


def test_aut14_samples_boundaries_constraints_and_real_tool_failures():
    from pack_builder.studio_bench import sample_template

    template = {
        "parameters": [{"name": "d", "kind": "integer", "min": 0, "max": 100, "step": 2}],
        "stem_template": "Travel {d} m.",
        "answer_tool": {"tool": "math_evaluate", "args": {"expression": "{d}/2"}},
        "constraints": ["d > 0"],
    }
    result = sample_template(template)
    assert len(result["variants"]) == 50
    assert result["variants"][0]["parameters"] == {"d": "0"}
    assert not result["variants"][0]["ok"]
    assert result["variants"][-1]["parameters"] == {"d": "100"}
    assert result["variants"][-1]["key"]["exact"]["text"] == "50"
    assert sum(result["distribution"].values()) == 49
    template["constraints"] = ["__import__('os').system('false')"]
    assert all(not row["ok"] for row in sample_template(template)["variants"])
    template["constraints"] = []
    template["answer_tool"]["args"]["expression"] = "1/({d}-{d})"
    assert all(not row["ok"] for row in sample_template(template)["variants"])


def aut25_marking_change_flagged(workspace):
    import subprocess

    w = workspace
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.test"],
        ["config", "user.name", "Synthetic"],
        ["add", "."],
        ["commit", "-qm", "Published baseline"],
    ):
        subprocess.run(["git", *args], cwd=w.root, check=True)
    item = opened(w)
    item["record"]["parts"][0]["answer"]["tolerance"]["value"] = 0.01
    result = w.dispatch({"op": "diff", **item, "id": ITEM})
    assert result["required_bump"] == "major"
    assert result["marking_changed"] == [ITEM]
    assert any(r["field"] == "$.parts[0].answer.tolerance.value" for r in result["fields"])
    save(w, item)
    again = w.dispatch({"op": "diff", **opened(w), "id": ITEM})
    assert again["before"]["parts"][0]["answer"]["tolerance"]["value"] == 0.005
    assert again["before_preview"]["lesson"]


def aut26_blocking_comments(workspace):
    w = workspace
    req = {
        "op": "comment",
        "pack": "pack.phy.o",
        "table": "items",
        "id": ITEM,
        "text": "Check the tolerance before publication.",
        "blocking": True,
        "anchor": {"kind": "part", "value": "a"},
    }
    row = w.dispatch(req)
    result = w.dispatch({"op": "publish", "pack": "pack.phy.o"})
    assert any("blocking comment" in p for p in result["problems"])
    reply = w.dispatch({**req, "text": "The tolerance is being checked.", "parent": row["id"], "blocking": False})
    assert reply["parent"] == row["id"]
    w.dispatch({**req, "resolve": row["id"]})
    result = w.dispatch({"op": "publish", "pack": "pack.phy.o"})
    assert not any("blocking comment" in p for p in result["problems"])
    assert "Check the tolerance" not in json.dumps(source.read_pack(w.pack("pack.phy.o"))[0])
    assert all("Check the tolerance" not in p.read_text() for p in w.content.rglob("*.yaml"))
    for text in ['student said "my answer"', "Student Robert needs help.", "Use name Robert here.", "me@example.test"]:
        assert handle(w, {**req, "text": text})["error"] == "invalid"


def test_aut32_green_evaluation_becomes_stale_on_changed_inputs(workspace, monkeypatch):
    from pack_builder import studio_workflow as workflow

    w = workspace
    original_checks, original_eval = workflow.categorised_problems, api.eval_pack
    monkeypatch.setattr(
        workflow,
        "categorised_problems",
        lambda *a: ({k: [] for k in ["validate", "verify", "lint", "qa", "scan"]}, None),
    )
    monkeypatch.setattr(api, "eval_pack", lambda p: {"ok": True, "cases": []})
    report = w.dispatch({"op": "evaluate", "pack": "pack.phy.o"})
    assert report["ok"]
    assert report["sha256"] == workflow.fingerprint(w, "pack.phy.o")
    item = opened(w)
    item["record"]["stem"] += " Check the distance."
    save(w, item)
    result = w.dispatch({"op": "publish", "pack": "pack.phy.o"})
    assert any("current content" in p for p in result["problems"])
    # Actual invalid inputs cannot inherit the mocked green record.
    monkeypatch.setattr(workflow, "categorised_problems", original_checks)
    monkeypatch.setattr(api, "eval_pack", original_eval)
    item = opened(w)
    item["record"]["parts"] = []
    save(w, item)
    report = w.dispatch({"op": "evaluate", "pack": "pack.phy.o"})
    assert not report["ok"] and report["problems"]


def aut34_min_bump_enforced(workspace):
    import subprocess

    w = workspace
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.test"],
        ["config", "user.name", "Synthetic"],
        ["add", "."],
        ["commit", "-qm", "Published baseline"],
    ):
        subprocess.run(["git", *args], cwd=w.root, check=True)
    item = opened(w)
    item["record"]["parts"][0]["marks"] += 1
    save(w, item)
    plan = w.dispatch({"op": "version_plan", "pack": "pack.phy.o"})
    assert plan["required_bump"] == "major"
    request = {
        "op": "set_version",
        "pack": "pack.phy.o",
        "version": "0.2.0",
        "revision": plan["revision"],
        "corrections": {ITEM: "Corrected the available marks."},
    }
    assert handle(w, request)["error"] == "invalid"
    assert w.dispatch({**request, "version": "2.0.0"})["ok"]


def aut35_retire_requires_reference_update(workspace):
    w = workspace
    pack = w.pack("pack.phy.o")
    lesson = pack / "lessons/les.phy.o.fixture.yaml"
    lesson.parent.mkdir()
    lesson.write_text(
        yaml.safe_dump({"id": "les.phy.o.fixture", "blocks": [{"type": "quick_check", "item_ids": [ITEM]}]})
    )
    req = {"op": "retire", "pack": "pack.phy.o", "table": "items", "id": ITEM, "reason": "Incorrect key."}
    result = w.dispatch(req)
    assert not result["ok"] and result["impact"]["records"][0]["id"] == "les.phy.o.fixture"
    lesson.unlink()
    misconception = opened(w, "misconceptions", "mc.phy.o.time_over_distance")
    misconception["record"]["probe_item_ids"] = []
    save(w, misconception)
    plan = w.dispatch(req)
    assert plan["ok"]
    assert w.dispatch({**req, **plan, "apply": True})["ok"]
    assert ITEM in source._load(pack / "pack.yaml")["retired_ids"]
    assert not (pack / "items" / f"{ITEM}.yaml").exists()
    assert w.dispatch({"op": "workflow", "pack": "pack.phy.o"})["retirements"][0]["reason"] == "Incorrect key."


def test_aut36_replay_and_apply_migration(workspace):
    w = workspace
    pack = w.pack("pack.phy.o")
    _, found = w.records("pack.phy.o")
    old, new = found["kcs"][0].record["id"], found["kcs"][1].record["id"]
    # Remove all references in the throwaway workspace before applying a one-to-one migration.
    for path in pack.rglob("*.yaml"):
        if path.name != "pack.yaml":
            path.write_text(path.read_text().replace(old, new))
    # Restore just the source KC, so the migration starts from a real active KC.
    path = found["kcs"][0].path
    records = source._load(path)
    records[0]["id"] = old
    path.write_text(source.canonical(records, "kcs"))
    version = source._load(pack / "pack.yaml")["version"]
    row = {"from_kc_id": old, "from_version": version, "to_version": "2.0.0", "to": [{"kc_id": new, "weight": 1.0}]}
    req = {"op": "migration", "pack": "pack.phy.o", "migrations": [row]}
    result = w.dispatch(req)
    assert result["replay"]["ok"]
    assert result["replay"]["before"][0]["attempts"] == result["replay"]["after"][0]["attempts"] == 3
    assert result["ok"], result
    applied = w.dispatch({**req, "apply": True, "revisions": result["revisions"]})
    assert applied["applied"]
    assert source._load(pack / "pack.yaml")["version"] == "2.0.0"
    assert old not in {k.record["id"] for k in w.records("pack.phy.o")[1]["kcs"] if k.record["status"] == "active"}


def test_atomic_change_set_recovers_after_a_mid_commit_disk_failure(workspace):
    from pack_builder.studio_io import atomic_changes, recover_changes

    w = workspace
    first, second = w.root / "one.txt", w.root / "two.txt"
    first.write_text("old one")
    second.write_text("old two")
    entries = [
        {"path": p.name, "text": text, "expected": revision(p)} for p, text in [(first, "new one"), (second, "new two")]
    ]
    original = atomic_write

    def broken(path, text, expected=None):
        if path == second:
            raise OSError("simulated full disk")
        return original(path, text, expected)

    with patch("pack_builder.studio_io.atomic_write", side_effect=broken), pytest.raises(OSError):
        atomic_changes(w.root, entries)
    assert first.read_text() == "new one" and second.read_text() == "old two"
    recover_changes(w.root)
    assert second.read_text() == "new two"
    assert not (w.root / "reviews/studio/.pending.json").exists()


def aut36_migration_references_updated(workspace):
    w = workspace
    _, found = w.records("pack.phy.o")
    old, new = found["kcs"][0].record["id"], found["kcs"][1].record["id"]
    skill = w.root / "skills/teaching/phy/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f"---\nkcs: [{old}]\n---\nFictional fixture.\n")
    row = {
        "from_kc_id": old,
        "from_version": source._load(w.pack("pack.phy.o") / "pack.yaml")["version"],
        "to_version": "2.0.0",
        "to": [{"kc_id": new, "weight": 1}],
    }
    result = w.dispatch({"op": "migration", "pack": "pack.phy.o", "migrations": [row]})
    assert not result["ok"]
    assert str(skill.relative_to(w.root)) in result["impact"][old]["skills"]
    # Prefixes are not identities: a longer valid id does not cause a false dangling-reference report.
    skill.write_text(f"---\nkcs: [{old}_longer]\n---\n")
    assert str(skill.relative_to(w.root)) not in w.references("pack.phy.o", old)["skills"]


def aut36_migration_replay_check(workspace):
    from pack_builder.build import load_source
    from pack_builder.studio_replay import replay

    w = workspace
    loaded = load_source(w.pack("pack.phy.o"))
    active = [k for k in loaded.tables["kcs"] if k["status"] == "active"]
    old, left, right = [k["id"] for k in active[:3]]
    for kc in loaded.tables["kcs"]:
        kc["prerequisites"] = []
    result = replay(
        loaded.pack,
        loaded.tables,
        [
            {
                "from_kc_id": old,
                "from_version": "1.0.1",
                "to_version": "2.0.0",
                "to": [{"kc_id": left, "weight": 0.7}, {"kc_id": right, "weight": 0.3}],
            }
        ],
    )
    before = next(r for r in result["before"] if r["kc_id"] == old)
    after = {r["kc_id"]: r for r in result["after"]}
    assert result["ok"] and old not in after
    assert after[left]["attempts"] == after[right]["attempts"] == before["attempts"]
    assert after[left]["succ_w"] == pytest.approx(before["succ_w"])
    assert result["after"] == result["reference_after"]


def aut15_inline_lint(workspace):
    w = workspace
    original = REPO / "skills/agent/agent-diagnose-question"
    path = w.root / "skills/agent/agent-diagnose-question/SKILL.md"
    path.parent.mkdir(parents=True)
    shutil.copytree(original / "evals", path.parent / "evals")
    path.write_text((original / "SKILL.md").read_text())
    opened_skill = w.dispatch({"op": "skill_open", "name": path.parent.name})
    text = opened_skill["text"].replace("summary: Classify a question", "summary: This skill classifies a question")
    report = w.dispatch({"op": "skill_check", "name": path.parent.name, "text": text})
    assert any(f["rule"] == "L01" and f["line"] == 1 for f in report["findings"])
    assert report["eval_cases"] > 0 and report["eval_minimum"] > 0
    assert report["role_slices"]["diagnoser"]
    assert report["index_budget"]["diagnoser"]["ok"]
    saved = w.dispatch(
        {
            "op": "skill_save",
            "name": path.parent.name,
            "text": "---\ninvalid: [\n",
            "revision": opened_skill["revision"],
        }
    )
    assert not saved["report"]["ok"]
    assert path.read_text() == "---\ninvalid: [\n"
    assert handle(w, {"op": "skill_save", "name": "../escape", "text": "", "revision": "missing"})["error"]


def aut32_evals_before_submit(workspace):
    from agent_core.assets.skills import parse
    from agent_core.config import Settings
    from jana_tools import skill_evals

    w = workspace
    original = REPO / "skills/agent/agent-diagnose-question"
    path = w.root / "skills/agent/agent-diagnose-question/SKILL.md"
    path.parent.mkdir(parents=True)
    shutil.copytree(original / "evals", path.parent / "evals")
    path.write_text((original / "SKILL.md").read_text())
    result = w.dispatch(
        {"op": "skill_submit", "name": path.parent.name, "text": path.read_text(), "revision": revision(path)}
    )
    assert not result["ok"]
    skill = parse(path)
    record = skill_evals.passing_records(w.root / "skills")[skill.name]
    assert skill_evals.passing(record, skill, Settings())
    path.write_text(path.read_text().replace('version: "0.1"', 'version: "0.2"'))
    assert not skill_evals.passing(record, parse(path), Settings())
    path.write_text((original / "SKILL.md").read_text().replace("subject: general", "subject: physics"))
    assert not skill_evals.passing(record, parse(path), Settings())


def diagram(workspace):
    original = REPO / "content/curriculum/phy/o/diagrams"
    directory = workspace.pack("pack.phy.o") / "diagrams"
    directory.mkdir(exist_ok=True)
    identity = "dgm.phy.plane_mirror_reflection.v1"
    for name in (identity + ".yaml", "plane_mirror_reflection_v1.svg"):
        shutil.copy(original / name, directory / name)
    return workspace.dispatch({"op": "diagram_open", "pack": "pack.phy.o", "id": identity})


def aut16_part_tagging_complete(workspace):
    w = workspace
    value = diagram(w)
    req = {"op": "diagram_check", "pack": "pack.phy.o", "entry": value["entry"], "svg": value["svg"]}
    assert w.dispatch(req)["ok"], w.dispatch(req)["problems"]
    req["svg"] = value["svg"].replace('data-part="incident_ray"', "")
    report = w.dispatch(req)
    assert not report["ok"]
    assert any("no element" in p or "Untagged" in p for p in report["problems"])
    req["svg"] = value["svg"].replace("</svg>", '<circle cx="1" cy="1" r="1"/></svg>')
    assert any("Untagged" in p for p in w.dispatch(req)["problems"])


def aut16_licence_allow_list(workspace):
    w = workspace
    value = diagram(w)
    value["entry"]["licence"] = "CC-BY-NC-4.0"
    report = w.dispatch({"op": "diagram_check", "pack": "pack.phy.o", "entry": value["entry"], "svg": value["svg"]})
    assert not report["ok"] and any("licence" in p for p in report["problems"])
    raw = value["svg"].replace(
        "</svg>", '<script>alert(1)</script><image href="https://example.test/a"/><path onclick="alert(1)"/></svg>'
    )
    cleaned = w.dispatch({"op": "diagram_sanitise", "pack": "pack.phy.o", "svg": raw})
    assert cleaned["ok"] and len(cleaned["removed"]) >= 3
    assert "<script" not in cleaned["svg"] and "onclick" not in cleaned["svg"]


def test_diagram_save_conflicts_versioning_and_part_identity(workspace):
    w = workspace
    value = diagram(w)
    identity = value["entry"]["id"]
    value["entry"]["review"]["status"] = "approved"
    path = w.pack("pack.phy.o") / "diagrams" / f"{identity}.yaml"
    path.write_text(source.canonical(value["entry"], "diagrams"))
    value = w.dispatch({"op": "diagram_open", "pack": "pack.phy.o", "id": identity})
    value["svg"] += "\n"
    saved = w.dispatch({"op": "diagram_save", "pack": "pack.phy.o", "id": identity, **value})
    assert saved["entry"]["version"] == "1.0.1"
    assert saved["entry"]["review"]["status"] == "in_review"
    assert handle(w, {"op": "diagram_save", "pack": "pack.phy.o", "id": identity, **value})["error"] == "conflict"
    saved["entry"]["parts"][0]["function"] = "A different physical part."
    assert handle(w, {"op": "diagram_save", "pack": "pack.phy.o", "id": identity, **saved})["error"] == "invalid"


def aut39_import_idempotent_and_licensed(workspace):
    w = workspace
    item = opened(w)["record"]
    item["id"] = "itm.phy.o.motion.0002"
    item["external_ref"] = "fixture-bank-row-1"
    provenance = {
        "title": "Fictional licensed item bank",
        "url": "https://example.test/fixture",
        "licence": "CC-BY-4.0",
        "attribution": "Synthetic fixture author",
        "modifications": "Original wording retained.",
        "retrieved": "2026-10-17",
    }
    request = {
        "op": "import_preview",
        "pack": "pack.phy.o",
        "table": "items",
        "format": "yaml",
        "text": yaml.safe_dump([item]),
        "source": provenance,
    }
    report = w.dispatch(request)
    assert report["ok"], report["problems"]
    applied = w.dispatch({**request, "op": "import_apply", "preview_sha256": report["preview_sha256"]})
    assert applied["imported"] == [item["id"]]
    assert opened(w, identity=item["id"])["record"]["provenance"]["origin"] == "imported"
    report = w.dispatch(request)
    repeated = w.dispatch({**request, "op": "import_apply", "preview_sha256": report["preview_sha256"]})
    assert repeated["imported"] == [] and repeated["unchanged"] == 1
    bad = w.dispatch({**request, "source": {}})
    assert not bad["ok"] and bad["problems"][0]["row"] == 1 and bad["problems"][0]["column"] == "source_*"
    assert handle(w, {**request, "format": "csv", "text": "name,class,score\nSynthetic,1,90"})["error"] == "invalid"
    changed = {**request, "text": request["text"] + "\n"}
    assert (
        handle(w, {**changed, "op": "import_apply", "preview_sha256": report["preview_sha256"]})["error"] == "invalid"
    )


def test_aut31_offline_queue_results_attach_and_stale_drafts_are_flagged(workspace, monkeypatch):
    from pack_builder import studio_jobs

    w = workspace
    queued = w.dispatch(
        {
            "op": "job_queue",
            "kind": "simulation",
            "pack": "pack.phy.o",
            "table": "items",
            "id": ITEM,
            "personas": ["answer_seeker"],
            "count": 5,
        }
    )
    job = queued["job"]
    assert job["count"] == 5 and job["development_data_only"] and not job["candidate_acceptance"]
    monkeypatch.delenv("JANA_STUDIO_EVAL_URL", raising=False)
    assert w.dispatch({"op": "job_start", "job_id": job["id"]})["queued"]

    async def fixture_result(*args):
        return {
            "kind": "simulation",
            "ok": True,
            "rows": [
                {
                    "persona": "answer_seeker",
                    "turns": [{"student": "Please give the answer.", "tutor": "What have you tried?"}],
                    "leaks": [],
                    "checks": {"no_leak": True},
                    "rubric": {"status": "calibrated_judge_required", "scores": None},
                }
            ],
            "rubric_acceptance": False,
        }

    monkeypatch.setattr(studio_jobs, "execute", fixture_result)
    monkeypatch.setenv("JANA_STUDIO_EVAL_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("JANA_STUDIO_EVAL_MODEL", "synthetic-test-provider")
    assert studio_jobs.run(w, job["id"]) == 0
    result = w.dispatch({"op": "job_result", "job_id": job["id"]})
    assert result["current"] and result["result"]["rows"][0]["checks"]["no_leak"]
    assert not result["result"]["rubric_acceptance"]
    attached = w.dispatch({"op": "workflow", "pack": "pack.phy.o"})["simulations"][0]
    assert attached["job_id"] == job["id"] and attached["result_path"].endswith(job["id"] + ".json")
    item = opened(w)
    item["record"]["stem"] += " Check the time."
    save(w, item)
    assert not w.dispatch({"op": "job_result", "job_id": job["id"]})["current"]
    assert handle(w, {"op": "job_start", "job_id": job["id"]})["error"] == "invalid"
    with pytest.raises(ValueError, match="loopback"):
        studio_jobs.local_url("https://external.example.test/v1")


def test_evaluation_worker_binds_real_case_results_to_skill_source(workspace, monkeypatch):
    import asyncio

    from jana_tools.skill_evals import CaseResult
    from pack_builder import studio_jobs

    w = workspace
    original = REPO / "skills/agent/agent-diagnose-question"
    path = w.root / "skills/agent/agent-diagnose-question/SKILL.md"
    path.parent.mkdir(parents=True)
    shutil.copytree(original / "evals", path.parent / "evals")
    shutil.copy(original / "SKILL.md", path)
    queued = w.dispatch({"op": "job_queue", "kind": "local_evaluation", "pack": "pack.phy.o"})["job"]
    calls = []

    async def fixture_case(case, skill, provider, model, out, **options):
        calls.append((case["id"], options))
        return CaseResult(case["id"], hard_total=1, hard_passed=1)

    monkeypatch.setattr(studio_jobs.skill_evals, "run_case", fixture_case)
    monkeypatch.setattr(
        studio_jobs,
        "categorised_problems",
        lambda *a: ({k: [] for k in ["validate", "verify", "lint", "qa", "scan"]}, None),
    )
    monkeypatch.setattr(api, "eval_pack", lambda p: {"ok": True, "cases": []})
    result = asyncio.run(
        studio_jobs.execute(w, queued, "http://127.0.0.1:8080", "synthetic-test-provider", "synthetic-test-provider")
    )
    assert result["ok"], result["problems"]
    assert calls and all(options["workspace"] == w.root and options["engine_stage"] == "S2" for _, options in calls)
    record = json.loads((w.root / "evals/skill-evals/results.json").read_text())["skills"][path.parent.name]
    assert record["network"] == "loopback_only" and record["source_sha256"]


def test_studio_bench_protocol_strips_source_only_metadata(workspace):
    record = opened(workspace, "misconceptions", "mc.phy.o.time_over_distance")["record"]
    assert "authoring" in record
    result = workspace.dispatch({"op": "signature_bench", "pack": "pack.phy.o", "record": record})
    assert result["ok"] and result["items"]


def test_import_preserves_all_attributions_and_ai_declaration():
    from pack_builder.studio_import import provenance

    source = {
        "title": "Synthetic source",
        "url": "https://example.test/one",
        "licence": "CC-BY-4.0",
        "attribution": "Fixture",
        "modifications": "None",
        "retrieved": "2026-10-17",
    }
    row = {
        "provenance": {
            "origin": "adapted",
            "licence": "CC-BY-4.0",
            "drafted_with_ai": True,
            "ai_model": "declared-fixture-model",
            "sources": [source, {**source, "url": "https://example.test/two"}],
        }
    }
    result = provenance(row, {})
    assert len(result["sources"]) == 2 and result["drafted_with_ai"] and result["ai_model"] == "declared-fixture-model"
    row["provenance"]["sources"][1]["licence"] = "CC-BY-SA-4.0"
    with pytest.raises(ValueError, match="share-alike"):
        provenance(row, {})


def test_template_ranges_variant_and_unmarkable_keys(workspace):
    from pack_builder.studio_bench import sample_template
    from pack_builder.studio_templates import digest

    w = workspace
    template = {
        "id": "itpl.phy.o.motion.0001",
        "kc_ids": ["kc.phy.o.motion.average_speed"],
        "item_type": "numeric",
        "stem_template": "A runner travels {d} m in 80 s. Find the average speed.",
        "parameters": [{"name": "d", "kind": "integer", "min": 400, "max": 800, "step": 8}],
        "answer_tool": {"tool": "math_evaluate", "args": {"expression": "{d}/80"}},
        "version": "0.1.0",
        "provenance": {"origin": "original", "licence": "LicenseRef-Own", "drafted_with_ai": False, "sources": []},
        "review": {"status": "drafted", "reviewers": []},
        "authoring": {"history": ["drafted"]},
    }
    source.save_record(w.pack("pack.phy.o"), "item_templates", template)
    sample = w.dispatch({"op": "sample_template", "pack": "pack.phy.o", "record": template})
    assert sample["ok"] and len(sample["variants"]) == 50
    review = w.dispatch({"op": "template_review_ranges", "pack": "pack.phy.o", "id": template["id"]})
    assert review["ok"] and review["reviewed_ranges"]["template_sha256"] == digest(template)
    recipe = {
        "steps": [{"n": 1, "latex": "v = {key}", "reason": "Divide distance by time", "check_id": "chk_build_variant"}],
        "final_answer": {"latex": "{key}", "check_id": "chk_build_variant"},
        "fading_order": [1],
        "checks": {"chk_build_variant": {"tool": "math_evaluate", "args": {"expression": "{d}/80"}}},
    }
    request = {
        "op": "template_variant",
        "pack": "pack.phy.o",
        "id": "wex.phy.o.motion.0001",
        "template_id": template["id"],
        "new_id": "wex.phy.o.motion.0002",
        "recipe": recipe,
        "sample": 0,
    }
    made = w.dispatch(request)
    assert made["ok"], made.get("problems")
    assert made["opened"]["record"]["review"]["status"] == "drafted"
    assert made["opened"]["record"]["final_answer"]["latex"] == "5"
    assert made["report"]["checks"][0]["function"] == "math_evaluate"
    assert handle(w, request)["error"] == "invalid"
    recipe["final_answer"]["latex"] = "999"
    rejected = w.dispatch({**request, "new_id": "wex.phy.o.motion.0003"})
    assert not rejected["ok"]
    assert not (w.pack("pack.phy.o") / "worked-examples/wex.phy.o.motion.0003.yaml").exists()
    template["answer_tool"] = {"tool": "math_simplify", "args": {"expression": "x+x"}}
    assert not sample_template(template)["ok"]  # a symbolic expression is not a numeric markable key
    template["answer_tool"] = {"tool": "math_evaluate", "args": {"expression": "{d}/80"}}
    template["stem_template"] = "{context.name} travels {d} m in 80 s."
    samples = sample_template(template, contexts={"name": ["Fictional A", "Fictional B"]})
    assert samples["variants"][0]["stem"].startswith("Fictional A")
    assert samples["variants"][1]["stem"].startswith("Fictional B")


def test_field_diff_added_object_has_a_single_absent_boundary():
    from pack_builder.studio_workflow import field_diff

    assert field_diff({}, {"a": {"b": 1}}) == [{"field": "$.a", "before": {"$absent": True}, "after": {"b": 1}}]


def test_studio_crashed_evaluation_worker_can_restart_same_request(workspace, monkeypatch):
    from types import SimpleNamespace

    from pack_builder import studio_jobs

    job = workspace.dispatch({"op": "job_queue", "kind": "local_evaluation", "pack": "pack.phy.o"})["job"]
    path = studio_jobs.path_for(workspace, job["id"])
    job.update(status="running", pid=987654321, started_epoch=1)
    atomic_write(path, json.dumps(job))
    monkeypatch.setenv("JANA_STUDIO_EVAL_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("JANA_STUDIO_EVAL_MODEL", "fixture-runtime-not-contacted")

    def dead(pid, signal):
        raise ProcessLookupError()

    monkeypatch.setattr(studio_jobs.os, "kill", dead)
    launched = []

    def start(args, **kwargs):
        launched.append(args)
        return SimpleNamespace(pid=123456789)

    monkeypatch.setattr(studio_jobs.subprocess, "Popen", start)
    result = studio_jobs.start(workspace, {"job_id": job["id"]})
    assert result["ok"] and len(launched) == 1 and launched[0][-1] == job["id"]
    assert studio_jobs.load(workspace, job["id"])["pid"] == 123456789
    assert workspace.dispatch({"op": "job_result", "job_id": job["id"]})["result"] is None


def aut08_published_ids_frozen(workspace):
    _, found = workspace.records("pack.phy.o")
    node = opened(workspace, "curriculum_nodes", found["curriculum_nodes"][0].record["id"])
    identity = node["record"]["id"]
    changed = copy.deepcopy(node)
    changed["record"]["id"] = identity + "_renamed"
    with pytest.raises(ValueError, match="immutable"):
        save(workspace, changed, id=identity)
    node["record"]["title"] += " (reworded title)"
    renamed = save(workspace, node)
    assert renamed["record"]["id"] == identity
    assert renamed["record"]["title"].endswith("(reworded title)")


def aut04_studio_not_in_student_build():
    import tomllib

    student = REPO / "apps/desktop/src-tauri"
    base = json.loads((student / "tauri.conf.json").read_text())
    assert "studio" not in json.dumps(base.get("bundle", {}).get("resources", {})).lower()
    build = (REPO / "scripts/packaging/build-sidecars.sh").read_text()
    assert "studio-backend" not in build
    desktop = json.loads((REPO / "apps/desktop/package.json").read_text())
    assert "@jana/studio" not in desktop.get("dependencies", {})
    manifest = tomllib.loads((student / "Cargo.toml").read_text())
    assert "jana-studio" not in manifest.get("dependencies", {})


def aut10_lesson_editor_structure(workspace):
    from pack_builder.studio import TABLES

    assert "lessons" in TABLES
    lesson = source._load(REPO / "content/curriculum/phy/o/lessons/les.phy.o.motion.speed_and_acceleration.yaml")
    # The fixture needs its referenced records; use a complete local pack and no learner database.
    lesson_id = lesson["id"]
    target = workspace.pack("pack.phy.o") / "lessons"
    target.mkdir(exist_ok=True)
    lesson["blocks"] = [{"type": "summary", "text": {"en": "Remember distance over time."}}]
    source.save_record(workspace.pack("pack.phy.o"), "lessons", lesson)
    report = workspace.candidate("pack.phy.o", "lessons", lesson)
    assert not report["ok"] and report["problems"]
    assert any("blocks" in p or "lesson" in p or "block" in p for p in report["problems"])
    assert workspace.open_record("pack.phy.o", "lessons", lesson_id)["record"]["blocks"] == lesson["blocks"]
