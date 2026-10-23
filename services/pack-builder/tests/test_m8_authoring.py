"""M8: content operations backbone (AUT-01 to AUT-06, AUT-17 to AUT-23, AUT-29, AUT-30, AUT-33, CUR-22, CUR-31).

Each test works on a throwaway repository: a copy of the S1 physics sources, a temporary authoring home and invented
accounts. Every name, e-mail address, draft and held-out item here is synthetic test data."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config.environments import Environment
from agent_core.store.packs import PackRejectedError, PackShelf, read_pack, table_sha256, verify
from pack_builder import api, cli, drafting, heldout, roles
from pack_builder import source as tree
from pack_builder.accounts import Accounts, AuditLog, chain_errors, totp
from pack_builder.build import BuildError, build
from pack_builder.preview import NotAPreviewPack, build_preview, open_preview

REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "content" / "curriculum" / "phy" / "o"
ITEM = "itm.phy.o.motion.0001"
NAMES = {"lead": ("Ada Lead", ["curriculum_lead"]), "slead": ("Ben Subject", ["subject_lead"]),
         "author": ("Cy Author", ["subject_author"]), "author2": ("Dee Writer", ["subject_author"]),
         "translator": ("Eli Translator", ["language_reviewer"])}  # fmt: skip


@dataclass
class Repo:
    root: Path
    pack: Path
    home: Path

    def ctx(self, who: str, otp: bool = True) -> api.Context:
        account = Accounts(self.home).get(who)
        return api.Context(account, totp(account.totp_secret) if otp else None, self.home)

    def record(self, record_id: str) -> dict[str, Any]:
        return api.find_record(record_id)[2]

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Repo]:
    root = tmp_path / "repo"
    pack = root / "content" / "curriculum" / "phy" / "o"
    shutil.copytree(PACK, pack)
    shutil.copytree(tree.ref_dir(PACK), tree.ref_dir(pack))
    _trim(pack)
    home = tmp_path / "authoring-home"
    monkeypatch.setattr(api, "REPO_ROOT", root)
    monkeypatch.setattr(api, "CURRICULUM", root / "content" / "curriculum")
    monkeypatch.setenv("JANA_AUTHORING_HOME", str(home))
    monkeypatch.delenv(heldout.KEY_ENV, raising=False)
    accounts = Accounts(home)
    for account_id, (name, account_roles) in NAMES.items():
        accounts.create(account_id, name, f"{account_id}@example.test", account_roles, pub=account_id == "lead")
    yield Repo(root, pack, home)


ORIGINAL = {"items": {f"itm.phy.o.motion.000{n}" for n in range(1, 5)},
            "worked_examples": {f"wex.phy.o.motion.000{n}" for n in range(1, 5)},
            "misconceptions": {"mc.phy.o.time_over_distance", "mc.phy.o.kmh_divide_by_36",
                               "mc.phy.o.final_velocity_over_time", "mc.phy.o.gravity_sign_flipped"}}  # fmt: skip


def _trim(pack: Path) -> None:
    """The fixture keeps the first twelve records of the S1 pack, so the review tests stay fast, and starts them all at
    `verified`, whatever pipeline state the real pack has reached since."""
    _, found = tree.read_pack(pack)
    for located in found["mock_papers"]:  # the mock papers draw on the items the fixture leaves out
        located.path.unlink()
    for table in ("items", "worked_examples", "misconceptions", "lessons"):
        for located in found[table]:
            if located.record["id"] not in ORIGINAL.get(table, set()):
                located.path.unlink()
            else:
                record = located.record
                tree.save_record(pack, table, {**record, "review": {**record["review"], "status": "verified"},
                                               "authoring": {**record["authoring"],
                                                             "history": ["drafted", "verified"]}})  # fmt: skip
    kcs = [k.record for k in found["kcs"]]
    for kc in kcs:
        kc["misconception_ids"] = [m for m in kc.get("misconception_ids", []) if m in ORIGINAL["misconceptions"]]
    tree.write_table(pack, "kcs", kcs)


def _all_reviewed(repo: Repo) -> list[str]:
    _, found = tree.read_pack(repo.pack)
    return [i.record["id"] for t in ("items", "worked_examples", "misconceptions") for i in found[t]]


def _commit(repo: Repo, message: str) -> str:
    if not (repo.root / ".git").exists():
        repo.git("init", "-q")
        repo.git("config", "user.email", "ci@example.test")
        repo.git("config", "user.name", "CI")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", message)
    return repo.git("rev-parse", "HEAD").strip()


def _draft_route(answer: str) -> tuple[drafting.Route, list[str]]:
    """A scripted local model that drafts one item; `answer` is the key it writes."""
    calls: list[str] = []
    base = yaml.safe_load((PACK / "items" / f"{ITEM}.yaml").read_text())
    drafted = {"stem": "A runner covers 1200 m along a straight track in 150 s.", "parts": copy.deepcopy(base["parts"]),
               "solution": copy.deepcopy(base["solution"]), "checks": copy.deepcopy(base["checks"])}  # fmt: skip
    drafted["parts"][0]["answer"]["value"] = answer

    def generate(system: str, user: str) -> str:
        calls.append(user)
        return yaml.safe_dump(drafted, allow_unicode=True)

    return drafting.Route("local", "scripted-model", "local", "local", generate), calls


def _new_draft_item(repo: Repo, record_id: str = "itm.phy.o.motion.0101") -> str:
    record = copy.deepcopy(repo.record(ITEM))
    record.update(id=record_id, review={"status": "drafted", "reviewers": []},
                  authoring={"drafted_by": repo.ctx("author").need().rev_id, "history": ["drafted"]})  # fmt: skip
    tree.save_record(repo.pack, "items", record)
    return record_id


# --- AUT-01 and AUT-02 ----------------------------------------------------------------------------------------------


def aut01_permission_matrix_enforced(repo: Repo) -> None:
    for action, allowed in roles.PERMISSIONS.items():
        for role in roles.ROLES:
            if role not in allowed:
                with pytest.raises(roles.Forbidden):
                    roles.require([role], action)
    audit = AuditLog(repo.home)
    calls = {
        "edit_draft": lambda c: api.touch(c, ITEM),
        "ai_draft": lambda c: api.draft(c, "hint_ladder", ITEM, "", drafting.Route("template")),
        "request_publication_bank": lambda c: api.bank(c, repo.pack, held_out_share=0.0),
        "request_publication": lambda c: api.publish(c, repo.pack, "dev", commit="0" * 40),
    }
    for action, call in calls.items():
        for who, (_, account_roles) in NAMES.items():
            if roles.allowed(account_roles, action.removesuffix("_bank")):
                continue
            before = len(audit.entries())
            with pytest.raises(roles.Forbidden):
                call(repo.ctx(who))
            last = audit.entries()[-1]
            assert len(audit.entries()) == before + 1 and last["outcome"] == "forbidden" and last["actor"] == who
    # The signing service refuses a request from anyone but a curriculum lead, whatever the CLI did.
    from signing_service.service import Refused, handle

    commit = _commit(repo, "content")
    request = {"request_id": "pubreq_test01", "commit": commit, "pack_id": "pack.phy.o", "pack_dir":
               "content/curriculum/phy/o", "version": "0.1.0", "channel": "dev",
               "requested_by": {"role_id": repo.ctx("author").need().rev_id}}  # fmt: skip
    with pytest.raises(Refused, match="not from a curriculum lead"):
        handle(request, repo.root, repo.root / "out", authoring_home=repo.home)
    assert audit.entries()[-1]["actor"] == "signing_service" and audit.entries()[-1]["outcome"] == "refused"
    # The CLI reports a refusal as `forbidden` with exit code 1.
    os.environ["JANA_AUTHOR"] = "translator"
    try:
        assert cli.main(["--json", "edit", ITEM]) == cli.EXIT_FAIL
    finally:
        del os.environ["JANA_AUTHOR"]


def aut02_no_personal_ids_in_pack(repo: Repo, tmp_path: Path) -> None:
    api.touch(repo.ctx("author"), ITEM)
    assert api.promote(repo.ctx("author"), repo.pack, [ITEM])["verified"] == [ITEM]
    built = build(repo.pack, tmp_path / "out")
    blobs = built.pack_path.read_bytes() + built.json_path.read_bytes() + built.report_path.read_bytes()
    for account_id, (name, _) in NAMES.items():
        for personal in (name, f"{account_id}@example.test", name.split()[0]):
            assert personal.encode() not in blobs
    assert repo.ctx("author").need().rev_id.encode() not in blobs, "authors stay in the authoring system"
    audit = AuditLog(repo.home).entries()
    assert {e["action"] for e in audit} >= {"edit", "promote"} and all(e["actor"] == "author" for e in audit)


def aut02_audit_chain_tamper_detected(repo: Repo) -> None:
    audit = AuditLog(repo.home)
    for n in range(4):
        audit.append("author", "edit", "ok", f"rec{n}")
    entries = audit.entries()
    assert chain_errors(entries) == []
    assert chain_errors(entries[:1] + entries[2:]), "a deleted entry is detected"
    assert chain_errors([entries[0], entries[2], entries[1], *entries[3:]]), "a reordered entry is detected"
    edited = copy.deepcopy(entries)
    edited[1]["outcome"] = "forbidden"
    assert chain_errors(edited), "an edited entry is detected"


WRITER = """
import sys, time
from pathlib import Path
from pack_builder.accounts import AuditLog
home, go, name, count = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
while not go.exists():
    time.sleep(0.001)
