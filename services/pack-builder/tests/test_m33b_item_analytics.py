"""M33.b: item analytics, calibration and the review queue (CUR-26, ASM-21), analytics feedback to authors (AUT-37)
and the content problem report inbox (AUT-38).

Pilot response volume does not exist yet: every response here is synthetic, drawn from a seeded 1PL (Rasch) model of
invented students, and every payload is built by the test. The workspace is a throwaway copy of a few physics items
with an invented author."""

from __future__ import annotations

import json
import math
import random
import shutil
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from pack_builder import analytics, cli, source
from pack_builder.accounts import Accounts, chain_errors
from pack_builder.analytics import Analytics, IntakeRefused, Tally
from pack_builder.problem_inbox import Inbox, ReportRefused
from pack_builder.studio import Workspace, handle
from pack_builder.studio_io import revision

REPO = Path(__file__).resolve().parents[3]
PHY = REPO / "content/curriculum/phy/o"
EASY, HARD, FLAT, NORMAL = (f"itm.phy.o.motion.000{n}" for n in (1, 2, 3, 4))
MCQ = "itm.phy.o.circuits.0027"
FEW = "itm.phy.o.motion.0005"  # crosses a threshold, but on too few responses
KC = "kc.phy.o.motion.average_speed"
ANCHORS = [f"itm.phy.o.anchor.{n:04d}" for n in range(12)]  # items the payload has and the workspace does not


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    pack = root / "content/curriculum/phy/o"
    pack.mkdir(parents=True)
    for name in ("pack.yaml", "map.yaml"):
        shutil.copy(PHY / name, pack / name)
    for directory in ("kcs", "misconceptions"):
        shutil.copytree(PHY / directory, pack / directory)
    shutil.copytree(source.ref_dir(PHY), source.ref_dir(pack))
    (pack / "items").mkdir()
    for identity in (EASY, HARD, FLAT, NORMAL, MCQ, FEW):
        shutil.copy(PHY / "items" / f"{identity}.yaml", pack / "items")
    home = tmp_path / "authors"
    monkeypatch.setenv("JANA_AUTHORING_HOME", str(home))
    Accounts(home).create("lead", "Synthetic Lead", "lead@example.test", ["curriculum_lead"])
    monkeypatch.setenv("JANA_AUTHOR", "lead")
    return Workspace(root)


# --- seeded synthetic responses ---------------------------------------------------------------------------------------


def respond(rng: random.Random, theta: float, item: str, b: float | None, time_ms: int = 40_000) -> dict[str, Any]:
    """One synthetic first response: Rasch with difficulty b, or a coin toss whatever the ability when b is None."""
    p = 0.5 if b is None else 1 / (1 + math.exp(b - theta))
    correct = rng.random() < p
    row = {"item_id": item, "outcome": "correct" if correct else "incorrect", "kc_id": KC,
           "time_ms": int(time_ms * rng.uniform(0.8, 1.25))}  # fmt: skip
    if item == MCQ:  # D is the key; A is the misconception almost nobody holds
        row["choice_id"] = "D" if correct else rng.choices(["A", "B", "C"], weights=[3, 60, 60])[0]
    return row


def evaluation(students: int, seed: int = 7, few: int = 150, slow: str | None = None) -> dict[str, Any]:
    """One evaluation run over `students` simulated students; FEW is answered by only the first `few` of them."""
    rng = random.Random(seed)
    rows = []
    for s in range(students):
        theta = rng.gauss(0, 1)
        plan = {EASY: -6.0, HARD: 5.0, FLAT: None, NORMAL: 0.0, MCQ: 0.0} | {a: rng.uniform(-1.5, 1.5) for a in ANCHORS}
        if s < few:
            plan[FEW] = -6.0
        for item, b in plan.items():
            row = respond(rng, theta, item, b, 400_000 if item == slow else 40_000)
            rows.append({"respondent": f"sim-{s:04d}", **row})
    return {"kind": "evaluation", "run_id": f"evr_synthetic_{seed:04d}", "item_responses": rows}


def research(rows: list[dict[str, Any]], **consent: Any) -> dict[str, Any]:
    """A research export body as a device seals it (agent_core.engine.research.export_rows)."""
    given = {"scope": "research_use", "student_assent": True, "protocol_ref": "synthetic-protocol"} | consent
    return {"kind": "research_export", "consent": given, "events": [], "kc_mastery": [], "item_responses": rows,
            "skill_sessions": []}  # fmt: skip


def item_records(w: Workspace) -> dict[str, dict[str, Any]]:
    from pack_builder.studio_analytics import items

    return items(w)


# --- CUR-26 -----------------------------------------------------------------------------------------------------------


