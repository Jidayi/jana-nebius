"""Private study notes on a shared computer (D102, JRN-11's lab; STU-15, API 1.10 and D104): a note the student marks
private is listed without its text, never matched by a search, and opened only through the confirm step; there is no
PIN or code (D86), and the mark is the note's own `private` column, so it goes with the note. Every note here is
synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent_core.contracts import errors
from api_harness import stop_core
from journey_harness import core, learner, restart, scripted, session, start
from test_m10a_profiles import Api
from test_m13g_learn import Client

TEXT = "Revise the circuit rules before Friday: series current is the same everywhere"


def listed_ok(body: object) -> list[str]:
    return [e for e in [errors("api/commands#/$defs/StudyNoteList", body)] if e]


def stu15_private_note_listed_without_text(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with core(tmp_path, provider=scripted({})) as r:
            c, _ = await learner(r, "Ama")
            sid = await session(c)
            saved = await c.ok("POST", f"/v1/sessions/{sid}/study/notes", {"type": "save_note", "text": TEXT})
            note = saved["note_id"]
            listed = await c.ok("GET", "/v1/study/notes")
            assert listed["notes"] == [saved], "a note not marked private is the study_note contract's shape"
            assert not listed_ok(listed)
            marked = await c.send("PATCH", f"/v1/study/notes/{note}", {"private": True})
            assert marked.status_code == 200 and marked.json()["private"] and marked.json()["text"] is None
            assert not errors("api/commands#/$defs/StudyNoteListed", marked.json())
            listed = await c.ok("GET", "/v1/study/notes")
            assert [(n["note_id"], n["private"], n["text"]) for n in listed["notes"]] == [(note, True, None)]
            assert not listed_ok(listed)
            assert (await c.ok("GET", "/v1/study/notes?q=circuit"))["notes"] == [], "no search inside a private note"
            closed = await c.send("POST", f"/v1/study/notes/{note}/open", {})
            assert closed.status_code == 422 and closed.json()["error"]["details"]["reason"] == "confirm_needed"
            opened = await c.ok("POST", f"/v1/study/notes/{note}/open", {"confirm": True})
            assert opened["text"] == TEXT and opened["private"]
            assert not errors("voice/activities#/$defs/study_note", opened)
            stored = r.runtime.learner.conn.execute("SELECT private FROM study_notes WHERE note_id = ?", (note,))
            assert stored.fetchone() == (1,), "the mark is the note's column (D104)"
            assert not list(r.data_dir.rglob("study-notes-private.json")), "no side file"
            unmarked = await c.send("PATCH", f"/v1/study/notes/{note}", {"private": False})
            assert unmarked.json()["text"] == TEXT and "private" not in unmarked.json()
            await c.send("PATCH", f"/v1/study/notes/{note}", {"private": True})
            deleted = await c.send("DELETE", f"/v1/study/notes/{note}", None)
            assert deleted.status_code == 204, deleted.text
            for refused in ({"private": "yes"}, {}, {"private": True, "text": "x"}):
                assert (await c.send("PATCH", f"/v1/study/notes/{note}", refused)).status_code == 422
            assert (await c.send("POST", f"/v1/study/notes/{note}/open", {"confirm": "yes"})).status_code == 422

    asyncio.run(scenario())


def test_d104_side_file_marks_move_into_the_column(tmp_path: Path) -> None:
    """DAT-12, D104: the private-note ids a core before API 1.10 kept beside the learner database become the notes'
    `private` column the first time the notes are read, and the side file is removed."""

    async def scenario() -> None:
        r = await start(tmp_path, provider=scripted({}))
        try:
            c, profile_id = await learner(r, "Ama")
            sid = await session(c)
            kept = await c.ok("POST", f"/v1/sessions/{sid}/study/notes", {"type": "save_note", "text": TEXT})
            other = await c.ok("POST", f"/v1/sessions/{sid}/study/notes", {"type": "save_note", "text": "Moles first"})
            rows = r.runtime.learner.conn.execute("PRAGMA database_list").fetchall()
            folder = Path(next(row[2] for row in rows if row[1] == "main")).parent
            r = await restart(r, provider=scripted({}))
            side = folder / "study-notes-private.json"  # as a core before API 1.10 left it: ids only
            side.write_text(json.dumps({"note_ids": [kept["note_id"], "nt_" + "0" * 26]}))
            c = Client(r, await Api(r).token(profile_id))
            listed = {n["note_id"]: n for n in (await c.ok("GET", "/v1/study/notes"))["notes"]}
            assert listed[kept["note_id"]]["private"] and listed[kept["note_id"]]["text"] is None
            assert listed[other["note_id"]] == other, "a note the file did not name is unchanged"
            assert not side.exists(), "the side file is removed once its marks are in the column"
        finally:
            await stop_core(r)

    asyncio.run(scenario())
