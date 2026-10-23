"""M10.d: the retention job of TABLE DAT-08a (DAT-08, MEM-22). Every row, file and identifier here is synthetic."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.learner.service import Learner
from agent_core.memory.write import NOTES_WRITER
from agent_core.store.events import iso_ms
from agent_core.store.generated.schema import DATABASES, DEVICE
from agent_core.store.ids import new_ulid
from agent_core.store.retention import DAY_MS, HOUR_MS, PROJECTION_TABLES, RULES, WEEK_MS, run_retention
from agent_core.store.sqlite import connect, statements
from agent_core.trace.store import TraceStore
from learner_harness import PROFILE, START_MS, Clock, learner_db, make_learner, random_log

REPO = Path(__file__).resolve().parents[3]
STORAGE_CONTRACT = REPO / "docs/specification/contracts/data/schema.sql"
B = START_MS
MINUTE_MS = 60_000
FAR = B + 5000 * DAY_MS


def device_db() -> sqlite3.Connection:
    conn = connect(":memory:")
    for statement in statements(DEVICE):
        conn.execute(statement)
    return conn


def count(conn: sqlite3.Connection, sql: str, *args: Any) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {sql}", args).fetchone()[0])  # noqa: S608 - test queries


def has(conn: sqlite3.Connection, table: str, column: str, value: Any) -> Callable[[], bool]:
    return lambda: count(conn, f"{table} WHERE {column} = ?", value) > 0


class World:
    """One profile's learner database, the device database, the profile folder and a trace store, with one or more
    rows of every row class of TABLE DAT-08a."""

    def __init__(self, tmp: Path) -> None:
        self.settings = Settings()
        self.dir = tmp / "profile"
        self.learner: Learner = make_learner(clock=Clock(B))
        self.L = self.learner.conn
        self.D = device_db()
        self.traces = TraceStore(
            tmp / "traces" / "traces.db",
            max_bytes=self.settings.trace_store_max_bytes,
            retention_days=self.settings.trace_retention_days,
            clock_ms=lambda: B + 2 * DAY_MS,
        )
        # (expiry, label, still present?, check after removal)
        self.schedule: list[tuple[int, str, Callable[[], bool], Callable[[int], None] | None]] = []

    def run(self, now: int) -> dict[str, int]:
        return run_retention(
            self.L,
            self.D,
            self.settings,
            now_ms=now,
            profile_dir=self.dir,
            log=self.learner.log,
            fold=self.learner.projector.apply,
            prune_traces=self.traces.prune,
        )

    def expect(
        self, expiry: int, label: str, present: Callable[[], bool], after: Callable[[int], None] | None = None
    ) -> None:
        self.schedule.append((expiry, label, present, after))

    # --- seeding ------------------------------------------------------------------------------------------------

    def seed(self) -> None:
        L, D = self.L, self.D
        L.execute(
            "INSERT INTO study_notes (note_id, text, source, created_at, updated_at)"
            " VALUES (?, 'Fictional revision note', 'voice', ?, ?)",
            ("nt_" + "1" * 26, B, B),
        )
        L.execute("INSERT INTO meta VALUES (1, ?, 1, ?, '0.0.0', ?, '0.0.0')", (PROFILE, B, B))
        L.execute(
            "INSERT INTO consents (consent_id, scope, granted_by_role, granted_by_label, notice_version,"
            " dpia_ref, method, granted_at) VALUES ('con_1', 'research_use', 'guardian', 'Guardian',"
            " 'n1', 'dpia1', 'in_app_guardian', ?)",
            (B,),
        )
        L.execute("INSERT INTO sync_cursors VALUES ('peer_1', 'out', 3, ?)", (B,))
        D.execute(
            "INSERT INTO device (singleton, device_id, hardware_binding, install_kind, created_at, schema_version)"
            " VALUES (1, ?, ?, 'family', ?, 1)",
            ("d" * 32, b"\0" * 32, B),
        )
        D.execute(
            "INSERT INTO profiles_index (profile_id, kind, display_name, avatar, db_file, keystore_ref,"
            " profile_auth_epoch, created_at) VALUES (?, 'student', 'Test', 'a1', 'profiles/p/learner.db', 'k1', 2, ?)",
            (PROFILE, B),
        )
        L.execute("INSERT INTO support_shares VALUES ('ses_3', ?, NULL)", (B,))
        D.execute("INSERT INTO online_features (feature) VALUES ('telemetry')")
        D.execute("INSERT INTO app_settings VALUES ('k', '1', ?)", (B,))
        D.execute("INSERT INTO migrations VALUES ('device', 'device.db', 1, ?, '0.0.0', NULL)", (B,))
        self.sessions()
        self.transcripts()
        self.learner_rows()
        self.files()
        self.notes()
        self.device_rows()

    def sessions(self) -> None:
        for sid, started, ended in (
            ("ses_1", B - HOUR_MS, B),
            ("ses_2", B, B + 60 * DAY_MS),
            ("ses_3", B, None),
            ("ses_4", B + 10 * DAY_MS, B + 10 * DAY_MS + 2 * HOUR_MS),
        ):
            self.L.execute(
                "INSERT INTO sessions (session_id, mode, title, summary, started_at, ended_at)"
                " VALUES (?, 'guided', ?, ?, ?, ?)",
                (sid, f"Title {sid}", f"Summary {sid}", started, ended),
            )

    def transcripts(self) -> None:
        L = self.L
        for sid, expiry in (("ses_1", B + 90 * DAY_MS), ("ses_2", B + 150 * DAY_MS)):
            L.execute(
                "INSERT INTO turns (turn_id, session_id, idx, speaker, status, student_text, started_at)"
                " VALUES (?, ?, 0, 'student', 'complete', 'my working', ?)",
                (f"trn_{sid}", sid, B),
            )
            L.execute(
                "INSERT INTO parts (part_id, turn_id, idx, kind, status, content, created_at, updated_at)"
                " VALUES (?, ?, 0, 'text', 'complete', '{}', ?, ?)",
                (f"prt_{sid}", f"trn_{sid}", B, B),
            )
            L.execute(
                "INSERT INTO checks (check_id, session_id, tool, tool_version, args_sha256, status, result,"
                " created_at) VALUES (?, ?, 'sympy', '1', 'x', 'ok', '{}', ?)",
                (f"chk_{sid}", sid, B),
            )
            L.execute(
                "INSERT INTO board_steps (step_id, session_id, board_id, part_id, idx, latex, owner, status,"
                " check_id, created_at) VALUES (?, ?, 'brd_1', ?, 0, 'x=1', 'tutor', 'final', ?, ?)",
                (f"stp_{sid}", sid, f"prt_{sid}", f"chk_{sid}", B),
            )

            def present(sid: str = sid) -> bool:
                return sum(count(L, f"{t} WHERE session_id = ?", sid) for t in ("turns", "board_steps", "checks")) > 0

            def after(now: int, sid: str = sid) -> None:
                assert count(L, "parts WHERE part_id = ?", f"prt_{sid}") == 0
                assert L.execute(
                    "SELECT transcript_purged_at, title, summary FROM sessions WHERE session_id = ?", (sid,)
                ).fetchone() == (now, f"Title {sid}", f"Summary {sid}")

            self.expect(expiry, f"transcript {sid}", present, after)

    def learner_rows(self) -> None:
        L = self.L
        for rid, state, updated, expiry in (
            ("run_done", "completed", B, B + 90 * DAY_MS),
            ("run_stop", "stopped", B + HOUR_MS, B + 90 * DAY_MS + HOUR_MS),
            ("run_live", "in_progress", B, None),
        ):
            L.execute("INSERT INTO assessment_runs VALUES (?, 'diagnostic', ?, '{}', ?)", (rid, state, updated))
            if expiry is not None:
                self.expect(expiry, rid, has(L, "assessment_runs", "assessment_id", rid))
        for qid, sid, created, expires, expiry in (
            ("q_expires", "ses_2", B, B + 10 * DAY_MS, B + 10 * DAY_MS),
            ("q_age", "ses_2", B + 5 * DAY_MS, FAR, B + 95 * DAY_MS),
        ):
            L.execute("INSERT INTO saved_questions VALUES (?, ?, '{}', 'kept', ?, ?)", (qid, sid, created, expires))
            self.expect(expiry, qid, has(L, "saved_questions", "question_id", qid))
        # The transcript of ses_1 goes at B+90d, before this report's own 90 days.
        L.execute("INSERT INTO problem_reports VALUES ('pr_1', 'ses_1', '{}', ?, ?)", (B + 30 * DAY_MS, FAR))
        self.expect(
            B + 90 * DAY_MS, "problem report with its transcript", has(L, "problem_reports", "report_id", "pr_1")
        )
        for aid, epoch, expires, consumed, expiry in (
            ("aa_expires", 2, B + 5 * MINUTE_MS, None, B + 5 * MINUTE_MS),
            ("aa_used", 2, FAR, B + MINUTE_MS, B + MINUTE_MS),
        ):
            L.execute(
                "INSERT INTO archive_authorizations VALUES (?, '[\"ses_1\"]', 0, ?, ?, ?)",
                (aid, epoch, expires, consumed),
            )
            self.expect(expiry, aid, has(L, "archive_authorizations", "authorization_id", aid))
        L.execute(
            "INSERT INTO exams (exam_id, paper_ref, status, duration_ms, submitted_at)"
            " VALUES ('exm_1', 'pack:paper', 'marked', 3600000, ?)",
            (B + 3 * DAY_MS,),
        )
        L.execute("INSERT INTO exam_answers VALUES ('exm_1', 'i1', '\"12\"', 0, 1.0, 2.0, ?)", (B + 3 * DAY_MS,))
        L.execute("INSERT INTO exam_answers VALUES ('exm_1', 'i2', '\"7\"', 0, NULL, NULL, ?)", (B + 3 * DAY_MS,))
        self.expect(
            B + 93 * DAY_MS,
            "graded exam answer",
            lambda: count(L, "exam_answers WHERE item_ref = 'i1' AND answer IS NOT NULL") > 0,
            lambda now: self._marks_kept(),
        )
        L.execute("INSERT INTO idempotency_responses VALUES ('idem_l', 'x', 200, '{}', ?)", (B,))
        self.expect(
            B + 24 * HOUR_MS, "learner idempotency", has(L, "idempotency_responses", "idempotency_key", "idem_l")
        )
        for cid, sid, created, expiry in (
            ("cp_s1", "ses_1", B - 30 * MINUTE_MS, B + 7 * DAY_MS),
            ("cp_s2_1", "ses_2", B + 1 * DAY_MS, B + 67 * DAY_MS),
            ("cp_s2_2", "ses_2", B + 2 * DAY_MS, B + 67 * DAY_MS),
            ("cp_s2_3", "ses_2", B + 3 * DAY_MS, B + 67 * DAY_MS),
        ):
            L.execute("INSERT INTO checkpoints VALUES (?, ?, NULL, 1, 'turn', '{}', 1, ?)", (cid, sid, created))
            self.expect(expiry, cid, has(L, "checkpoints", "checkpoint_id", cid))
        L.execute("INSERT INTO digests VALUES ('dig_1', '2025-10-06', '{}', ?, NULL)", (B,))
        self.expect(B + 26 * WEEK_MS, "digest", has(L, "digests", "digest_id", "dig_1"))
        for alert, dismissed in (("al_dismissed", B + DAY_MS), ("al_open", None)):
            L.execute(
                "INSERT INTO alerts VALUES (?, 'inactive', 'info', 'parent', '{}', ?, NULL, ?)", (alert, B, dismissed)
            )
        self.expect(B + 91 * DAY_MS, "dismissed alert", has(L, "alerts", "alert_id", "al_dismissed"))
        L.execute("INSERT INTO audit_log VALUES ('aud_1', 'student', 'export', NULL, NULL, ?)", (B,))
        self.expect(B + 400 * DAY_MS, "audit log", has(L, "audit_log", "audit_id", "aud_1"))
        L.execute(
            "INSERT INTO exports VALUES ('exp_1', 'parent_report', 'file', 'self', NULL, NULL, 'h', ?)", (B + DAY_MS,)
        )
        self.expect(B + 401 * DAY_MS, "export record", has(L, "exports", "export_id", "exp_1"))

    def _marks_kept(self) -> None:
        rows = self.L.execute("SELECT item_ref, answer, marks_awarded FROM exam_answers ORDER BY item_ref").fetchall()
        assert rows == [("i1", None, 1.0), ("i2", '"7"', None)]

    def files(self) -> None:
        L = self.L
        attachments = self.dir / "attachments"
        attachments.mkdir(parents=True)
        for name, sid, created, delete_after, expiry in (
            ("by_age", "ses_2", B + DAY_MS, FAR, B + 31 * DAY_MS),
            ("by_delete_after", "ses_2", B, B + 2 * DAY_MS, B + 2 * DAY_MS),
            ("by_transcript", "ses_1", B + 80 * DAY_MS, FAR, B + 90 * DAY_MS),
        ):
            attachment_id = "img_" + new_ulid(created)
            (attachments / f"{name}.png").write_bytes(b"synthetic")
            L.execute(
                "INSERT INTO attachments (attachment_id, session_id, kind, file_path, sha256, bytes, created_at,"
                " delete_after) VALUES (?, ?, 'photo', ?, 'h', 9, ?, ?)",
                (attachment_id, sid, f"{name}.png", created, delete_after),
            )

            def present(attachment_id: str = attachment_id, path: Path = attachments / f"{name}.png") -> bool:
                row = count(L, "attachments WHERE attachment_id = ?", attachment_id) > 0
                assert row == path.exists(), "an attachment row and its file go together"
                return row

            self.expect(expiry, f"attachment {name}", present)
        spill = self.dir / "spill"
        for sid, expiry in (
            ("ses_1", B),  # ended at B
            ("ses_2", B + 24 * HOUR_MS),  # still open at 24 h: the hard maximum
            ("ses_3", B + 24 * HOUR_MS),
            ("ses_4", B + 10 * DAY_MS + 2 * HOUR_MS),  # ended within 24 h
            ("ses_orphan", B + 29 * HOUR_MS),  # no session row: 24 h after its last write
        ):
            (spill / sid).mkdir(parents=True)
            (spill / sid / "spill_abc").write_text("synthetic")
            self.expect(expiry, f"spill {sid}", (spill / sid).exists)
        os.utime(spill / "ses_orphan", ((B + 5 * HOUR_MS) / 1000, (B + 5 * HOUR_MS) / 1000))
        self.traces.submit({"trace_id": "trc_1", "profile_ref": "p", "session_ref": "s", "pad": "x"})
        self.traces.flush()
        self.expect(B + 16 * DAY_MS, "trace record", lambda: bool(self.traces.records()))

    def notes(self) -> None:
        for note_id, written, expires, expiry in (
            ("01J9ZZN0TE0000000000000001", B + DAY_MS, None, B + 181 * DAY_MS),
            ("01J9ZZN0TE0000000000000002", B + 2 * DAY_MS, B + 20 * DAY_MS, B + 20 * DAY_MS),
        ):
            payload: dict[str, Any] = {
                "note_id": note_id,
                "text": "Draws the graph first",
                "source_event_ids": [new_ulid(B)],
                "status": "active",
            }
            if expires is not None:
                payload["expires_at"] = iso_ms(expires)
            self.learner.record("note_written", payload, source="reflector", occurred_at=written, writer=NOTES_WRITER)
            self.expect(
                expiry,
                f"note {note_id[-1]}",
                lambda n=note_id: count(self.L, "notes WHERE note_id = ? AND status <> 'deleted'", n) > 0,
                lambda now, n=note_id: self._note_deleted(n),
            )

    def _note_deleted(self, note_id: str) -> None:
        L = self.L
        assert L.execute("SELECT status, text FROM notes WHERE note_id = ?", (note_id,)).fetchone() == ("deleted", "")
        deleted = [
            json.loads(r[0])
            for r in L.execute(
                "SELECT payload FROM events WHERE type = 'note_deleted' AND json_extract(payload, '$.note_id') = ?",
                (note_id,),
            )
        ]
        assert deleted == [{"note_id": note_id, "actor_role": "system_expiry"}]
        assert (
            count(
                L,
                "events WHERE type = 'note_written' AND erased_at IS NULL AND json_extract(payload, '$.note_id') = ?",
                note_id,
            )
            == 0
        )
        assert count(L, "notes_fts WHERE notes_fts MATCH 'graph'") == count(L, "notes WHERE text LIKE '%graph%'")

    def device_rows(self) -> None:
        D = self.D
        for oid, kind, created, expires, delivered, expiry, audit in (
            ("ob_delivered", "backup_snapshot", B, FAR, B + HOUR_MS, B + HOUR_MS, None),
            ("ob_tombstone", "tombstone", B, FAR, None, B + 365 * DAY_MS, "tombstone.expired"),
            (
                "ob_withdrawal",
                "consent_withdrawal",
                B,
                B + 30 * DAY_MS,
                None,
                B + 30 * DAY_MS,
                "consent_withdrawal.expired",
            ),
            ("ob_telemetry", "telemetry", B, FAR, None, B + 14 * DAY_MS, None),
            ("ob_snapshot", "backup_snapshot", B, B + 3 * DAY_MS, None, B + 3 * DAY_MS, None),
        ):
            D.execute(
                "INSERT INTO outbox (outbox_id, idempotency_key, kind, profile_id, destination, payload, bytes,"
                " created_at, delivered_at, expires_at) VALUES (?, ?, ?, ?, 'dest', x'00', 1, ?, ?, ?)",
                (oid, f"k_{oid}", kind, PROFILE, created, delivered, expires),
            )

            def after(now: int, oid: str = oid, audit: str | None = audit) -> None:
                rows = D.execute(
                    "SELECT action, profile_id, at FROM device_audit WHERE json_extract(detail, '$.outbox_id') = ?",
                    (oid,),
                ).fetchall()
                assert rows == ([(audit, PROFILE, now)] if audit else [])

            self.expect(expiry, oid, has(D, "outbox", "outbox_id", oid), after)
        D.execute(
            "INSERT INTO egress_ledger VALUES ('eg_1', ?, 'downloads', 'example.invalid', 10, 'pack', NULL)", (B,)
        )
        self.expect(B + 90 * DAY_MS, "egress ledger", has(D, "egress_ledger", "ledger_id", "eg_1"))
        D.execute("INSERT INTO idempotency_responses VALUES ('idem_d', 'x', 200, '{}', ?)", (B + HOUR_MS,))
        self.expect(
            B + 25 * HOUR_MS, "device idempotency", has(D, "idempotency_responses", "idempotency_key", "idem_d")
        )
        D.execute("INSERT INTO device_audit VALUES ('da_1', 'user', 'online_feature.enable', NULL, NULL, ?)", (B,))
        self.expect(B + 400 * DAY_MS, "device audit", has(D, "device_audit", "audit_id", "da_1"))
        for cid, scope, withdrawn in (
            ("dc_withdrawn", "telemetry", B + 2 * DAY_MS),
            ("dc_active", "crash_reports", None),
        ):
            D.execute(
                "INSERT INTO device_consents VALUES (?, ?, 'device_user', 'n1', 'dpia1', 'in_app_notice', ?, ?)",
                (cid, scope, B, withdrawn),
            )
        self.expect(
            B + 402 * DAY_MS, "withdrawn device consent", has(D, "device_consents", "consent_id", "dc_withdrawn")
        )


def dat08_retention_schedule(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.seed()
    L, D = world.L, world.D
    events_before = count(L, "events")
    # Count limits hold at every run: the newest checkpoints of a session and the newest queued crash reports stay.
    for n in range(5):
        L.execute("INSERT INTO checkpoints VALUES (?, 'ses_3', NULL, 1, 'turn', '{}', 1, ?)", (f"cp_s3_{n}", B + n))
    for n in range(world.settings.crash_reports_queued_max + 2):
        D.execute(
            "INSERT INTO outbox (outbox_id, idempotency_key, kind, destination, payload, bytes, created_at,"
            " expires_at) VALUES (?, ?, 'crash_report', 'dest', x'00', 1, ?, ?)",
            (f"cr_{n:02d}", f"cr_{n:02d}", B - 1000 + n, FAR),
        )
    # An archive authorization from before a lock or PIN reset (an earlier auth epoch) is void at once.
    L.execute("INSERT INTO archive_authorizations VALUES ('aa_stale', '[]', 0, 1, ?, NULL)", (FAR,))
    first = min(expiry for expiry, *_ in world.schedule) - 1
    world.run(first)
    assert count(L, "archive_authorizations WHERE authorization_id = 'aa_stale'") == 0
    kept = [r[0] for r in L.execute("SELECT checkpoint_id FROM checkpoints WHERE session_id = 'ses_3' ORDER BY 1")]
    assert kept == ["cp_s3_2", "cp_s3_3", "cp_s3_4"]
    crash = [r[0] for r in D.execute("SELECT outbox_id FROM outbox WHERE kind = 'crash_report' ORDER BY 1")]
    assert crash == [f"cr_{n:02d}" for n in range(2, world.settings.crash_reports_queued_max + 2)]

    # Each row class goes at its expiry and not one millisecond before.
    by_expiry: dict[int, list[tuple[str, Callable[[], bool], Callable[[int], None] | None]]] = {}
    for expiry, label, present, after in world.schedule:
        by_expiry.setdefault(expiry, []).append((label, present, after))
    assert len(world.schedule) >= 35
    for expiry in sorted(by_expiry):
        world.run(expiry - 1)
        for label, present, _ in by_expiry[expiry]:
            assert present(), f"{label} removed before its expiry"
        world.run(expiry)
        for label, present, after in by_expiry[expiry]:
            assert not present(), f"{label} kept after its expiry"
            if after is not None:
                after(expiry)

    # "Life of the profile" and "life of the installation" rows are never touched by the job.
    world.run(FAR)
    assert count(L, "events") == events_before + 2  # only the two note_deleted events were added
    assert [r[0] for r in L.execute("SELECT session_id FROM sessions ORDER BY 1")] == [f"ses_{n}" for n in (1, 2, 3, 4)]
    assert L.execute("SELECT title, summary FROM sessions WHERE session_id = 'ses_1'").fetchone() == (
        "Title ses_1",
        "Summary ses_1",
    )
    world._marks_kept()
    for table in ("meta", "consents", "sync_cursors", "exams", "support_shares", "study_notes"):
        assert count(L, table) == 1, table
    assert count(L, "assessment_runs") == 1 and count(L, "alerts") == 1
    for table in ("device", "profiles_index", "online_features", "app_settings", "migrations"):
        assert count(D, table) == 1, table
    assert [r[0] for r in D.execute("SELECT consent_id FROM device_consents")] == ["dc_active"]
    world.traces.close()


def _created_tables(sql: str) -> set[str]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(sql)
        # Ordinary and virtual tables; the shadow tables of a full-text index belong to SQLite.
        return {
            r[1]
            for r in conn.execute("PRAGMA table_list")
            if r[2] in ("table", "virtual") and not r[1].startswith("sqlite_")
        }
    finally:
        conn.close()


def dat08_every_table_has_retention() -> None:
    governed: dict[tuple[str, str], list[str]] = {}
    for rule in RULES:
        for table in rule.tables:
            governed.setdefault((rule.database, table), []).append(rule.row_class)
    created = {(kind, table) for kind, sql in DATABASES.items() for table in _created_tables(sql)}
    for kind, table in sorted(created):
        assert len(governed.get((kind, table), [])) == 1, f"{kind}.{table}: {governed.get((kind, table))}"
    assert set(governed) <= created, set(governed) - created
    # The projections rule covers exactly the tables the storage contract marks PROJECTION (DAT-05).
    contract = STORAGE_CONTRACT.read_text()
    learner = contract.split("-- @database learner", 1)[1].split("-- @database device", 1)[0]
    marked = set(re.findall(r"^-- PROJECTION:.*\n(?:--.*\n)*CREATE TABLE (\w+)", learner, re.MULTILINE))
    assert marked == set(PROJECTION_TABLES)
    projections = next(r for r in RULES if r.row_class == "projections")
    assert marked <= set(projections.tables) and projections.purge is None
    # Every period is a configuration key; the "life of" rows have none and nothing purges them.
    for rule in RULES:
        assert all(key in Settings.model_fields for key in rule.keys), rule.row_class
        assert (rule.purge is None) == (not rule.keys) == bool(rule.removed_by), rule.row_class
    retention_keys = {k for k in Settings.model_fields if k.startswith("retention_")} - {"retention_job_interval_h"}
    assert retention_keys <= {k for r in RULES for k in r.keys}


def _transcript_rows(conn: sqlite3.Connection) -> None:
    """Session rows and a transcript for every session in the log, as the transcript store would have written."""
    sessions = conn.execute(
        "SELECT session_id, min(occurred_at), max(occurred_at) FROM events WHERE session_id IS NOT NULL"
        " GROUP BY session_id"
    ).fetchall()
    for n, (sid, started, ended) in enumerate(sessions):
        conn.execute(
            "INSERT INTO sessions (session_id, mode, title, summary, started_at, ended_at)"
            " VALUES (?, 'guided', 'A session', 'Its summary', ?, ?)",
            (sid, started, ended),
        )
        conn.execute(
            "INSERT INTO turns (turn_id, session_id, idx, speaker, status, started_at)"
            " VALUES (?, ?, 0, 'student', 'complete', ?)",
            (f"trn_{n}", sid, started),
        )
        conn.execute(
            "INSERT INTO parts (part_id, turn_id, idx, kind, status, content, created_at, updated_at)"
            " VALUES (?, ?, 0, 'text', 'complete', '{}', ?, ?)",
            (f"prt_{n}", f"trn_{n}", started, started),
        )


MASTERY = ("kc_mastery", "subject_ability", "attempts", "review_cards", "learner_misconceptions")


def _dump(conn: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in MASTERY}  # noqa: S608


def dat08_purge_keeps_mastery(tmp_path: Path) -> None:
    for seed in (1, 2, 3):
        clock = Clock()
        learner = random_log(seed, sessions=5, learner=make_learner(learner_db(), clock=clock), clock=clock)
        conn = learner.conn
        _transcript_rows(conn)
        before, events = _dump(conn), count(conn, "events")
        checksum = learner.projector.checksum("kc_mastery")
        assert before["kc_mastery"], "the log produced mastery to keep"
        # Late enough that every transcript is due; notes may expire too, which must not move mastery either.
        last_end = conn.execute("SELECT max(ended_at) FROM sessions").fetchone()[0]
        now = last_end + Settings().retention_transcript_days * DAY_MS
        run_retention(
            conn,
            device_db(),
            Settings(),
            now_ms=now,
            profile_dir=tmp_path / f"p{seed}",
            log=learner.log,
            fold=learner.projector.apply,
        )
        assert count(conn, "turns") == count(conn, "parts") == 0
        assert count(conn, "sessions WHERE transcript_purged_at IS NULL") == 0
        assert count(conn, "sessions WHERE title = 'A session' AND summary = 'Its summary'") == count(conn, "sessions")
        assert count(conn, "events") >= events  # nothing is deleted from the log
        assert _dump(conn) == before
        # And a rebuild from the log after the purge gives the same mastery.
        learner.projector.rebuild()
        assert learner.projector.checksum("kc_mastery") == checksum
        assert _dump(conn) == before
