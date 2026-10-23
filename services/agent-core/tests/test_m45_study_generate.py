"""M45.b (STU-21, STU-22, D118): the Generate panel's settings reach the generator and are enforced, My Sets keeps
each aid's progress across a restart, and chapters cover a recording in order with citations that seek."""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import struct

import pytest
from agent_core.config import Settings
from agent_core.contracts import errors
from agent_core.engine.study import StudyDesk, StudyError, StudyQueue, digest
from agent_core.engine.study_topics import material_topics
from agent_core.store.sqlite import open_database

NOW = 1792281600000
NOTES = (
    "Enzymes\n\nEnzymes are biological catalysts that speed up reactions.\n\n"
    "Enzymes work best at an optimum temperature.\n\n"
    "Respiration\n\nRespiration releases energy from glucose in cells.\n\n"
    "Aerobic respiration needs oxygen."
)
SYLLABUS = "Syllabus: Section 2 covers enzymes and their optimum temperature."


def span(chunk, quote=None, text=None):
    quote = quote or chunk["text"][: min(40, len(chunk["text"]))]
    start = chunk["text"].index(quote)
    return {
        "text": text or quote,
        "citations": [
            {
                "source_id": chunk["source_id"],
                "revision": chunk["revision"],
                "chunk_id": chunk["chunk_id"],
                "start": start,
                "end": start + len(quote),
                "quote": quote,
            }
        ],
    }


class Recorder:
    """A scripted local model that records every request and returns every quiz type, for the engine to filter."""

    def __init__(self):
        self.requests: list[tuple[dict, list[dict]]] = []

    async def local_ready(self):
        return True

    async def study_generate(self, identity, request, chunks):
        self.requests.append((json.loads(json.dumps(request)), chunks))
        c = chunks[0]
        out = {"request_id": identity, "kind": request["kind"], "claims": [span(x) for x in chunks]}
        if request["kind"] == "flashcards":
            out["flashcards"] = [{"front": span(c, text="What are enzymes?"), "back": span(c)}]
        if request["kind"] == "quiz":
            out["quiz"] = {
                "items": [
                    {
                        "item_id": "a",
                        "type": "choice",
                        "stem": span(c, text="Which are catalysts?"),
                        "options": [{"option_id": "x", "text": "Enzymes"}, {"option_id": "y", "text": "Glucose"}],
                    },
                    {"item_id": "b", "type": "fill_blank", "stem": span(c, text="____ are biological catalysts.")},
                    {"item_id": "c", "type": "true_false", "stem": span(c, text="Enzymes speed up reactions.")},
                    {
                        "item_id": "d",
                        "type": "multi_select",
                        "stem": span(c, text="Which of these speed up reactions?"),
                        "options": [{"option_id": "p", "text": "Enzymes"}, {"option_id": "q", "text": "Water"}],
                    },
                ],
                "keys": [
                    {"item_id": "a", "answer": "x", "explanation": span(c), "marking": "judged"},
                    {"item_id": "b", "answer": "Enzymes", "explanation": span(c), "marking": "judged"},
                    {"item_id": "c", "answer": "true", "explanation": span(c), "marking": "judged"},
                    {"item_id": "d", "answer": "p", "explanation": span(c), "marking": "judged"},
                ],
            }
        if request["kind"] == "chapters":
            out["chapters"] = [
                {
                    "start_ms": x["locator"]["start_ms"] + 500,
                    "end_ms": x["locator"]["end_ms"] - 500,
                    "title": f"Part {i + 1}",
                    "summary": [span(x)],
                }
                for i, x in enumerate(chunks)
            ]
        return out, True

    async def study_support(self, request, chunks, output):
        n = len(output["claims"]) + len(output.get("flashcards", [])) + len(output.get("quiz", {}).get("items", []))
        return [True] * n, True


def desk_at(path):
    conn, _ = open_database(path / "learner.db", "learner")
    return StudyDesk(conn, lambda: NOW, Settings(study_offline_enabled=True))


def run(desk, model, body):
    job = desk.create_job(body)
    queue = StudyQueue(lambda: desk.conn, lambda: model, lambda: False, desk.clock, desk.settings)
    asyncio.run(queue.run(desk, job["job_id"]))
    done = desk.job(job["job_id"])
    assert done["state"] == "completed", done
    return desk.aid(done["result_ids"][0])