def cur26_flagged_items_queued(workspace):
    """Each item crossing a threshold in a seeded aggregate is queued with its reason; an item crossing one on fewer
    than the response minimum is not, and an ordinary item is not."""
    store = Analytics()
    store.intake(evaluation(260, slow=NORMAL))
    queue = analytics.refresh_queue(store, item_records(workspace))
    reasons = {k: set(v["reasons"]) for k, v in queue.items()}
    assert "facility_high" in reasons[EASY]
    assert "facility_low" in reasons[HARD]
    assert "discrimination_low" in reasons[FLAT]
    assert "distractor_rare:A" in reasons[MCQ]
    assert "slow_median_time" in reasons[NORMAL]
    assert store.tallies()[FEW].responses == 150 and FEW not in queue  # below item_analytics_min_responses (200)
    ordinary = analytics.flags(item_records(workspace)[NORMAL], store.tallies()[NORMAL], None)
    assert ordinary == []  # without the slow KC comparison the Rasch item crosses nothing
    assert all(v["status"] == "open" and v["statistics"]["students"] == 260 for v in queue.values())


def test_cur26_unused_distractor_and_reopening(workspace):
    """A distractor nobody picks is queued as unused (ASM-21); a dismissed entry stays dismissed until a new reason
    appears."""
    store = Analytics()
    payload = evaluation(220, seed=3)
    for row in payload["item_responses"]:
        if row.get("choice_id") == "A":
            row["choice_id"] = "B"
    store.intake(payload)
    queue = analytics.refresh_queue(store, item_records(workspace))
    assert "distractor_unused:A" in queue[MCQ]["reasons"]
    analytics.resolve(store, MCQ, "dismissed", "rev_synthetic")
    assert analytics.refresh_queue(store, item_records(workspace))[MCQ]["status"] == "dismissed"
    assert analytics.resolve(store, EASY, "wrong_key", "rev_synthetic")["next"].endswith("(CUR-36).")


# --- ASM-21 -----------------------------------------------------------------------------------------------------------


def asm21_threshold():
    """The calibrated difficulty replaces the author's prior only from 100 responses; below, the prior stands."""
    settings = Settings()
    rng = random.Random(11)
    true_b, prior = 1.5, 0.0

    def tally(students: int) -> Tally:
        tallies: dict[str, Tally] = {}
        groups = []
        for _ in range(students):
            theta = rng.gauss(0, 1)
            groups.append([respond(rng, theta, "itm.phy.o.motion.0009", true_b)]
                          + [respond(rng, theta, a, rng.uniform(-1.5, 1.5)) for a in ANCHORS])  # fmt: skip
        analytics.reduce(groups, tallies)
        return tallies["itm.phy.o.motion.0009"]

    below = analytics.calibrate(tally(settings.calibration_min_responses - 1), prior, settings)
    assert below["replaced"] is False and below["difficulty"] == prior and below["estimate"] != prior
    at = analytics.calibrate(tally(settings.calibration_min_responses), prior, settings)
    assert at["replaced"] is True and at["difficulty"] == at["estimate"]
    many = analytics.calibrate(tally(800), prior, settings)
    assert abs(many["estimate"] - true_b) < abs(prior - true_b) and many["estimate"] > 0.75
    assert analytics.calibrate(Tally(), prior, settings)["difficulty"] == prior


def asm21_flag_not_edit(workspace):
    """Flagged items appear in the review queue and are unchanged in the source the packs are built from, also after
    the review confirms a wrong key; a calibrated difficulty reaches an item only as an author's registered edit."""
    pack = workspace.pack("pack.phy.o")
    before = {p.name: revision(p) for p in sorted((pack / "items").glob("*.yaml"))}
    store = Analytics()
    store.intake(evaluation(260, few=60))
    queue = handle(workspace, {"op": "analytics_queue"})["result"]["entries"]
    assert {e["record_id"] for e in queue} >= {EASY, HARD, FLAT, MCQ}
    handle(workspace, {"op": "analytics_resolve", "id": HARD, "outcome": "wrong_key"})
    assert {p.name: revision(p) for p in sorted((pack / "items").glob("*.yaml"))} == before
    easy = next(e for e in queue if e["record_id"] == EASY)
    assert easy["calibration"]["replaced"] and easy["calibration"]["difficulty"] != easy["calibration"]["prior"]
    assert source._load(pack / "items" / f"{EASY}.yaml")["difficulty"]["prior"] == easy["calibration"]["prior"]
    # The author adopts it: an ordinary edit, which returns the published item to drafted at a new version.
    opened = workspace.open_record("pack.phy.o", "items", EASY)
    adopted = handle(workspace, {"op": "analytics_apply_calibration", "pack": "pack.phy.o", "id": EASY,
                                 "revision": opened["revision"]})["result"]  # fmt: skip
    assert adopted["record"]["difficulty"]["prior"] == easy["calibration"]["difficulty"]
    assert adopted["record"]["review"]["status"] == "drafted"
    assert adopted["record"]["version"] != opened["record"]["version"]
    few = workspace.open_record("pack.phy.o", "items", FEW)
    refused = handle(workspace, {"op": "analytics_apply_calibration", "pack": "pack.phy.o", "id": FEW,
                                 "revision": few["revision"]})  # fmt: skip
    assert refused["error"] == "invalid" and "ASM-21" in refused["message"]  # 60 responses replace no prior
    assert not chain_errors(workspace.ctx().audit.entries())


