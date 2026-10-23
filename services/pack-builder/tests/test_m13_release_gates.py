"""M13.c at the signing service: the content safety review (CUR-27) and the pack evaluation gate (EVL-25).

Each test works on the throwaway authoring repository of the M8 tests (a few physics records, invented accounts). The
safety reviews here are fixtures signed with the development reviewer key, which is derived from a published phrase
and proves nothing about any content: no real review is recorded or claimed."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from pack_builder import api, scan
from pack_builder import coverage as cov
from pack_builder import safety_review as review
from pack_builder import source as tree
from pack_builder.accounts import Accounts
from pack_builder.build import load_source
from signing_service import service
from signing_service.safety_review import (
    DEV_REVIEWER_KEY_ID,
    dev_reviewer_key,
    development_reviewers,
    review_problems,
    sign_review,
    trusted_reviewers,
)
from test_m8_authoring import Repo, _commit
from test_m8_authoring import repo as authoring_repo  # noqa: F401 - the authoring repository fixture

REPO = Path(__file__).resolve().parents[3]
SETTINGS = Settings()
SIGNED_AT = "2026-10-13T12:00:00.000Z"


def _request(repo: Repo, commit: str, channel: str) -> dict[str, Any]:
    pack = load_source(repo.pack).pack
    return {"request_id": f"req_{channel}_{commit[:8]}", "commit": commit, "pack_id": pack["pack_id"],
            "version": pack["version"], "channel": channel, "pack_dir": "content/curriculum/phy/o",
            "requested_by": {"role_id": Accounts(repo.home).get("lead").rev_id}}  # fmt: skip


def _sample(repo: Repo) -> review.Sample:
    source = load_source(repo.pack)
    lists = scan.lists_for(repo.pack)
    assert lists is not None
    return review.sample(source.pack, source.tables, None, lists, SETTINGS)


def _write_review(repo: Repo, document: dict[str, Any]) -> None:
    path = review.review_path(repo.root / "content" / "curriculum", document["pack_id"], document["version"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, sort_keys=True))


def _pilot_slice(repo: Repo) -> None:
    """A pilot pack needs a published item and worked example on every active KC (CUR-04): the fixture keeps the KCs
    its few records cover, and every reference stays inside them."""
    _, found = tree.read_pack(repo.pack)
    covered = {k for t in ("items", "worked_examples") for r in found[t] for k in r.record["kc_ids"]}
    both = {k for k in covered if any(k in r.record["kc_ids"] for r in found["items"])
            and any(k in r.record["kc_ids"] for r in found["worked_examples"])}  # fmt: skip
    for table in ("items", "worked_examples", "misconceptions"):
        for located in found[table]:
            record = located.record
            kept = [k for k in record["kc_ids"] if k in both]
            if not kept:
                located.path.unlink()
            elif kept != record["kc_ids"]:
                tree.save_record(repo.pack, table, {**record, "kc_ids": kept})
    kcs = [k.record for k in found["kcs"] if k.record["id"] in both]
    for kc in kcs:
        kc["prerequisites"] = [e for e in kc["prerequisites"] if e["kc_id"] in both]
    tree.write_table(repo.pack, "kcs", kcs)


def cur27_safety_review_signed(authoring_repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    repo = authoring_repo
    _pilot_slice(repo)
    # The sample: every new record on a sensitive topic, plus the configured share of the rest, in a fixed order.
    sensitive = "itm.phy.o.motion.0003"
    record = repo.record(sensitive)
    record["stem"] = f"{record['stem']} A hospital uses a similar fall time to time a cancer treatment."
    tree.save_record(repo.pack, "items", record)
    wanted = _sample(repo)
    assert sensitive in wanted.sensitive and sensitive in wanted.records
    others = len(wanted.records) - len(wanted.sensitive)
    share = SETTINGS.safety_review_sample_share
    assert others == min(math.ceil(share * wanted.new), wanted.new - len(wanted.sensitive))
    assert wanted.records == _sample(repo).records, "anyone can recompute the sample"
    source = load_source(repo.pack)
    lists = scan.lists_for(repo.pack)
    assert lists is not None
    assert review.sample(source.pack, source.tables, source.tables, lists, SETTINGS).records == {}, (
        "an unchanged release has nothing new to review")  # fmt: skip

    # The gate itself: a missing, untrusted, tampered or incomplete review keeps the release from publication.
    fixture = sign_review(wanted.unsigned("rev_safety_fixture", SIGNED_AT), dev_reviewer_key(), DEV_REVIEWER_KEY_ID)
    dev = development_reviewers()
    assert review_problems(None, wanted, dev) == [f"{wanted.pack_id} {wanted.version}: no signed content safety "
                                                  "review (CUR-27)"]  # fmt: skip
    assert review_problems(fixture, wanted, dev) == []
    assert trusted_reviewers() == {}, "no reviewer is trusted for pilot or stable until the owner adds their key"
    assert review_problems(fixture, wanted, trusted_reviewers()) == [
        f"the safety review is signed by {DEV_REVIEWER_KEY_ID}, not a trusted reviewer (CUR-27)"]  # fmt: skip
    tampered = {**fixture, "records": [{**r, "decision": "approved"} for r in fixture["records"]][1:]}
    assert any("does not verify" in p for p in review_problems(tampered, wanted, dev))
    rejected = dict(fixture["records"][0], decision="changes_requested")
    held = sign_review({**fixture, "records": [rejected, *fixture["records"][1:]]}, dev_reviewer_key(),
                       DEV_REVIEWER_KEY_ID)  # fmt: skip
    assert review_problems(held, wanted, dev) == [
        f"{rejected['id']}: the safety review did not approve it (changes_requested) (CUR-27)"]  # fmt: skip

    # Through the signing service: a pilot release is refused without a signed review, and signed with one.
    monkeypatch.setattr(service.cov, "report", lambda *a, **k: {"gaps": []})  # coverage is CUR-31's gate, not this
    api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)
    unreviewed = _commit(repo, "banked, not reviewed")
    out = tmp_path / "out"
    with pytest.raises(service.Refused) as refused:
        service.handle(_request(repo, unreviewed, "pilot"), repo.root, out, authoring_home=repo.home,
                       reviewers=dev)  # fmt: skip
    assert f"{wanted.pack_id} {wanted.version}: no signed content safety review (CUR-27)" in refused.value.problems
    _write_review(repo, sign_review(_sample(repo).unsigned("rev_safety_fixture", SIGNED_AT), dev_reviewer_key(),
                                    DEV_REVIEWER_KEY_ID))  # fmt: skip
    reviewed = _commit(repo, "a fixture safety review signed with the development reviewer key")
    with pytest.raises(service.Refused) as untrusted:  # the default trust holds no development key
        service.handle(_request(repo, reviewed, "pilot"), repo.root, out, authoring_home=repo.home)
    assert any("not a trusted reviewer" in p for p in untrusted.value.problems)
    # A sampled record changed after its review needs a new review.
    changed = repo.record(sensitive)
    changed["stem"] = changed["stem"].replace("hospital", "clinic")
    tree.save_record(repo.pack, "items", changed)
    after = _commit(repo, "a reviewed record changed")
    with pytest.raises(service.Refused) as stale:
        service.handle(_request(repo, after, "pilot"), repo.root, out, authoring_home=repo.home, reviewers=dev)
    assert f"{sensitive}: changed since its safety review (CUR-27)" in stale.value.problems
    tree.save_record(repo.pack, "items", record | {"review": changed["review"], "authoring": changed["authoring"]})
    restored = _commit(repo, "the reviewed wording again")
    release = service.handle(_request(repo, restored, "pilot"), repo.root, out, authoring_home=repo.home,
                             reviewers=dev)  # fmt: skip
    assert release.record["channel"] == "pilot"
    assert release.record["safety_review"]["required"] and release.record["safety_review"]["signed_off"]
    assert release.record["safety_review"]["sensitive"] >= 1


def evl25_pack_signing_gate(authoring_repo: Repo, tmp_path: Path) -> None:  # noqa: F811
    repo = authoring_repo
    api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)
    rid = "wex.phy.o.motion.0002"
    good = repo.record(rid)
    wrong = json.loads(json.dumps(good))
    wrong["final_answer"]["latex"] = "4.0\\ \\text{m/s}^2"  # the tool's result is 3.0
    tree.save_record(repo.pack, "worked_examples", wrong)
    failing = _commit(repo, "a worked solution with a wrong final answer")
    out = tmp_path / "out"
    with pytest.raises(service.Refused) as refused:
        service.handle(_request(repo, failing, "dev"), repo.root, out, authoring_home=repo.home)
    assert any(p.startswith(f"{rid}: final answer 4.0") for p in refused.value.problems), refused.value.problems
    assert not (out / "build").exists(), "nothing is signed or written for a refused pack"
    # A failing step of an item's worked solution is refused the same way.
    tree.save_record(repo.pack, "worked_examples", good)
    item = repo.record("itm.phy.o.motion.0001")
    step = item["solution"]["steps"][-1]
    step["latex"] = f"{step['latex']} = 7.5"
    tree.save_record(repo.pack, "items", item)
    step_failing = _commit(repo, "a worked solution step showing an unchecked number")
    with pytest.raises(service.Refused) as refused_step:
        service.handle(_request(repo, step_failing, "dev"), repo.root, out, authoring_home=repo.home)
    assert any("itm.phy.o.motion.0001: solution step" in p and "7.5" in p for p in refused_step.value.problems)
    item["solution"]["steps"][-1]["latex"] = step["latex"].removesuffix(" = 7.5")
    tree.save_record(repo.pack, "items", item)
    fixed = _commit(repo, "worked solutions verified again")
    release = service.handle(_request(repo, fixed, "dev"), repo.root, out, authoring_home=repo.home)
    assert release.record["channel"] == "dev" and release.pack_path.is_file()
    assert not release.record["safety_review"]["required"], "the development channel needs no safety review"


def test_aut33_coverage_counts_banked_edits_as_released(authoring_repo: Repo) -> None:  # noqa: F811
    """The pilot and stable coverage gate counts the pack the release publishes: a banked new version of a published
    item (an edit, CUR-19) is published by this release, so it counts as its published version did and re-releasing
    banked edits is not refused as lost coverage (AUT-33, CUR-31). A record still at `verified` is not counted."""
    repo = authoring_repo
    api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)
    _, found = tree.read_pack(repo.pack)
    for table in ("items", "worked_examples", "misconceptions"):  # as `aut record-release` leaves a signed release
        for located in found[table]:
            record = located.record
            history = [*record["authoring"]["history"], "published"]
            tree.save_record(repo.pack, table, {**record, "review": {**record["review"], "status": "published"},
                                                "authoring": {**record["authoring"], "history": history}})  # fmt: skip
    item_id = "itm.phy.o.motion.0001"
    kc = repo.record(item_id)["kc_ids"][0]

    def published_items(tables: dict[str, list[dict[str, Any]]]) -> int:
        report = cov.report(load_source(repo.pack).pack, tables, SETTINGS)
        return int(next(r for r in report["per_kc"] if r["kc_id"] == kc)["items"]["published"])

    before = published_items(load_source(repo.pack).tables)
    api.touch(repo.ctx("author"), item_id)
    api.promote(repo.ctx("author"), repo.pack, [item_id])
    verified = load_source(repo.pack)
    assert published_items(service.as_released(verified.tables)) == before - 1, "a verified edit is not released"
    api.bank(repo.ctx("lead"), repo.pack, held_out_share=0.0)
    banked = load_source(repo.pack)
    assert repo.record(item_id)["review"]["status"] == "in_eval_bank"
    assert published_items(banked.tables) == before - 1, "the source alone lacks the banked version"
    assert published_items(service.as_released(banked.tables)) == before
    gaps = cov.report(banked.pack, service.as_released(banked.tables), SETTINGS)["gaps"]
    assert service.coverage_problems(banked.pack, banked.tables, SETTINGS) == [f"coverage: {g}" for g in gaps]