def selection(source):
    return [{"source_id": source["source_id"], "revision": source["revision"]}]


def extracted(d, kind, units, data=b"%PDF-1.4 fixture"):
    """A source as extraction leaves it, without running a decoder: its file and its located units."""
    mime = {"pdf": "application/pdf", "recording": "audio/wav"}[kind]
    name = {"pdf": "notes.pdf", "recording": "lecture.wav"}[kind]
    source = d.create(
        {"kind": kind, "file_name": name, "mime_type": mime, "byte_length": len(data), "sha256": digest(data)}
    )
    d.upload(
        source["source_id"], 0, {"offset": 0, "sha256": digest(data), "data_base64": base64.b64encode(data).decode()}
    )
    d.commit_units(d.pending_source(source["source_id"]), units)
    return d.source(source["source_id"])


PAGES = [
    {
        "locator": {"kind": "page", "page": 1},
        "text": "Enzymes\nEnzymes are biological catalysts that speed up reactions.\n"
        "Enzymes work best at an optimum temperature.",
    },
    {
        "locator": {"kind": "page", "page": 2},
        "text": "Respiration\nRespiration releases energy from glucose in cells.\nAerobic respiration needs oxygen.",
    },
]


def test_stu21_settings_respected(tmp_path):
    d = desk_at(tmp_path)
    notes = extracted(d, "pdf", PAGES)
    syllabus = d.create({"kind": "text", "title": "Syllabus", "text": SYLLABUS})
    topics = [t["title"] for t in d.topics(selection(notes))]
    assert topics == ["Enzymes", "Respiration"]
    model = Recorder()
    settings = {
        "question_types": ["fill_blank", "true_false"],
        "difficulty": "hard",
        "topics": ["Enzymes"],
        "focus": "optimum temperature",
        "syllabus": selection(syllabus),
    }
    quiz = run(
        d,
        model,
        {"kind": "quiz", "execution": "local", "count": 5, "sources": selection(notes), "settings": settings},
    )
    request, chunks = model.requests[-1]
    # The settings reach the generator; the syllabus is bounded scope text, never a citable source.
    assert request["settings"] == {k: v for k, v in settings.items() if k != "syllabus"}
    assert request["syllabus_outline"] == SYLLABUS
    assert {c["source_id"] for c in chunks} == {notes["source_id"]}
    # Only the kept topic's chunks are generated from.
    assert all("Respiration" not in c["text"] and "respiration" not in c["text"] for c in chunks)
    stored = d.quiz(quiz["quiz_id"])
    assert {i["type"] for i in stored["view"]["items"]} == {"fill_blank", "true_false"}
    for item in stored["view"]["items"]:
        assert item["stem"]["citations"], item
        d.citation(item["stem"], quiz["sources"])
    assert quiz["settings"] == settings and not errors("study/workspace#/$defs/Aid", quiz)
    # Honest marking: a literal blank match or a true/false key is judged; another word is not guessed.
    ids = {i["type"]: i["item_id"] for i in stored["view"]["items"]}
    result = d.submit(
        quiz["quiz_id"],
        {
            "attempt_id": "sqa_" + "0" * 26,
            "quiz_revision": 1,
            "answers": [
                {"item_id": ids["fill_blank"], "answer": " enzymes."},
                {"item_id": ids["true_false"], "answer": "false"},
            ],
        },
    )
    verdicts = {r["item_id"]: r for r in result["results"]}
    assert verdicts[ids["fill_blank"]]["verdict"] == "correct"
    assert verdicts[ids["true_false"]]["verdict"] == "incorrect"
    assert {r["label"] for r in result["results"]} == {"Judged, not checked"}
    other = d.submit(
        quiz["quiz_id"],
        {
            "attempt_id": "sqa_" + "1" * 26,
            "quiz_revision": 1,
            "answers": [{"item_id": ids["fill_blank"], "answer": "Catalase"}],
        },
    )
    assert other["results"][0]["verdict"] == "unverifiable"

    # Flashcards take count, topics and focus; a podcast its length and voices; a lesson plan its time and date.
    cards = run(
        d,
        model,
        {
            "kind": "flashcards",
            "execution": "local",
            "count": 3,
            "sources": selection(notes),
            "settings": {"topics": ["Respiration"], "focus": "oxygen"},
        },
    )
    request, chunks = model.requests[-1]
    assert request["count"] == 3 and request["settings"] == {"topics": ["Respiration"], "focus": "oxygen"}
    assert all("nzyme" not in c["text"] for c in chunks) and cards["deck_id"]
    podcast = run(
        d,
        model,
        {
            "kind": "audio_overview",
            "execution": "local",
            "sources": selection(notes),
            "settings": {"podcast_length": "short", "voices": 2},
        },
    )
    assert model.requests[-1][0]["settings"] == {"podcast_length": "short", "voices": 2}
    assert len(podcast["claims"]) <= 6
    plan = run(
        d,
        model,
        {
            "kind": "lesson_plan",
            "execution": "local",
            "sources": selection(notes),
            "settings": {"minutes_available": 45, "ready_by": "2026-11-02"},
        },
    )
    assert plan["kind"] == "lesson_plan" and plan["settings"]["minutes_available"] == 45
    assert model.requests[-1][0]["settings"] == {"minutes_available": 45, "ready_by": "2026-11-02"}

    # A setting the tool does not take, or a topic the material does not have, is refused, never ignored.
    for kind, wrong in (("flashcards", {"question_types": ["choice"]}), ("quiz", {"topics": ["Volcanoes"]})):
        with pytest.raises(StudyError, match="invalid_study_request"):
            d.create_job({"kind": kind, "execution": "local", "sources": selection(notes), "settings": wrong})
    # The syllabus file is part of the set: erasing it erases the set (STU-19).
    d.delete(syllabus["source_id"])
    with pytest.raises(StudyError, match="not_found"):
        d.aid(quiz["aid_id"])


