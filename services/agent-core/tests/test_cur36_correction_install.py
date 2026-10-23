"""CUR-36, D98, OPS-27, ASM-23: a correcting pack re-marks the withdrawn item's attempts on install, with no other step.

Synthetic signed packs and a synthetic learner only. Pack 0.1.0 ships item OLD with a wrong key (option A marked
right; B is truly right). A safety configuration withdraws OLD. Pack 0.2.0 retires OLD and ships NEW, which names it
in `corrects`. Installing pack 0.2.0 through the pack desk, as the app wires it, starts the re-mark in the background;
nothing else is called. Whichever arrives second, the pack or the withdrawal, completes the pair."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.engine.assembly import AppRuntime
from agent_core.engine.assessment.service import AssessmentDesk
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.remark import pending_notice, take_notice
from agent_core.learner.service import Learner
from agent_core.store.packs import write_pack
from m20_fixtures import SIGNED_AT, content_manifest, empty_tables
from signing_service.hierarchy import dev_signer
from test_m24_remark import withdraw

REPO = Path(__file__).resolve().parents[3]
OLD = "itm.mth.o.number.0900"
NEW = "itm.mth.o.number.0901"
KC = "kc.mth.o.number.add_whole"
WRONG_CLAIM = "mc.mth.o.adds_wrongly"
HINTS = ("orient", "concept", "first_step", "worked_step", "full_step")


def item(item_id: str, key: str, claims: dict[str, str], corrects: str | None = None) -> dict[str, Any]:
    """A contract-valid synthetic multiple-choice item: 5 + 7, option B (12) truly right."""
    options = [{"id": x, "text": t, "correct": x == key,
                **({} if x == key or x not in claims else {"misconception_id": claims[x]})}
               for x, t in zip("ABCD", ("35", "12", "57", "2"), strict=True)]  # fmt: skip
    record = {
        "id": item_id, "version": "0.1.0", "type": "mcq", "subject": "mth", "level": "o", "kc_ids": [KC],
        "stem": "A synthetic sum.",
        "parts": [{"id": "a", "prompt": "Add 5 and 7.", "marks": 1,
                   "answer": {"kind": "mcq", "diagnostic": False, "shuffle": False, "options": options},
                   "hints": [{"rung": r, "name": n, "text": {"en": f"Synthetic hint {r}."}}
                             for r, n in enumerate(HINTS, start=1)]}],
        "solution": {"steps": [{"n": 1, "latex": "5 + 7 = 12", "reason": "Synthetic"}]},
        "difficulty": {"prior": 0.0, "band": "foundation"}, "estimated_seconds": 30,
        "exam_style": {"paper_style": "objective", "total_marks": 1, "calculator": False}, "context_tags": [],
        "provenance": {"origin": "original", "licence": "LicenseRef-Own", "drafted_with_ai": False, "sources": []},
        "review": {"status": "published", "reviewers": []},
    }  # fmt: skip
    if corrects is not None:
        record["corrects"] = corrects
    return record


WRONG = item(OLD, "A", {"B": WRONG_CLAIM})
CORRECTED = item(NEW, "B", {}, corrects=OLD)


def pack(folder: Path, version: str, items: list[dict[str, Any]], retired: list[str]) -> Path:
    tables = {**empty_tables(), "items": items}
    manifest = {**content_manifest("pack.mth.o", version, tables), "retired_ids": retired}
    path = folder / f"pack.mth.o-{version}.pack"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pack(path, dev_signer().sign("content_pack", manifest, now=SIGNED_AT), tables)
    return path


class Device:
    """The app's wiring of the pack desk and the runtime (api.__main__): an install tells the runtime."""

    def __init__(self, tmp_path: Path) -> None:
        from agent_core.api.packs import PackDesk

        self.tmp = tmp_path
        self.runtime = AppRuntime(Settings(), REPO / "content" / "agent", REPO / "skills", tmp_path / "data")
        self.runtime.open_stores("1.0.0")
        self.desk = PackDesk(tmp_path / "data", Environment.DEV, "1.0.0", publish=lambda _event: None)
        self.desk.on_installed = lambda _installed: self.runtime.schedule_corrections()
        self.jobs = 0

    def install(self, path: Path) -> Any:
        """What the install command's job does: install, then tell (`api.packs.add_routes.run_install`)."""
        self.jobs += 1
        installed = self.desk.install_source({"kind": "file", "path": str(path)}, f"job_{self.jobs}")
        assert self.desk.on_installed is not None
        return self.desk.on_installed(installed)

    async def answer(self, options: list[str]) -> None:
        """The student answers OLD, as shipped, with each option in turn (the assessment's write path)."""
        runtime, clock = self.runtime, [1_800_000_000_000]
        assert runtime.stores is not None
        learner = Learner.open(runtime.stores.learner, profile_id=runtime.stores.profile_id,
                               device_id=runtime.stores.device_id, wall_ms=lambda: clock[0],
                               max_skew_ms=Settings().sync_clock_skew_max_ms,
                               params=MasteryParams.from_settings(Settings()), content=runtime.content())  # fmt: skip
        desk = AssessmentDesk(learner, runtime.content(), Settings(), clock_ms=lambda: clock[0])
        shown = runtime.content().record("items", OLD)
        assert shown is not None
        state = {"id": "0" * 26, "kind": "practice", "subject": "mathematics"}
        for n, option in enumerate(options):
            clock[0] += n * 3_600_000
            given = {"parts": [{"part_id": "a", "kind": "mcq", "option_id": option}]}
            _, events, transcript = desk._attempt_events(state, shown, await desk._mark(shown, given), given, 20_000)
            desk.learner.record_batch(events, extra=lambda conn, stored, t=transcript: t())

    def verdicts(self) -> int:
        assert self.runtime.stores is not None
        return int(self.runtime.stores.learner.execute("SELECT count(*) FROM events WHERE type = 'verdict'")
                   .fetchone()[0])  # fmt: skip

    def outcomes(self) -> list[str]:
        assert self.runtime.stores is not None
        rows = self.runtime.stores.learner.execute("SELECT outcome FROM attempts ORDER BY occurred_at")
        return [r[0] for r in rows]

    def misconceptions(self) -> list[str]:
        assert self.runtime.stores is not None
        rows = self.runtime.stores.learner.execute("SELECT misconception_id FROM learner_misconceptions")
        return [r[0] for r in rows]