log = AuditLog(home)
for n in range(count):
    log.append(name, "edit", "ok", f"{name}-{n}")
"""


def test_audit_log_two_processes_keep_one_chain(tmp_path: Path) -> None:
    """AUT-02: two authoring processes appending at once (the studio and the CLI) still leave one unbroken chain."""
    home, go, count = tmp_path / "home", tmp_path / "go", 60
    home.mkdir()
    path = os.pathsep.join([str(REPO / "services" / "pack-builder"), os.environ.get("PYTHONPATH", "")])
    env = {**os.environ, "PYTHONPATH": path}
    writers = [subprocess.Popen([sys.executable, "-c", WRITER, str(home), str(go), name, str(count)], env=env)
               for name in ("studio", "cli")]  # fmt: skip
    go.touch()
    assert [w.wait(timeout=120) for w in writers] == [0, 0]
    entries = AuditLog(home).entries()
    assert len(entries) == 2 * count
    assert chain_errors(entries) == []
    assert {e["actor"] for e in entries} == {"studio", "cli"}


# --- AUT-03, AUT-05, AUT-06 -----------------------------------------------------------------------------------------


def aut03_build_reproducible(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    result = api.reproducible(repo.pack)
    assert result["identical_table_hashes"] and result["identical_pack_bytes"]
    first = api.build_pack(repo.pack, repo.root / "first")
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    monkeypatch.chdir(repo.root)
    again = api.build_pack(repo.pack, repo.root / "elsewhere")
    assert again["table_hashes"] == first["table_hashes"], "the same sources build the same tables anywhere"


def aut03_canonical_form(repo: Repo) -> None:
    record = repo.record(ITEM)
    path = tree.save_record(repo.pack, "items", record)  # as the studio saves it (the same library)
    studio = path.read_bytes()
    messy = dict(reversed(list(record.items())))
    messy["stem"] = unicodedata.normalize("NFD", "Café cyclist: " + record["stem"])
    path.write_bytes(yaml.safe_dump(messy, sort_keys=True).replace("\n", "\r\n").encode())
    assert tree.format_tree(repo.pack) == [path]
    os.environ["JANA_AUTHOR"] = "author"
    try:
        assert cli.main(["--json", "edit", ITEM]) == cli.EXIT_OK  # the CLI rewrites it in canonical form
    finally:
        del os.environ["JANA_AUTHOR"]
    cli_bytes = path.read_bytes()
    assert b"\r\n" not in cli_bytes and unicodedata.is_normalized("NFC", cli_bytes.decode())
    roundtrip = yaml.safe_load(cli_bytes)
    assert tree.canonical(roundtrip, "items").encode() == cli_bytes, "canonical form is a fixed point"
    restored = {**roundtrip, "stem": record["stem"], "authoring": record["authoring"], "review": record["review"]}
    assert tree.canonical(restored, "items").encode() == studio


def aut05_cli_studio_parity(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    library = {
        "validate": [api.check("validate", repo.pack)],
        "verify": [api.check("verify", repo.pack)],
        "lint": [api.check("lint", repo.pack)],
        "coverage": [api.coverage(repo.pack)],
        "eval": [api.eval_pack(repo.pack)],
    }
    for command, expected in library.items():
        assert cli.main(["--json", command, "--pack", str(repo.pack)]) == cli.EXIT_OK
        printed = json.loads(capsys.readouterr().out)
        assert printed["results"] == json.loads(json.dumps(expected, default=str)), command


def aut05_verify_exit_codes(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    record = repo.record("itm.phy.o.motion.0002")
    record["parts"][0]["answer"]["value"] = "2.5"
    tree.save_record(repo.pack, "items", record)
    assert cli.main(["--json", "verify", "--pack", str(repo.pack)]) == cli.EXIT_FAIL
    problems = json.loads(capsys.readouterr().out)["results"][0]["problems"]
    assert any(p.startswith("itm.phy.o.motion.0002") and "result 2.0" in p for p in problems), problems
    assert cli.main(["--json", "verify", "--pack", str(PACK)]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["verify", "--no-such-flag"]) == cli.EXIT_USAGE


def aut06_merge_requires_gates(repo: Repo) -> None:
    base = _commit(repo, "clean content")
    assert api.ci(base)["ok"]
    record = repo.record("itm.phy.o.motion.0002")
    record["parts"][0]["answer"]["value"] = "2.5"  # a wrong key: the tools compute 2.0
    tree.save_record(repo.pack, "items", record)
    result = api.ci(base)
    assert not result["ok"]
    assert any(p.startswith("itm.phy.o.motion.0002") for p in result["packs"][0]["verify"])


def aut06_ci_cannot_read_held_out(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    from jana_tools.harness import lock

    with pytest.raises(lock.HeldOutInaccessibleError):
        lock.held_out_items("answer_oracles", "development", repo.root / "evals" / "held-out")
    assert api.held_out_guard() == []
    monkeypatch.setenv(heldout.KEY_ENV, lock.new_key())
    assert api.held_out_guard(), "a development CI job holding the release key fails"
    assert not api.ci(None)["ok"]


# --- AUT-17 to AUT-20 -----------------------------------------------------------------------------------------------


def aut17_offline_fallback(repo: Repo) -> None:
    from jana_tools.harness.egress import offline_run

    route = drafting.choose_route(online_drafting=False, cloud=None, local=None)
    assert route.kind == "template"
    record_id = _new_draft_item(repo)
    with offline_run() as egress:
        result = api.draft(repo.ctx("author"), "item_variants", record_id, "Another cyclist item", route)
    assert result["route"] == "template" and egress.attempts == []
    assert AuditLog(repo.home).entries()[-1]["outcome"] == "template"
    cloud = drafting.Route("cloud", "provider-model", "provider", "strong", lambda s, u: "")
    assert drafting.choose_route(online_drafting=False, cloud=cloud, local=None).kind == "template"
    assert cli.main(["--json", "draft", "item_variants", record_id, "--cloud"]) in (cli.EXIT_NETWORK, cli.EXIT_FAIL)


def aut18_model_numbers_recomputed(repo: Repo) -> None:
    record_id = _new_draft_item(repo)
    route, _ = _draft_route(answer="9.0")  # the tools compute 8.0
    result = api.draft(repo.ctx("author"), "item_variants", record_id, "A runner instead of a cyclist", route)
    assert result["fields"]["parts"]["status"] == "failed"
    with pytest.raises(ValueError, match="failed verification"):
        api.accept(repo.ctx("author"), record_id, ["parts"])
    refused = api.promote(repo.ctx("author"), repo.pack, [record_id])
    assert refused["verified"] == [] and any("failed verification" in p for p in refused["held"][0]["problems"])


def aut18_unaccepted_field_blocks(repo: Repo) -> None:
    record_id = _new_draft_item(repo)
    route, _ = _draft_route(answer="8.0")
    result = api.draft(repo.ctx("author"), "item_variants", record_id, "A runner instead of a cyclist", route)
    assert {f["status"] for f in result["fields"].values()} == {"passed"}
    api.accept(repo.ctx("author"), record_id, ["stem", "parts", "solution"])
    refused = api.promote(repo.ctx("author"), repo.pack, [record_id])
    assert refused["held"] == [
        {"record": record_id, "problems": [f"{record_id}: checks is an AI draft not yet accepted"]}
    ]
    api.accept(repo.ctx("author"), record_id, ["checks"])
    assert api.promote(repo.ctx("author"), repo.pack, [record_id])["verified"] == [record_id]


def aut19_pack_provenance_summary(repo: Repo, tmp_path: Path) -> None:
    record_id = _new_draft_item(repo)
    route, _ = _draft_route(answer="8.0")
    api.draft(repo.ctx("author"), "item_variants", record_id, "A runner", route)
    api.accept(repo.ctx("author"), record_id, ["stem", "parts", "solution", "checks"])
    fields = repo.record(record_id)["authoring"]["fields"]
    assert {f["origin"] for f in fields.values()} == {"ai_accepted"}
    assert all(f["model"] == "scripted-model" and f["prompt_sha256"] and f["inputs"] for f in fields.values())
    built = build(repo.pack, tmp_path / "out")
    item = next(i for i in json.loads(built.json_path.read_text())["items"] if i["id"] == record_id)
    assert item["provenance"]["drafted_with_ai"] is True and item["provenance"]["ai_model"] == "scripted-model"
    assert "fields" not in json.dumps(item), "field-level provenance stays in the authoring system"
    record = repo.record(record_id)
    record["provenance"] = {**record["provenance"], "drafted_with_ai": False}
    record["provenance"].pop("ai_model", None)
    tree.save_record(repo.pack, "items", record)
    assert any("AUT-19" in p for p in api.check("lint", repo.pack)["problems"])


def aut20_held_out_never_sent(repo: Repo) -> None:
    key = heldout_key()
    secret_item = {"id": "itm.phy.o.motion.0900", "stem": "A delivery van travels 2400 m north along a road in 300 s."}
    heldout.seal([secret_item], "answer_oracles", key, repo.root / "evals" / "held-out")
    route, calls = _draft_route(answer="8.0")
    record_id = _new_draft_item(repo)
    with pytest.raises(drafting.DraftBlocked, match="held-out"):
        api.draft(repo.ctx("author"), "item_variants", record_id, f"Make it like this: {secret_item['stem']}", route)
    with pytest.raises(drafting.DraftBlocked):
        api.draft(repo.ctx("author"), "item_variants", record_id, "Base it on itm.phy.o.motion.0900", route)
    assert calls == [], "nothing reached the model"
    with pytest.raises(drafting.DraftBlocked, match="allow-list"):
        drafting.build_request("hint_ladder", "x", {"items": [], "transcripts": []}, heldout.HeldOut())
    assert "review" not in drafting.build_request("hint_ladder", "x", {"items": [repo.record(ITEM)]},
                                                  heldout.HeldOut())[1]  # fmt: skip


def heldout_key() -> str:
    from jana_tools.harness.lock import new_key

    return new_key()


# --- AUT-21 to AUT-23 -----------------------------------------------------------------------------------------------


# --- AUT-29, AUT-30 -------------------------------------------------------------------------------------------------


def aut29_preview_matches_student(repo: Repo, tmp_path: Path) -> None:
    preview = build_preview(repo.pack, tmp_path / "preview")
    signed = _signed(repo.pack, tmp_path / "signed")
    _, preview_tables = read_pack(preview.pack_path)
    _, signed_tables = read_pack(signed.pack_path)
    assert {t: table_sha256(t, r) for t, r in preview_tables.items()} == {
        t: table_sha256(t, r) for t, r in signed_tables.items()
    }, "the student sees exactly the previewed records"
    with open_preview(preview.pack_path, hardware_class="low") as session:
        assert session.profile_dir.is_dir()
        statement = session.problem_statement(ITEM)
        assert statement.startswith("A cyclist rides 1200 m") and "(a) Calculate" in statement
        profile = session.profile_dir
    assert not profile.exists(), "the preview profile is deleted when the preview closes"


def _signed(pack: Path, out: Path) -> Any:
    from signing_service.keys import DEV_KEY_ID, dev_key

    return build(pack, out, key=dev_key(), key_id=DEV_KEY_ID)


def aut30_preview_pack_refused(repo: Repo, tmp_path: Path) -> None:
    preview = build_preview(repo.pack, tmp_path / "preview")
    for environment in (Environment.PRODUCTION, Environment.PILOT, Environment.DEV):
        with pytest.raises(PackRejectedError) as refused:
            verify(preview.pack_path, environment)
        assert refused.value.message_key == "pack.damaged"
    shelf = PackShelf(Environment.PRODUCTION)
    assert not shelf.install(preview.pack_path) and shelf.rejected
    with pytest.raises(NotAPreviewPack):
        with open_preview(_signed(repo.pack, tmp_path / "signed").pack_path):
            pass


# --- CUR-22, CUR-31 -------------------------------------------------------------------------------------------------


def cur22_held_out_never_shipped(repo: Repo, tmp_path: Path) -> None:
    store = repo.root / "evals" / "held-out"
    key = heldout_key()
    heldout.seal([repo.record(ITEM)], "answer_oracles", key, store)
    with pytest.raises(BuildError) as failed:
        build(repo.pack, tmp_path / "a")
    assert f"{ITEM}: a held-out item never ships in a student pack (CUR-22)" in failed.value.problems
    others = [p for p in failed.value.problems if p.startswith("itm.") and not p.startswith(ITEM)]
    assert others == [], "items sharing only KC and misconception ids with a held-out item are not near-duplicates"
    near = {"id": "itm.phy.o.motion.0950", "stem": repo.record("itm.phy.o.motion.0002")["stem"]}
    heldout.seal([near], "answer_oracles", key, store)
    with pytest.raises(BuildError) as failed:
        build(repo.pack, tmp_path / "b")
    assert any("itm.phy.o.motion.0002: repeats the wording of a held-out item" in p for p in failed.value.problems)
    # Named held-out items: every KC must reach the share, and no banked record may repeat their wording.
    os.environ[heldout.KEY_ENV] = key
    try:
        with pytest.raises(ValueError, match="held out of"):
            api.bank(repo.ctx("lead"), repo.pack, held_out_share=1.0, held_ids=[ITEM])
        twin = repo.record("itm.phy.o.motion.0002")
        tree.save_record(repo.pack, "items", {**twin, "stem": repo.record(ITEM)["stem"]})
        with pytest.raises(ValueError, match=r"itm\.phy\.o\.motion\.0002: repeats the wording of a held-out item"):
            api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0, held_ids=[ITEM])
        tree.save_record(repo.pack, "items", twin)
    finally:
        del os.environ[heldout.KEY_ENV]
    # Banking with a held-out share seals verified items out of the tree; it needs the release key.
    with pytest.raises(api.EnvironmentProblem):
        api.bank(repo.ctx("lead"), repo.pack, held_out_share=1.0)
    os.environ[heldout.KEY_ENV] = key
    try:
        (store / "answer_oracles.enc").unlink()
        moved = api.bank(repo.ctx("lead"), repo.pack, held_out_share=1.0)
    finally:
        del os.environ[heldout.KEY_ENV]
    assert moved["held_out"] and all(not (repo.pack / "items" / f"{i}.yaml").exists() for i in moved["held_out"])
    assert all(repo.record(i)["review"]["status"] == "in_eval_bank" for i in moved["in_eval_bank"])


def cur31_coverage_report_gates(repo: Repo) -> None:
    from agent_core.config import Settings

    report = api.coverage(repo.pack)
    assert not report["available"] and report["gaps"]
    assert report["per_kc"][0]["items"]["needed"] == Settings().coverage_s1_items_per_kc
    assert report["map"]["met"] and report["lessons"]["needed"] == Settings().coverage_s1_lessons
    source = api.load_source(repo.pack)
    tables = copy.deepcopy(source.tables)
    settings = Settings()
    for kc in [k for k in tables["kcs"] if k["status"] == "active"]:
        for table, need in (("items", settings.coverage_s1_items_per_kc),
                            ("worked_examples", settings.coverage_s1_worked_examples_per_kc),
                            ("misconceptions", settings.coverage_s1_misconceptions_per_kc)):  # fmt: skip
            for n in range(need):
                tables[table].append({"id": f"{table}.{kc['id']}.{n}", "kc_ids": [kc["id"]],
                                      "review": {"status": "published", "reviewers": []}})  # fmt: skip
    tables["lessons"].append({"id": "les.synthetic", "kc_ids": [], "review": {"status": "published"}})
    from pack_builder.coverage import report as coverage_report

    met = coverage_report(source.pack, tables, settings)
    assert met["available"] and met["gaps"] == []
    _s2_coverage_gates(settings)


def _s2_tables(settings: Any) -> dict[str, list[dict[str, Any]]]:
    """A synthetic chemistry pack that meets the S2 target exactly (TABLE CUR-31a): twelve topics, two KCs (one light
    enough to need no misconceptions), the S2 counts per KC, lessons on the highest-weight topics, the mock papers."""
    published = {"status": "published", "reviewers": []}
    weights = [0.2, 0.15, 0.1, 0.1, 0.1, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02]
    nodes = [{"id": "cur.chm.o", "kind": "subject", "parent_id": None, "order": 0}]
    nodes += [{"id": f"cur.chm.o.t{n:02d}", "kind": "topic", "parent_id": "cur.chm.o", "order": n, "exam_weight": w}
              for n, w in enumerate(weights, 1)]  # fmt: skip
    nodes.append({"id": "cur.chm.o.t01.sub", "kind": "subtopic", "parent_id": "cur.chm.o.t01", "order": 1})
    kcs = [{"id": "kc.chm.o.t01.heavy", "node_id": "cur.chm.o.t01.sub", "status": "active", "exam_weight": 0.08,
            "prerequisites": [{"kc_id": "kc.chm.o.t02.light", "strength": "required"},
                              {"kc_id": "kc.mth.o.algebra.ratio", "strength": "helpful"}]},
           {"id": "kc.chm.o.t02.light", "node_id": "cur.chm.o.t02", "status": "active", "exam_weight": 0.04,
            "prerequisites": []}]  # fmt: skip
    tables: dict[str, list[dict[str, Any]]] = {"curriculum_nodes": nodes, "kcs": kcs, "items": [],
                                               "worked_examples": [], "misconceptions": [], "lessons": [],
                                               "mock_papers": []}  # fmt: skip
    for kc in kcs:
        for n in range(settings.coverage_s2_items_per_kc):
            kind = "mcq_diagnostic" if n < settings.coverage_s2_diagnostic_items_per_kc else "numeric"
            tables["items"].append({"id": f"itm.{kc['id']}.{n}", "type": kind, "kc_ids": [kc["id"]],
                                    "review": published})  # fmt: skip
        for n in range(settings.coverage_s2_worked_examples_per_kc):
            tables["worked_examples"].append({"id": f"wex.{kc['id']}.{n}", "kc_ids": [kc["id"]], "review": published})
    for n in range(settings.coverage_s2_misconceptions_per_kc):
        tables["misconceptions"].append({"id": f"mc.heavy.{n}", "kc_ids": ["kc.chm.o.t01.heavy"], "review": published})
    for n in range(1, settings.coverage_s2_lesson_topics + 1):  # the topic or a subtopic below it
        node = "cur.chm.o.t01.sub" if n == 1 else f"cur.chm.o.t{n:02d}"
        tables["lessons"].append({"id": f"les.chm.o.t{n:02d}", "node_id": node, "review": published})
    for n in range(settings.coverage_s2_mock_papers):
        tables["mock_papers"].append({"id": f"mck.chm.o.{n:04d}", "review": published})
    return tables


def _s2_coverage_gates(settings: Any) -> None:
    from agent_core.store.catalogue import available, coverage_gaps
    from pack_builder.coverage import report as coverage_report

    full = _s2_tables(settings)
    assert coverage_gaps("S2", full, settings) == []
    pack = {"pack_id": "pack.chm.o", "subject": "chm", "level": "o"}
    shown = coverage_report(pack, full, settings)
    assert shown["stage"] == "S2" and shown["available"]  # chemistry is first produced in S2
    assert shown["mock_papers"] == {"published": 3, "authored": 3, "needed": settings.coverage_s2_mock_papers}
    assert shown["lessons"]["topics"] == [f"cur.chm.o.t{n:02d}" for n in range(1, 11)]
    light = next(r for r in shown["per_kc"] if r["kc_id"] == "kc.chm.o.t02.light")
    assert light["misconceptions"]["needed"] == 0 and light["diagnostic_items"]["published"] == 3

    def gaps(change: Any) -> list[str]:
        tables = copy.deepcopy(full)
        change(tables)
        return coverage_gaps("S2", tables, settings)

    assert gaps(lambda t: t["mock_papers"].pop()) == ["2 published mock papers, needs 3"]
    assert gaps(lambda t: t["mock_papers"][0].update(review={"status": "verified"})) == [
        "2 published mock papers, needs 3"]  # fmt: skip
    assert gaps(lambda t: t.pop("mock_papers")) == ["0 published mock papers, needs 3"]  # a pack without the table
    assert gaps(lambda t: t["items"].pop(0)) == [
        "kc.chm.o.t01.heavy: 9 published items, needs 10",
        "kc.chm.o.t01.heavy: 2 published diagnostic items, needs 3",
    ]
    assert gaps(lambda t: t["items"][0].update(type="mcq")) == [
        "kc.chm.o.t01.heavy: 2 published diagnostic items, needs 3"]  # fmt: skip
    assert gaps(lambda t: t["misconceptions"].pop()) == ["kc.chm.o.t01.heavy: 1 published misconceptions, needs 2"]
    assert gaps(lambda t: t["worked_examples"].pop()) == ["kc.chm.o.t02.light: 0 published worked examples, needs 1"]
    # A lesson on a topic outside the ten highest-weight ones does not count for them.
    assert gaps(lambda t: t["lessons"][9].update(node_id="cur.chm.o.t11")) == [
        "cur.chm.o.t10: no published lesson (one of the 10 highest-weight topics)"]  # fmt: skip
    assert gaps(lambda t: t["kcs"][1].update(node_id="cur.chm.o.t99")) == ["kc.chm.o.t02.light: not on the map"]
    assert gaps(lambda t: t["kcs"][0]["prerequisites"].append({"kc_id": "kc.chm.o.t03.gone"})) == [
        "kc.chm.o.t01.heavy: prerequisite kc.chm.o.t03.gone is not an active KC of the pack"]  # fmt: skip
    # Availability is decided per subject: the pack that meets its target is shown, the other hidden.
    short = copy.deepcopy(full)
    short["mock_papers"] = []
    assert [(a.subject, a.level) for a in available("S2", {"pack.chm.o": full, "pack.acc.o": short}, settings)] == [
        ("chm", "o")]  # fmt: skip
    assert coverage_gaps("S3", full, settings) == ["no coverage target is defined for S3 yet"]


# --- AUT-33 ---------------------------------------------------------------------------------------------------------


def _ready_to_publish(repo: Repo) -> None:
    """Every record passed the automated gates (verified) and enters the evaluation bank; no approval (D65)."""
    api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)


def aut33_service_rechecks_gates(repo: Repo) -> None:
    from signing_service.service import process_inbox

    _ready_to_publish(repo)
    weak = "itm.phy.o.motion.0003"
    record = repo.record(weak)
    original = copy.deepcopy(record)
    record["review"]["status"] = "verified"  # passes every CI check, but never entered the evaluation bank
    record["authoring"]["history"] = ["drafted", "verified"]
    tree.save_record(repo.pack, "items", record)
    forged = _commit(repo, "ready, with one record not banked")
    assert api.ci(None)["ok"], "CI's own checks pass"
    api.publish(repo.ctx("lead"), repo.pack, "dev", commit=forged)
    outcomes = process_inbox(api.inbox(repo.home), repo.root, repo.root / "out", repo.home)
    assert outcomes[0]["status"] == "refused"
    assert any(p.startswith(f"{weak}: verified but not yet in the evaluation bank") for p in outcomes[0]["problems"])
    # Banked again, the request is signed: the pack verifies in a development build, and the banked records are
    # published by the signing.
    tree.save_record(repo.pack, "items", original)
    fixed = _commit(repo, "banked")
    api.publish(repo.ctx("lead"), repo.pack, "dev", commit=fixed)
    outcomes = process_inbox(api.inbox(repo.home), repo.root, repo.root / "out", repo.home)
    assert outcomes[0]["status"] == "signed", outcomes
    manifest = verify(Path(outcomes[0]["pack"]), Environment.DEV)
    assert manifest["signature"]["key_id"] == "key_dev_test"
    _, tables = read_pack(Path(outcomes[0]["pack"]))
    assert {r["review"]["status"] for r in tables["items"]} == {"published"}
    version = tree.read_pack(repo.pack)[0]["version"]
    release = json.loads((repo.root / "out" / "releases" / "pack.phy.o" / f"{version}.release.json").read_text())
    assert release["commit"] == fixed and set(release["published_records"]) == set(_all_reviewed(repo))
    # The release is carried back into the source tree: exactly its records become published (AUT-03, CUR-19).
    released = repo.root / "out" / "releases" / "pack.phy.o" / f"{version}.release.json"
    recorded = api.record_release(repo.ctx("lead"), released)
    assert set(recorded["published"]) == set(release["published_records"])
    assert {repo.record(i)["review"]["status"] for i in _all_reviewed(repo)} == {"published"}
    assert all(repo.record(i)["authoring"]["history"][-1] == "published" for i in _all_reviewed(repo))


def aut33_no_keys_in_toolchain() -> None:
    markers = ("PRIVATE KEY", "from_private_bytes", "_DEV_PHRASE", "signing_service", "dev_key(")
    toolchain = [REPO / "services" / "pack-builder" / "pack_builder", REPO / "content", REPO / "skills"]
    toolchain += [p for p in (REPO / "apps" / "studio",) if p.exists()]
    found = []
    for base in toolchain:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".yaml", ".yml", ".json", ".toml", ".md", ".ts", ".pem"):
                text = path.read_text(errors="replace")
                # Public trust-role metadata and contract references may name the service; executable imports,
                # private-key operations and key material remain forbidden, including in a staged frozen backend.
                checked = tuple(m for m in markers if m != "signing_service" or path.suffix != ".json")
                found += [f"{path.relative_to(REPO)}: {m}" for m in checked if m in text]
            if path.name == "signing_service" or (
                path.is_file() and path.suffix == ".pem" and path.is_relative_to(REPO / "services" / "pack-builder")
            ):
                found.append(str(path.relative_to(REPO)))
    assert found == [], found
    pyproject = (REPO / "services" / "pack-builder" / "pyproject.toml").read_text()
    assert "signing-service" not in pyproject, "the authoring toolchain does not depend on the signing service"