# --- AUT-37 -----------------------------------------------------------------------------------------------------------


def aut37_research_only(workspace, tmp_path):
    """The analytics intake refuses unconsented research, student text and school-sync payloads whole, and keeps no
    student row of what it accepts."""
    store = Analytics()
    rows = [{"item_id": NORMAL, "outcome": "correct", "time_ms": 30_000, "kc_id": KC}]
    refused = [
        research(rows, scope="model_training_research"),
        research(rows, student_assent=False),
        research(rows, protocol_ref=""),
        {k: v for k, v in research(rows).items() if k != "consent"},
        research([rows[0] | {"normalised_response": "PRIVATE-CANARY I think it is 8"}]),
        research(rows) | {"events": [{"type": "attempt", "day": "2026-10-01", "text": "PRIVATE-CANARY"}]},
        research(rows) | {"notes": ["PRIVATE-CANARY"]},
        research([rows[0] | {"profile_id": "prf_01JABCDEFGHJKMNPQRSTVWXYZ0"}]),
        {"kind": "school_sync", "school_id": "sch_1", "class_id": "cls_1", "item_responses": rows},
        {"kind": "telemetry", "report_id": "r", "metrics": {}},
        {"frame": "hello", "item_responses": rows},
        evaluation(3) | {"item_responses": [{"respondent": "Ada Lovelace", **rows[0]}]},
        evaluation(3) | {"item_responses": [{"respondent": "sim-1", **rows[0], "transcript": "PRIVATE-CANARY"}]},
    ]
    for payload in refused:
        with pytest.raises(IntakeRefused):
            store.intake(payload)
    assert not store.items_path.exists()
    assert store.intake(research(rows)) == {"kind": "research_export", "respondents": 1, "items": 1}
    assert store.intake(evaluation(12))["respondents"] == 12
    with pytest.raises(IntakeRefused):
        store.intake(evaluation(12))  # the same payload twice
    stored = store.items_path.read_text()
    assert "sim-" not in stored and "PRIVATE-CANARY" not in stored and '"respondent"' not in stored
    # The CLI refuses the same way, exits 1 and leaves the store as it was.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"kind": "school_sync", "item_responses": rows}))
    assert cli.main(["--json", "analytics", "intake", str(bad)]) == 1
    assert store.items_path.read_text() == stored


def aut37_small_sample(workspace):
    """Figures from fewer than 10 students are suppressed; the sample size is always shown, and figures from 10 come
    with 95% intervals."""
    store = Analytics()
    store.intake(evaluation(9, seed=21))
    shown = handle(workspace, {"op": "analytics_records", "pack": "pack.phy.o"})["result"]["records"]
    normal = next(r for r in shown if r["record_id"] == NORMAL)
    assert normal["students"] == 9 and normal["suppressed"] is True
    assert normal["facility"] is None and normal["discrimination"] is None and normal["distractors"] is None
    store.intake(evaluation(1, seed=22))
    shown = handle(workspace, {"op": "analytics_records", "pack": "pack.phy.o"})["result"]["records"]
    normal = next(r for r in shown if r["record_id"] == NORMAL)
    mcq = next(r for r in shown if r["record_id"] == MCQ)
    assert normal["students"] == 10 and normal["suppressed"] is False
    low, high = normal["facility"]["interval"]
    assert low <= normal["facility"]["value"] <= high
    assert all(0 <= d["interval"][0] <= d["share"] <= d["interval"][1] for d in mcq["distractors"].values())


def test_aut37_research_exports_count_students_and_resolve_distractors(workspace):
    """Each research export is one student; a device's response names the distractor by the misconception the marker
    matched (the answer itself stays on the device), which resolves to the item's option."""
    store = Analytics()
    split = "mc.phy.o.parallel_current_split_equally"  # option B
    for n in range(12):
        row: dict[str, Any] = {"item_id": MCQ, "time_ms": 20_000 + n, "kc_id": "kc.phy.o.circuits.parallel_circuits"}
        row |= {"outcome": "correct"} if n % 3 else {"outcome": "incorrect", "misconception_id": split}
        assert store.intake(research([row]))["respondents"] == 1
    (shown,) = handle(workspace, {"op": "analytics_records", "pack": "pack.phy.o"})["result"]["records"]
    assert shown["students"] == 12 and shown["suppressed"] is False
    assert {k: v["share"] for k, v in shown["distractors"].items()} == {"A": 0, "B": 0.333333, "C": 0, "D": 0.666667}