def cur36_correction_install_remarks(tmp_path: Path) -> None:
    """Installing a pack whose item `corrects` a withdrawn item re-marks that item's attempts once, with no other
    step, and the student is told when a result changed (ASM-23)."""

    async def scenario() -> None:
        device = Device(tmp_path)
        assert device.install(pack(tmp_path / "in", "0.1.0", [WRONG], [])) is None  # nothing corrects anything
        await device.answer(["B", "B", "C", "B"])  # three truly right answers, marked wrong by the wrong key
        assert device.outcomes() == ["incorrect", "incorrect", "incorrect", "incorrect"]
        assert device.misconceptions() == [WRONG_CLAIM]
        withdraw(device.runtime.operation_policy(), OLD)
        device.runtime.operation_boundary()  # the withdrawal applies at a turn boundary (OPS-10)
        before = device.verdicts()

        sweep = device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        assert sweep is not None  # the install alone started the re-mark, in the background
        (report,) = await sweep
        assert report.remarked_attempts == report.affected_attempts == 4 and report.changed_results == 3
        assert device.verdicts() == before + 4
        assert device.outcomes() == ["correct", "correct", "incorrect", "correct"]
        assert device.misconceptions() == []  # the wrong key's claim left with its verdicts

        # Once: later installs, boundaries and starts find nothing waiting, and append nothing.
        assert device.runtime.schedule_corrections() is None
        device.runtime.operation_boundary()
        assert device.runtime.schedule_corrections() is None
        assert device.install(pack(tmp_path / "in", "0.2.1", [CORRECTED], [OLD])) is None
        assert device.verdicts() == before + 4

        # The student is told, once, how many results changed.
        assert device.runtime.stores is not None
        assert pending_notice(device.runtime.stores.learner) == 3
        assert take_notice(device.runtime.stores.learner, 1) == 3
        assert pending_notice(device.runtime.stores.learner) == 0

    asyncio.run(scenario())


