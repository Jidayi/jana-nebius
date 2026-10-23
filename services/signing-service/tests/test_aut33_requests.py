"""The signing service accepts only well-formed publish requests that their named requester authenticated (AUT-33):
a commit is a commit id (never an option git would read, such as `--remote=`), the pack folder is inside the exported
content tree, ids and versions are plain names, and an inbox request carries its requester's MAC and is handled once.
Accounts and requests are synthetic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pack_builder.accounts import Accounts, request_mac
from signing_service.service import Refused, export_commit, handle, process_inbox, request_problems

GOOD = {
    "request_id": "pubreq_0123456789abcdef",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "pack_id": "pack.phy.o",
    "version": "0.2.0",
    "channel": "dev",
    "pack_dir": "content/curriculum/phy/o",
}


def test_aut33_request_fields_validated() -> None:
    assert request_problems(GOOD) == []
    bad = {
        "commit": ["--remote=/elsewhere", "HEAD", "main; rm -rf /", ""],
        "pack_dir": ["/Users/someone/elsewhere", "content/curriculum/../../secrets", "evals/held-out", "..\\x"],
        "pack_id": ["../../escape", "Pack ID", ""],
        "version": ["1.0", "../1.0.0", "1.0.0-beta"],
        "channel": ["nightly", None],
        "request_id": ["../../x", "a" * 65],
    }
    for name, values in bad.items():
        for value in values:
            assert request_problems({**GOOD, name: value}), (name, value)
    assert request_problems(["not", "an", "object"])


def test_aut33_git_options_never_reach_git(tmp_path: Path) -> None:
    with pytest.raises(Refused):
        export_commit(tmp_path, "--remote=" + str(tmp_path / "other"), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_aut33_handle_refuses_malformed_request_before_export(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="pack_dir"):
        elsewhere = str(tmp_path / "elsewhere")
        handle({**GOOD, "pack_dir": elsewhere}, tmp_path / "no-repo", tmp_path / "out", authoring_home=tmp_path)


def _lead(home: Path) -> tuple[str, str]:
    account = Accounts(home).create("lead", "Synthetic Lead", "lead@example.invalid", ["curriculum_lead"])
    return account.rev_id, account.totp_secret


def test_aut33_inbox_requests_authenticated(tmp_path: Path) -> None:
    """An unsigned request, one signed with another key, one altered after signing and a replay are all refused
    without reaching the gates (no repository is needed to refuse them)."""
    home = tmp_path / "home"
    rev_id, secret = _lead(home)
    inbox = home / "signing" / "inbox"
    inbox.mkdir(parents=True)
    named = {**GOOD, "requested_by": {"role_id": rev_id}}
    signed = {**named, "mac": request_mac(secret, named)}
    unsigned_other = {**named, "request_id": "pubreq_other"}
    other = {**unsigned_other, "mac": request_mac("A" * 32, unsigned_other)}
    altered = {**signed, "request_id": "pubreq_altered", "channel": "stable"}
    for name, request in {"a": named, "b": other, "c": altered}.items():
        (inbox / f"{name}.json").write_text(json.dumps(request))
    (inbox / "d.json").write_text("{not json")
    outcomes = process_inbox(inbox, tmp_path / "no-repo", tmp_path / "out", home)
    assert [o["status"] for o in outcomes] == ["refused"] * 4
    assert all("not authenticated" in o["problems"][0] or "JSON object" in o["problems"][0] for o in outcomes)

    (home / "signing" / "done").mkdir()
    (home / "signing" / "done" / "earlier.json").write_text(json.dumps({**signed, "outcome": {"status": "signed"}}))
    (inbox / "replay.json").write_text(json.dumps(signed))
    (replayed,) = process_inbox(inbox, tmp_path / "no-repo", tmp_path / "out", home)
    assert replayed["status"] == "refused" and "handled already" in replayed["problems"][0]


def test_aut33_vanished_request_skipped(tmp_path: Path) -> None:
    """A request listed in the inbox but gone before it is read (withdrawn, or taken by another run) is skipped: no
    refusal is written for it and the rest of the inbox is still handled."""
    home = tmp_path / "home"
    _lead(home)
    inbox = home / "signing" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "a.json").symlink_to(tmp_path / "gone.json")  # listed by the glob, missing when read
    (inbox / "b.json").write_text("{not json")
    outcomes = process_inbox(inbox, tmp_path / "no-repo", tmp_path / "out", home)
    assert [o["request_id"] for o in outcomes] == ["b"]
    assert not (home / "signing" / "refused" / "a.json").exists()
