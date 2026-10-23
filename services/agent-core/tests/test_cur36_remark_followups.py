"""CUR-36, ASM-23, MEM-06, OPS-10, DAT-08: the re-mark's follow-ups. A notice waiting for a profile survives audit-log
retention until it is shown; content or a withdrawal arriving from a pack, a kit or the update desk re-marks promptly;
a re-mark that keeps failing backs off and is named in health; and a re-mark alone never makes the Reflector reflect a
session again. Synthetic signed packs and a synthetic learner only (see test_cur36_correction_install)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from agent_core.engine.reflection import window_cursor
from agent_core.learner.remark import NOTICE_ACTION, NOTICE_SHOWN, pending_notice, take_notice
from agent_core.store import retention
from test_cur36_correction_install import CORRECTED, NEW, OLD, WRONG, Device, pack
from test_m24_remark import withdraw

DAY_MS = 86_400_000


def _prompt(device: Device) -> None:
    """The app's wiring (api.__main__): an install, a kit or the update desk applies a waiting withdrawal promptly."""
    device.desk.on_installed = lambda _installed: device.runtime.schedule_corrections(apply_pending=True)


def test_cur36_withdrawal_and_correction_arriving_together_remark_promptly(tmp_path: Path) -> None:
    """The withdrawal (adopted, not yet applied) and the correcting pack arrive together, as from a USB kit or the
    update desk: the re-mark runs as soon as no turn runs, with no turn boundary in between (OPS-10)."""

    async def scenario() -> None:
        device = Device(tmp_path)
        _prompt(device)
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B", "A"])
        withdraw(device.runtime.operation_policy(), OLD)  # adopted: waits for a boundary
        assert device.runtime.safety_pending() and device.runtime.corrections() == []
        sweep = device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        assert sweep is not None
        (report,) = await sweep
        assert report.changed_results == 2 and device.outcomes() == ["correct", "incorrect"]
        assert not device.runtime.safety_pending()
        assert device.runtime.schedule_corrections(apply_pending=True) is None  # nothing pending, nothing waiting

    asyncio.run(scenario())


def test_cur36_update_desk_staging_asks_for_the_remark(tmp_path: Path) -> None:
    """The update desk tells the runtime once an update (which may carry a safety configuration) is staged."""
    from m20_fixtures import update_pack
    from test_m20_update_workflow import desk_at

    async def scenario() -> list[int]:
        core, desk, _ = desk_at(tmp_path / "data")
        calls: list[int] = []
        core.corrections_due = lambda: calls.append(1)
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        return calls

    assert asyncio.run(scenario()) == [1]


def test_cur36_failing_remark_backs_off_and_shows_in_health(tmp_path: Path) -> None:
    """A re-mark that fails is not retried at every start or turn boundary: it waits the first delay, then twice as
    long, and health names it once it has failed `remark_failures_reported` times; a success clears it."""

    async def scenario() -> None:
        device = Device(tmp_path)
        runtime = device.runtime
        clock = [2_000_000_000_000]
        runtime.remark_clock_ms = lambda: clock[0]
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B"])
        withdraw(runtime.operation_policy(), OLD)
        runtime.operation_boundary()
        real = runtime._remark_everywhere
        attempts: list[str] = []

        async def broken(old: str, new: str) -> list[Any]:
            attempts.append(old)
            raise RuntimeError("synthetic failure")

        runtime._remark_everywhere = broken  # type: ignore[method-assign]
        sweep = device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        assert sweep is not None and await sweep == [] and len(attempts) == 1
        (failed,) = runtime.remark_failures().values()
        first = runtime.settings.remark_retry_first_delay_s
        assert failed["failures"] == 1 and failed["retry_at"] == clock[0] + int(first * 1000)
        # Boundaries and starts within the delay try nothing.
        runtime.operation_boundary()
        assert runtime.schedule_corrections() is None and runtime.corrections() == []
        assert not runtime.remark_failing() and "remark" not in runtime.health_components()
        clock[0] += int(first * 1000)
        sweep = runtime.schedule_corrections()
        assert sweep is not None and await sweep == [] and len(attempts) == 2
        (failed,) = runtime.remark_failures().values()
        assert failed["failures"] == 2 and failed["retry_at"] == clock[0] + int(2 * first * 1000)  # doubled
        assert runtime.remark_failing() and runtime.health_components()["remark"] == "degraded"
        # Once it works, the failures are cleared and health is quiet again.
        runtime._remark_everywhere = real  # type: ignore[method-assign]
        clock[0] += int(runtime.settings.remark_retry_max_delay_s * 1000)
        sweep = runtime.schedule_corrections()
        assert sweep is not None
        (report,) = await sweep
        assert report.changed_results == 1
        assert runtime.remark_failures() == {} and "remark" not in runtime.health_components()

    asyncio.run(scenario())


