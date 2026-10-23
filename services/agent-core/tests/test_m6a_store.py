"""M6.a: the storage schema, its conventions and the migration runner (DAT-03, DAT-12)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from agent_core.store.generated.schema import DATABASES
from agent_core.store.sqlite import (
    MIGRATIONS,
    Migration,
    MigrationError,
    NewerDatabaseError,
    backup_path,
    open_database,
    record_migrations,
    schema_version,
)

REPO = Path(__file__).resolve().parents[3]
SCHEMAS = REPO / "services/agent-core/agent_core/contracts/schemas"
sys.path.insert(0, str(REPO / "scripts"))

from jana_tools.schema_lint import lint, schema_errors  # noqa: E402


def dat03_schema_lint(tmp_path: Path) -> None:
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    assert lint(DATABASES, conn) == []
    conn.close()
    # The lint catches each convention it guards.
    bad = {
        "learner": "CREATE TABLE Loose (id TEXT PRIMARY KEY, body TEXT DEFAULT '{}');\n"
        "CREATE TABLE anyish (id TEXT PRIMARY KEY, v ANY, seen_at TEXT, on_off TEXT CHECK (on_off IN (0,1))) STRICT;\n"
    }
    errors = "\n".join(schema_errors(bad))
    for expected in (
        "learner.Loose: not STRICT",
        "table name is not snake_case",
        "learner.Loose.body: JSON column without CHECK",
        "learner.anyish.v: column type ANY",
        "learner.anyish.seen_at: timestamp must be INTEGER",
        "learner.anyish.on_off: boolean must be INTEGER",
    ):
        assert expected in errors, errors
    plain = sqlite3.connect(tmp_path / "plain.db")
    plain.execute("PRAGMA synchronous=NORMAL")  # some builds default to FULL; the lint must not rely on that
    assert {e.split(" is ")[0] for e in lint({}, plain)} == {
        "pragma journal_mode",
        "pragma synchronous",
        "pragma foreign_keys",
        "pragma secure_delete",
        "pragma recursive_triggers",
    }
    plain.close()


def dat03_schema_applies(tmp_path: Path) -> None:
    assert set(DATABASES) == {"learner", "device"}
    for kind in DATABASES:
        conn, applied = open_database(tmp_path / f"{kind}.db", kind)
        assert [a.version for a in applied] == [m.version for m in MIGRATIONS[kind]]
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        assert ("meta" if kind == "learner" else "device") in names
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.close()


def _enum(contract: str, pointer: str) -> set[str]:
    node = json.loads((SCHEMAS / f"{contract}.schema.json").read_text())
    for key in pointer.strip("/").split("/"):
        node = node[int(key)] if isinstance(node, list) else node[key]
    return set(node["enum"])


def _checks(kind: str) -> dict[tuple[str, str], set[str]]:
    from jana_tools.schema_lint import columns, tables

    out: dict[tuple[str, str], set[str]] = {}
    for table, (_, create) in tables(DATABASES[kind]).items():
        for name, definition in columns(create).items():
            import re

            match = re.search(rf"\b{name}\s+IN\s*\(([^)]*)\)", definition)
            if match:
                out[(table, name)] = set(re.findall(r"'([^']*)'", match.group(1)))
    return out


# Columns that mirror a contract enum (DAT-03): (table, column) → (contract, JSON pointer to the enum).
EVENTS = "api/events"
LEARNING = "learning/learning-event"
MODEL = "learning/learner-model"
MIRRORS: dict[tuple[str, str], tuple[str, str]] = {
    ("parts", "kind"): (EVENTS, "/$defs/part_kind"),
    ("parts", "status"): (EVENTS, "/$defs/ev_part_end/properties/status"),
    ("parts", "card_type"): (EVENTS, "/$defs/card_kind"),
    ("board_steps", "owner"): (EVENTS, "/$defs/step_owner"),
    ("board_steps", "status"): (EVENTS, "/$defs/board_step_status"),
    ("board_steps", "error_category"): (EVENTS, "/$defs/step_error_category"),
    ("events", "source"): (LEARNING, "/$defs/envelope/properties/source"),
    ("sessions", "mode"): (LEARNING, "/$defs/payload_session_started/properties/mode"),
    ("sessions", "subject"): (LEARNING, "/$defs/subject"),
    ("sessions", "hardware_class"): (LEARNING, "/$defs/payload_session_started/properties/hardware_class"),
    ("sessions", "end_reason"): (LEARNING, "/$defs/payload_session_ended/properties/reason"),
    ("attempts", "mode"): (LEARNING, "/$defs/payload_attempt/properties/mode"),
    ("attempts", "outcome"): (LEARNING, "/$defs/payload_verdict/properties/outcome"),
    ("attempts", "error_category"): (LEARNING, "/$defs/payload_verdict/properties/error_category"),
    ("settings", "key"): (LEARNING, "/$defs/payload_setting_change/properties/setting"),
    ("notes", "subject"): (LEARNING, "/$defs/subject"),
    ("profile", "level"): (MODEL, "/$defs/profile/properties/level"),
    ("profile", "reading_level"): (MODEL, "/$defs/profile/properties/reading_level"),
    ("profile", "support_level"): (MODEL, "/$defs/profile/properties/support_level"),
    ("kc_mastery", "status"): (MODEL, "/$defs/kc_state/properties/status"),
    ("kc_mastery", "mastery_check_state"): (MODEL, "/$defs/kc_state/properties/mastery_check/properties/state"),
    ("review_cards", "state"): (MODEL, "/$defs/review_card/properties/state"),
    ("learner_misconceptions", "status"): (MODEL, "/$defs/misconception/properties/status"),
    ("preferences", "key"): (MODEL, "/$defs/preferences/properties/student_overrides/items"),
}
# turns.status is the turn.end status plus 'open', the value a turn holds until turn.end arrives.
SUPERSETS = {("turns", "status"): ((EVENTS, "/$defs/ev_turn_end/properties/status"), {"open"})}


def dat03_enums_match_contracts() -> None:
    checks = _checks("learner")
    mismatches = []
    for column, (contract, pointer) in MIRRORS.items():
        if checks[column] != _enum(contract, pointer):
            mismatches.append((column, checks[column] ^ _enum(contract, pointer)))
    for column, ((contract, pointer), extra) in SUPERSETS.items():
        if checks[column] != _enum(contract, pointer) | extra:
            mismatches.append((column, checks[column] ^ (_enum(contract, pointer) | extra)))
    device = _checks("device")
    if device[("device", "hardware_class")] != checks[("sessions", "hardware_class")]:
        mismatches.append((("device", "hardware_class"), set()))
    assert mismatches == []


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO meta VALUES (1, '01J0000000000000000000PROF', 1, 1, '0.0.0', 1, '0.0.0')",
    )


def dat12_failed_migration_rollback(tmp_path: Path) -> None:
    # The migration under test is the one after the latest the app ships (the learner store has several, DAT-12).
    latest = MIGRATIONS["learner"][-1].version
    following = latest + 1
    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner")
    _seed(conn)
    conn.execute("UPDATE meta SET schema_version = ?", (latest,))
    conn.close()
    broken = (
        *MIGRATIONS["learner"],
        Migration(following, "CREATE TABLE added_next (id TEXT PRIMARY KEY) STRICT;\nINSERT INTO missing VALUES (1);"),
    )
    with pytest.raises(MigrationError):
        open_database(path, "learner", broken)
    # The original is usable at its previous version, untouched by the half-run migration, and a copy was kept.
    conn, applied = open_database(path, "learner")
    assert applied == []
    assert schema_version(conn) == latest
    profile = "01J0000000000000000000PROF"
    assert conn.execute("SELECT schema_version, profile_id FROM meta").fetchone() == (latest, profile)
    assert conn.execute("SELECT 1 FROM sqlite_schema WHERE name = 'added_next'").fetchone() is None
    conn.close()
    # That successful open released the copy; a good next migration records itself, keeping a fresh copy.
    assert not backup_path(path, latest).exists()
    good = (*MIGRATIONS["learner"], Migration(following, "CREATE TABLE added_next (id TEXT PRIMARY KEY) STRICT;\n"))
    conn, applied = open_database(path, "learner", good)
    assert [(a.version, a.backup_file) for a in applied] == [(following, backup_path(path, latest).name)]
    assert conn.execute("SELECT schema_version FROM meta").fetchone() == (following,)
    assert backup_path(path, latest).exists()
    conn.close()
    device, _ = open_database(tmp_path / "device.db", "device")
    record_migrations(device, "learner", "learner.db", applied, "0.0.0", 2)
    assert device.execute("SELECT db_kind, version, backup_file FROM migrations").fetchall() == [
        ("learner", following, f"learner.db.pre-v{latest}.bak")
    ]
    device.close()


def dat12_newer_db_refused(tmp_path: Path) -> None:
    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner")
    _seed(conn)
    conn.execute("UPDATE meta SET schema_version = ?", (MIGRATIONS["learner"][-1].version + 1,))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    with pytest.raises(NewerDatabaseError) as raised:
        open_database(path, "learner")
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    assert before == after
    # The refusal carries the message key the profile picker shows (G51).
    assert raised.value.message_key == "profile.newer_app"
    _newer_profile_refused_at_unlock(tmp_path / "app")


def _newer_profile_refused_at_unlock(data_dir: Path) -> None:
    """Through the API (G51): unlocking a profile saved by a newer app is refused with the picker's message key before
    any token is issued, and the profile's files stay as they were."""
    import asyncio

    from api_harness import start_core, stop_core
    from test_m10a_profiles import Api, code, student

    async def first() -> str:
        r = await start_core(data_dir, worker=False)
        try:
            api = Api(r)
            return await api.add(student("Ama"))
        finally:
            await stop_core(r)

    async def after_newer_app(profile: str) -> tuple[int, str, dict, list]:
        r = await start_core(data_dir, worker=False)
        try:
            api = Api(r)
            path = r.runtime.directory.learner_path(profile)
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.parent.iterdir()}
            refused = await api.unlock(profile)
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.parent.iterdir()}
            assert before == after
            listed = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            return refused.status_code, code(refused), refused.json()["error"].get("details") or {}, listed
        finally:
            await stop_core(r)

    loop = asyncio.new_event_loop()
    try:
        profile = loop.run_until_complete(first())
        learner = next((data_dir / "profiles" / profile[4:]).glob("*.db"))
        conn = sqlite3.connect(learner)
        conn.execute("UPDATE meta SET schema_version = ?", (MIGRATIONS["learner"][-1].version + 1,))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        status, error, details, listed = loop.run_until_complete(after_newer_app(profile))
    finally:
        loop.close()
    assert (status, error, details) == (426, "upgrade_required", {"message_key": "profile.newer_app"})
    assert [p["profile_id"] for p in listed] == [profile]  # still listed, so the picker can say why it will not open