def test_stu21_choice_types_are_all_refused_when_unchosen(tmp_path):
    d = desk_at(tmp_path)
    notes = d.create({"kind": "text", "title": "Biology notes", "text": NOTES})

    class OnlyChoice(Recorder):
        async def study_generate(self, identity, request, chunks):
            out, local = await super().study_generate(identity, request, chunks)
            out["quiz"]["items"], out["quiz"]["keys"] = out["quiz"]["items"][:1], out["quiz"]["keys"][:1]
            return out, local

    job = d.create_job(
        {
            "kind": "quiz",
            "execution": "local",
            "sources": selection(notes),
            "settings": {"question_types": ["true_false"]},
        }
    )
    queue = StudyQueue(lambda: d.conn, lambda: OnlyChoice(), lambda: False, d.clock, d.settings)
    asyncio.run(queue.run(d, job["job_id"]))
    assert d.job(job["job_id"])["error"] == "insufficient_evidence"


def test_stu21_material_topics_are_the_materials_own_headings():
    chunk = {"source_id": "s", "revision": 1, "locator": {"kind": "slide", "slide": 1}}
    slides = [
        {**chunk, "chunk_id": "c1", "text": "Photosynthesis\nPlants make glucose using light."},
        {**chunk, "chunk_id": "c2", "text": "1. Leaf structure\nThe palisade layer holds chloroplasts."},
        {**chunk, "chunk_id": "c3", "text": "More on leaves, continued here."},
    ]
    assert material_topics(slides)["items"] == [
        {"title": "Photosynthesis", "chunk_ids": ["c1"]},
        {"title": "Leaf structure", "chunk_ids": ["c2", "c3"]},
    ]
    plain = [
        {
            **chunk,
            "locator": {"kind": "text", "paragraph": 1},
            "chunk_id": "p1",
            "text": "Osmosis moves water. Osmosis needs a membrane.",
        }
    ]
    assert material_topics(plain)["items"] == [{"title": "Osmosis", "chunk_ids": ["p1"]}]