def test_asm23_waiting_notice_survives_audit_retention_until_shown(tmp_path: Path) -> None:
    """A profile not opened within `retention_audit_days` still gets its notice: the waiting row is kept until it is
    shown, then it and its shown row age out like any audit row (DAT-08)."""
    assert (retention.PENDING_NOTICE, retention.NOTICE_SHOWN) == (NOTICE_ACTION, NOTICE_SHOWN)

    async def scenario() -> Device:
        device = Device(tmp_path)
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B", "B"])
        withdraw(device.runtime.operation_policy(), OLD)
        device.runtime.operation_boundary()
        sweep = device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        assert sweep is not None
        await sweep
        return device

    runtime = asyncio.run(scenario()).runtime
    assert runtime.stores is not None
    conn = runtime.stores.learner
    period = int(runtime.settings.retention_audit_days * DAY_MS)
    now = int(time.time() * 1000)
    conn.execute("INSERT INTO audit_log (audit_id, actor_role, action, target, detail, at) VALUES"
                 " ('01JSYNTHETICOTHERAUDIT0000', 'system', 'synthetic.other', 'x', NULL, ?)", (now,))  # fmt: skip
    conn.commit()
    assert pending_notice(conn) == 2
    runtime.retention_pass(now + period + DAY_MS)
    assert pending_notice(conn) == 2, "kept past the period while it waits"
    left = conn.execute("SELECT count(*) FROM audit_log WHERE action = 'synthetic.other'").fetchone()[0]
    assert left == 0, "every other audit row still goes at its expiry"
    told_at = now + period + 2 * DAY_MS
    assert take_notice(conn, told_at) == 2
    runtime.retention_pass(told_at + DAY_MS)
    assert conn.execute("SELECT count(*) FROM audit_log WHERE action = ?", (NOTICE_ACTION,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM audit_log WHERE action = ?", (NOTICE_SHOWN,)).fetchone()[0] == 1
    runtime.retention_pass(told_at + period + DAY_MS)
    assert conn.execute("SELECT count(*) FROM audit_log WHERE action LIKE 'remark.%'").fetchone()[0] == 0
    assert pending_notice(conn) == 0


async def _answer_new(device: Device) -> None:
    """One answer to the corrected item, through the assessment's write path, in the same session."""
    from agent_core.config import Settings
    from agent_core.engine.assessment.service import AssessmentDesk
    from agent_core.learner.mastery import MasteryParams
    from agent_core.learner.service import Learner

    runtime, clock = device.runtime, [1_900_000_000_000]
    assert runtime.stores is not None
    learner = Learner.open(runtime.stores.learner, profile_id=runtime.stores.profile_id,
                           device_id=runtime.stores.device_id, wall_ms=lambda: clock[0],
                           max_skew_ms=Settings().sync_clock_skew_max_ms,
                           params=MasteryParams.from_settings(Settings()), content=runtime.content())  # fmt: skip
    desk = AssessmentDesk(learner, runtime.content(), Settings(), clock_ms=lambda: clock[0])
    shown = runtime.content().record("items", NEW)
    assert shown is not None
    state = {"id": "0" * 26, "kind": "practice", "subject": "mathematics"}
    given = {"parts": [{"part_id": "a", "kind": "mcq", "option_id": "B"}]}
    _, events, transcript = desk._attempt_events(state, shown, await desk._mark(shown, given), given, 20_000)
    desk.learner.record_batch(events, extra=lambda conn, stored, t=transcript: t())


def test_mem06_remark_alone_never_reflects_a_session_again(tmp_path: Path) -> None:
    """A re-mark appends verdicts and evidence to old sessions, but it is not a write point (MEM-06): the Reflector's
    window for those sessions does not move, so no job is queued for them; a real new event still moves it."""

    async def scenario() -> tuple[int, int, int, int]:
        device = Device(tmp_path)
        device.install(pack(tmp_path / "in", "0.1.0", [WRONG], []))
        await device.answer(["B", "B", "C"])
        assert device.runtime.stores is not None
        conn = device.runtime.stores.learner
        (sid,) = {r[0] for r in conn.execute("SELECT session_id FROM events WHERE type = 'verdict'")}
        before = window_cursor(conn, sid)
        withdraw(device.runtime.operation_policy(), OLD)
        device.runtime.operation_boundary()
        sweep = device.install(pack(tmp_path / "in", "0.2.0", [CORRECTED], [OLD]))
        assert sweep is not None
        (report,) = await sweep
        assert report.appended == 3
        newest = conn.execute("SELECT max(seq) FROM events WHERE session_id = ?", (sid,)).fetchone()[0]
        after = window_cursor(conn, sid)
        await _answer_new(device)  # the student answers the corrected item in the same session
        return before, after, int(newest), window_cursor(conn, sid)

    before, after, newest, later = asyncio.run(scenario())
    assert after == before < newest, "the re-mark's events do not move the window"
    assert later > newest, "a new attempt does"