def test_aut37_analytics_need_the_permission(workspace, monkeypatch):
    Accounts().create("nobody", "Synthetic Reviewer", "lang@example.test", ["language_reviewer"])
    monkeypatch.setenv("JANA_AUTHOR", "nobody")
    assert handle(workspace, {"op": "analytics_queue"})["error"] == "forbidden"


# --- AUT-38 -----------------------------------------------------------------------------------------------------------


def test_aut38_inbox_counts_and_allowed_text(workspace):
    """Reports reach the inbox as counts by category and record id; free text only where the student allowed sending
    it; any other source is refused."""
    inbox = Inbox()
    inbox.intake(
        {
            "kind": "content_reports",
            "counts": [
                {"record_id": EASY, "category": "wrong_answer", "count": 3},
                {"record_id": MCQ, "category": "typo", "count": 1},
            ],
        }
    )
    inbox.intake({"kind": "support_export", "reports": [
        {"record_id": EASY, "category": "wrong_answer", "note": "The key says 8 but 1200/150 is 8.0",
         "allow_support_export": True},
        {"record_id": EASY, "category": "unclear", "note": "PRIVATE-CANARY", "allow_support_export": False},
    ]})  # fmt: skip
    rows = handle(workspace, {"op": "inbox_list"})["result"]["rows"]
    assert rows[0]["record_id"] == EASY and rows[0]["counts"] == {"wrong_answer": 4, "unclear": 1}
    assert [n["note"] for n in rows[0]["notes"]] == ["The key says 8 but 1200/150 is 8.0"]
    assert "PRIVATE-CANARY" not in inbox.path.read_text()
    for payload in (
        {"kind": "content_reports", "counts": [{"record_id": EASY, "category": "typo", "count": 1, "note": "x"}]},
        {"kind": "content_reports", "counts": [{"record_id": "Ada", "category": "typo", "count": 1}]},
        {"kind": "content_reports", "counts": [{"record_id": EASY, "category": "rude", "count": 1}]},
        {"kind": "teacher_inbox", "reports": []},
        {"kind": "school_sync", "counts": []},
    ):
        with pytest.raises(ReportRefused):
            inbox.intake(payload)


def test_aut38_counts_match_the_proposed_telemetry_field():
    """The counts the inbox takes are the `content_reports` proposed for the telemetry report (contract-additions-
    m33b.json, D72): what one accepts the other does, and a count with text or a person's name fits neither."""
    from jsonschema import Draft202012Validator

    additions = json.loads((REPO / "contract-additions-m33b.json").read_text())["additions"]
    schema = next(a["value"] for a in additions if a["pointer"] == "/properties/content_reports")
    validator = Draft202012Validator(schema)
    good = [
        {"record_id": r, "category": c, "count": 2}
        for r in (EASY, MCQ, KC, "mc.phy.o.time_over_distance", "wex.phy.o.motion.0001")
        for c in ("typo", "other")
    ]
    assert not list(validator.iter_errors(good))
    from pack_builder.problem_inbox import reports

    assert len(reports({"kind": "content_reports", "counts": good})) == len(good)
    for bad in ({"record_id": "Ada Lovelace", "category": "typo", "count": 1},
                {"record_id": EASY, "category": "typo", "count": 1, "note": "PRIVATE-CANARY"},
                {"record_id": EASY, "category": "rude", "count": 1}):  # fmt: skip
        assert list(validator.iter_errors([bad]))
        with pytest.raises(ReportRefused):
            reports({"kind": "content_reports", "counts": [bad]})


def test_aut38_report_opens_a_draft_change(workspace):
    """A report opens its record in the editor; saving it is the ordinary edit, back to drafted at a new version."""
    Inbox().intake({"kind": "content_reports", "counts": [{"record_id": EASY, "category": "typo", "count": 2}]})
    opened = handle(workspace, {"op": "inbox_open", "pack": "pack.phy.o", "table": "items", "id": EASY})["result"]
    assert opened["record"]["review"]["status"] == "published"
    opened["record"]["stem"] = opened["record"]["stem"].replace("rides", "cycles")
    saved = workspace.save({"pack": "pack.phy.o", "table": "items", "id": EASY, "record": opened["record"],
                            "revision": opened["revision"]})  # fmt: skip
    assert saved["record"]["review"]["status"] == "drafted"
    assert Inbox().rows()[0]["drafts"][0]["version"] == opened["record"]["version"]