def test_stu21_sets_persist_progress(tmp_path):
    d = desk_at(tmp_path)
    notes = d.create({"kind": "text", "title": "Biology notes", "text": NOTES})
    model = Recorder()
    quiz = run(d, model, {"kind": "quiz", "execution": "local", "count": 4, "sources": selection(notes)})
    cards = run(d, model, {"kind": "flashcards", "execution": "local", "sources": selection(notes)})
    summary = run(d, model, {"kind": "summary", "execution": "local", "sources": selection(notes)})
    items = d.quiz(quiz["quiz_id"])["view"]["items"]
    assert len(items) == 4
    first = items[0]
    answer = "x" if first["type"] == "choice" else "p"
    draft = {"quiz_revision": 1, "answers": [{"item_id": first["item_id"], "answer": answer}], "position": 1}
    d.save_draft(quiz["quiz_id"], draft)
    deck = d.deck(cards["deck_id"])
    d.review(
        deck["deck_id"],
        {
            "client_review_id": "srv_" + "0" * 26,
            "card_id": deck["cards"][0]["card_id"],
            "card_revision": 1,
            "rating": "easy",
            "revealed": True,
        },
    )
    d.conn.close()

    # A restart: a fresh connection to the same learner database.
    later = desk_at(tmp_path)
    listed = later.sets(lambda _: False)
    assert not errors("study/workspace#/$defs/StudySetList", listed)
    by_id = {s["aid_id"]: s for s in listed["items"]}
    assert set(by_id) == {quiz["aid_id"], cards["aid_id"], summary["aid_id"]}
    assert by_id[quiz["aid_id"]]["progress"] == {"questions_total": 4, "questions_left": 3}
    assert by_id[cards["aid_id"]]["progress"] == {"cards_total": 1, "cards_due_today": 0}
    assert "progress" not in by_id[summary["aid_id"]] and by_id[summary["aid_id"]]["title"] == "Biology notes"
    # The quiz opens where it was left.
    assert later.quiz(quiz["quiz_id"])["view"]["draft"] == draft
    later.submit(
        quiz["quiz_id"],
        {
            "attempt_id": "sqa_" + "2" * 26,
            "quiz_revision": 1,
            "answers": [
                {
                    "item_id": i["item_id"],
                    "answer": "x"
                    if i["type"] == "choice"
                    else "p"
                    if i["type"] == "multi_select"
                    else "true"
                    if i["type"] == "true_false"
                    else "Enzymes",
                }
                for i in items[:2]
            ],
        },
    )
    assert "draft" not in later.quiz(quiz["quiz_id"])["view"]
    assert {s["aid_id"]: s for s in later.sets(lambda _: False)["items"]}[quiz["aid_id"]]["progress"][
        "questions_left"
    ] == 2
    # A private source's sets keep no title or progress until it is opened (STU-19).
    later.patch(notes["source_id"], {"private": True})
    hidden = later.sets(lambda _: False)["items"]
    assert all(s["private"] and "title" not in s and "progress" not in s for s in hidden)
    assert all("title" in s for s in later.sets(lambda _: True)["items"])
    # A stale or wrong draft is refused.
    with pytest.raises(StudyError, match="invalid_study_request"):
        later.save_draft(quiz["quiz_id"], {"quiz_revision": 1, "answers": [], "position": 39})


def recording(d, parts):
    data = b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + b"\0" * 24
    units = [{"locator": {"kind": "time", "start_ms": a, "end_ms": b}, "text": text} for a, b, text in parts]
    return extracted(d, "recording", units, data), data


PARTS = [
    (0, 60000, "Today we look at enzymes and how they act as catalysts."),
    (60000, 120000, "Next, temperature changes how fast an enzyme works."),
    (120000, 180000, "Finally, respiration releases energy in every cell."),
]


