"""One registry of every per-profile store, walked by profile deletion and by the retention job (DAT-08, DAT-09,
DAT-14, MEM-22). These tests fail when a store is added without being registered: a retention row no store claims, an
eraser nothing registers, or a file that holds a profile's text outside every registered place. Synthetic data."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.store.profile_stores import ERASERS, NONE, PROFILE_STORES, Erasers, UnknownStore, retention_order
from agent_core.store.retention import RULES, ordered_rules
from api_harness import STATEMENT, ask, cli, start_core, stop_core
from test_m10a_profiles import Api, student

CANARY = "A trolley qz9erase rolls 40 m in 8 s. How fast is it on average?"
NOTE = "Revise speed qz9erase before Friday"


def test_every_retention_row_belongs_to_one_store() -> None:
    """Every row of TABLE DAT-08a is claimed by exactly one registered store, and the retention job applies them in
    the registry's order; every store names an eraser of the registry, or says why it needs none."""
    claimed = retention_order()
    assert len(claimed) == len(set(claimed)), "a retention row is claimed twice"
    assert set(claimed) == {rule.row_class for rule in RULES}, "every retention row needs a store in the registry"
    assert [rule.row_class for rule in ordered_rules()] == claimed
    for store in PROFILE_STORES:
        assert store.erased_by in (*ERASERS, NONE), store.name
        assert store.rule is not None or store.lifetime, f"{store.name}: a retention row or a lifetime"
        assert store.erased_by or store.lifetime, f"{store.name}: an eraser, or why it needs none"
    assert len({store.name for store in PROFILE_STORES}) == len(PROFILE_STORES)


def test_an_unlisted_store_cannot_register_an_eraser() -> None:
    erasers = Erasers()
    with pytest.raises(UnknownStore):
        erasers.register("a new cache", lambda _profile: None)


def _holders(data_dir: Path, needles: tuple[str, ...]) -> list[str]:
    """Every file under the data folder whose name or bytes hold one of the needles, relative to the folder."""
    found = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir).as_posix()
        data = path.read_bytes()
        if any(n in relative or n.encode() in data for n in needles):
            found.append(relative)
    return found


def _registered(relative: str, folder: str) -> bool:
    """Whether a file lies in a place a registered store names (a database with its -wal and -shm, or a folder)."""
    for store in PROFILE_STORES:
        where = store.where.replace("{profile}", folder)
        if relative == where or relative.startswith((where + "-", where + "/")):
            return True
    return False


async def _wait_idle(r: Any, session: str) -> None:
    for _ in range(600):
        entry = r.core.sessions.get(session)
        if entry is not None and (entry.task is None or entry.task.done()):
            return
        await asyncio.sleep(0.05)


def test_profile_text_lives_only_in_registered_stores(tmp_path: Path) -> None:
    """A profile's text (a turn, a study note, a typed capture, a saved question) lands only in places the registry
    names; deleting the profile walks every eraser (the model caches included) and leaves none of it on disk."""
    cleared: list[str] = []

    async def scenario() -> tuple[str, list[str], list[str]]:
        r = await start_core(tmp_path)
        api = Api(r)

        async def clear_cache() -> None:
            cleared.append("kv")

        r.core.cache_clearers.append(clear_cache)
        try:
            assert r.core.erasers.missing() == [], "an assembled core registers every eraser"
            profile = await api.add(student("Ama"))
            token = await api.token(profile)
            body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                    "origin": {"kind": "ask", "ref": None}}  # fmt: skip
            session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
            started = await api.call("POST", f"/v1/sessions/{session}/turns", ask(CANARY), profile=token)
            assert started.status_code in (200, 202), started.text
            await _wait_idle(r, session)
            note = await api.call("POST", f"/v1/sessions/{session}/study/notes", {"type": "save_note", "text": NOTE},
                                  profile=token)  # fmt: skip
            assert note.status_code == 200, note.text
            key = cli()
            capture = await api.call("POST", "/v1/captures", {"client_capture_id": key, "source": "typed",
                                                              "purpose": "question", "session_id": session,
                                                              "text": CANARY}, profile=token,
                                     headers={"content-type": "application/json", "idempotency-key": key})  # fmt: skip
            assert capture.status_code in (200, 202), capture.text
            await asyncio.sleep(0.5)  # the trace writer is asynchronous
            before = _holders(tmp_path, ("qz9erase",))
            cleared.clear()
            deleted = await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)
            assert deleted.status_code == 200 and deleted.json()["deleted"] is True, deleted.text
            assert not [e for e in r.core.sessions.values() if e.profile_id == profile]
            # The note's stored reply named neither the profile nor its id; it goes with the profile all the same.
            assert not [k for k, v in r.core.idempotency.entries.items() if "qz9erase" in json.dumps(v.body)]
            return profile[4:], before, _holders(tmp_path, ("qz9erase",))
        finally:
            await stop_core(r)

    folder, before, after = asyncio.run(scenario())
    assert before, "the profile's text was written somewhere"
    unregistered = [path for path in before if not _registered(path, folder)]
    assert not unregistered, f"list these stores in agent_core/store/profile_stores.py: {unregistered}"
    assert after == [], f"profile deletion left the profile's text in: {after}"
    assert cleared == ["kv"], "deletion clears the model runtime's caches (DAT-14)"
    assert STATEMENT  # the harness's own statement is not this profile's