def test_a_withdrawal_arriving_after_the_correcting_pack_remarks_at_the_boundary(tmp_path: Path) -> None:
    """The correcting pack came first (the item is not withdrawn here yet): nothing is re-marked until the
    withdrawal applies at a turn boundary, which then starts the re-mark on its own."""

    async def scenario() -> None:
        device = Device(tmp_path)
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B", "A"])
        assert device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD])) is None  # not withdrawn here
        assert device.runtime.corrections() == []
        withdraw(device.runtime.operation_policy(), OLD)
        assert device.runtime.corrections() == []  # adopted, not yet applied: it applies at the boundary
        device.runtime.operation_boundary()
        sweep = device.runtime.schedule_corrections()
        assert sweep is not None
        (report,) = await sweep
        assert report.changed_results == 2 and device.outcomes() == ["correct", "incorrect"]
        assert device.runtime.corrections() == []

    asyncio.run(scenario())


def test_an_open_session_is_told_at_once(tmp_path: Path) -> None:
    """With a session of the profile open, the notice goes to it as soon as the re-mark ends (ASM-23)."""

    class Session:
        def __init__(self, conn: Any) -> None:
            self.conn, self.told = conn, []

        def turn_started(self) -> float:
            return 1.0

        def deliver_remark_notice(self) -> bool:
            count = take_notice(self.conn, 1)
            self.told.append(count)
            return count > 0

    async def scenario() -> list[int]:
        device = Device(tmp_path)
        assert device.runtime.stores is not None
        session = Session(device.runtime.stores.learner)
        device.runtime.engines.add(session)  # type: ignore[arg-type]
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B"])
        withdraw(device.runtime.operation_policy(), OLD)
        device.runtime.operation_boundary()
        await device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        return session.told

    assert asyncio.run(scenario()) == [1]


def test_asm23_remark_notice_in_the_next_turn(tmp_path: Path) -> None:
    """ASM-23: the student's next turn carries one `notice` saying how many answers were marked again, through the
    catalogue key the client shows; the turn after carries none, and a session told at once gets it in its latest
    turn."""
    from engine_harness import close, make_engine, tutor
    from memory_harness import SAFE

    waiting = [2]

    def take() -> int:
        return waiting.pop(0) if waiting else 0

    async def scenario() -> tuple[Any, list[Any]]:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE), tutor(SAFE)]}, worker=False)
        try:
            assert engine.deliver_remark_notice() is False  # nothing bound, no turn yet
            engine.remark_notice = take
            assert engine.deliver_remark_notice() is False  # no turn to show it in yet: it keeps waiting
            first = await engine.student_turn("How do I start?")
            second = await engine.student_turn("And then?")
            waiting.append(1)  # a later re-mark changed one more result, with the session open
            told_at_once = engine.deliver_remark_notice()
            assert told_at_once and engine.deliver_remark_notice() is False
            return engine, [first, second]
        finally:
            await close(engine)

    engine, (first, second) = asyncio.run(scenario())

    def notices(turn_id: str) -> list[dict[str, Any]]:
        return [e for e in engine.events.of_turn(turn_id) if e["type"] == "notice"]

    (shown,) = notices(first.turn_id)
    assert (shown["code"], shown["message_key"], shown["params"]) == ("marking_corrected", "notice.marking_corrected",
                                                                     {"count": 2})  # fmt: skip
    (later,) = notices(second.turn_id)  # the one told at once lands in the latest turn
    assert later["params"] == {"count": 1}
    from agent_core.contracts import validate

    validate("api/events#/$defs/ev_notice", shown)