def test_stu22_chapters_and_seek(tmp_path):
    d = desk_at(tmp_path)
    source, data = recording(d, PARTS)
    assert source["state"] == "ready" and source["duration_ms"] == 180000
    aid = run(d, Recorder(), {"kind": "chapters", "execution": "local", "sources": selection(source)})
    chapters = aid["chapters"]
    assert not errors("study/workspace#/$defs/Aid", aid)
    # In order, no overlap, covering the recording from its start to its end.
    assert chapters[0]["start_ms"] == 0 and chapters[-1]["end_ms"] == 180000
    for a, b in itertools.pairwise(chapters):
        assert a["end_ms"] == b["start_ms"] and a["start_ms"] < a["end_ms"]
    # Every summary sentence cites a span inside its chapter; that span's start is where the player seeks.
    timed = {c["chunk_id"]: c["locator"] for c in d.selected(selection(source))}
    for chapter in chapters:
        assert 1 <= len(chapter["summary"]) <= 3
        for claim in chapter["summary"]:
            loc = timed[claim["citations"][0]["chunk_id"]]
            assert chapter["start_ms"] <= loc["start_ms"] < chapter["end_ms"]
    # The owned recording plays from the device, typed by its own bytes.
    assert d.media(source["source_id"], 1) == (data, "audio/wav")

    class Overlapping(Recorder):
        async def study_generate(self, identity, request, chunks):
            out, local = await super().study_generate(identity, request, chunks)
            out["chapters"][1]["start_ms"] = out["chapters"][0]["end_ms"] - 1000
            return out, local

    job = d.create_job({"kind": "chapters", "execution": "local", "sources": selection(source)})
    queue = StudyQueue(lambda: d.conn, lambda: Overlapping(), lambda: False, d.clock, d.settings)
    asyncio.run(queue.run(d, job["job_id"]))
    assert d.job(job["job_id"])["error"] == "insufficient_evidence"
    # Chapters belong to time-located material only.
    notes = d.create({"kind": "text", "title": "Notes", "text": NOTES})
    with pytest.raises(StudyError, match="invalid_study_request"):
        d.create_job({"kind": "chapters", "execution": "local", "sources": selection(notes)})


def test_stu21_api_sets_draft_and_screened_focus(tmp_path):
    from api_harness import cli, start_core, stop_core
    from test_m10a_profiles import Api, student

    async def scenario():
        runtime = await start_core(
            tmp_path, settings=Settings(study_workspace_enabled=True, study_offline_enabled=True)
        )
        api = Api(runtime)
        try:
            pid = await api.add(student("Ama"))
            token = (await api.unlock(pid)).json()["profile_token"]
            runtime.core.study.model = lambda: Recorder()
            body = {"kind": "text", "title": "Biology notes", "text": NOTES}
            source = await api.call(
                "POST", "/v1/study/sources", body, profile=token, headers={"idempotency-key": cli()}
            )
            sid = source.json()["source_id"]
            topics = await api.call("GET", f"/v1/study/sources/{sid}/material-topics", profile=token)
            assert [t["title"] for t in topics.json()["items"]] == ["Enzymes", "Respiration"]
            refused = await api.call(
                "POST",
                "/v1/study/jobs",
                {
                    "kind": "quiz",
                    "execution": "local",
                    "sources": [{"source_id": sid, "revision": 1}],
                    "settings": {"focus": "write my graded homework essay for me to hand in"},
                },
                profile=token,
            )
            assert refused.status_code == 422, refused.text
            started = await api.call(
                "POST",
                "/v1/study/jobs",
                {
                    "kind": "quiz",
                    "execution": "local",
                    "sources": [{"source_id": sid, "revision": 1}],
                    "settings": {"question_types": ["true_false"], "topics": ["Enzymes"]},
                },
                profile=token,
            )
            assert started.status_code == 202, started.text
            await runtime.core.study.task
            sets = (await api.call("GET", "/v1/study/sets", profile=token)).json()
            entry = sets["items"][0]
            assert (
                entry["kind"] == "quiz" and entry["progress"]["questions_left"] == entry["progress"]["questions_total"]
            )
            aid = (await api.call("GET", f"/v1/study/aids/{entry['aid_id']}", profile=token)).json()
            quiz = (await api.call("GET", f"/v1/study/quizzes/{aid['quiz_id']}", profile=token)).json()
            item = quiz["items"][0]["item_id"]
            saved = await api.call(
                "PUT",
                f"/v1/study/quizzes/{aid['quiz_id']}/draft",
                {"quiz_revision": 1, "answers": [{"item_id": item, "answer": "true"}], "position": 0},
                profile=token,
            )
            assert saved.status_code == 200, saved.text
            sets = (await api.call("GET", "/v1/study/sets", profile=token)).json()
            assert sets["items"][0]["progress"]["questions_left"] == entry["progress"]["questions_total"] - 1
            reopened = (await api.call("GET", f"/v1/study/quizzes/{aid['quiz_id']}", profile=token)).json()
            assert reopened["draft"]["answers"] == [{"item_id": item, "answer": "true"}]
        finally:
            await stop_core(runtime)

    asyncio.run(scenario())
