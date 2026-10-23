"""PRV-03: onboarding asks for and stores no name other than a display name and no birth date. The inventory half
(prv03_inventory_covers_schema) is in scripts/tests/test_prv03_data_minimisation.py. Synthetic profile only."""

import json
import re
import sqlite3
from pathlib import Path

from agent_core.contracts.api.commands import CreateProfile
from agent_core.store.generated.schema import DATABASES
from api_harness import start_core, stop_core
from test_m10a_profiles import LOOP, Api, student

COMMANDS = Path(__file__).resolve().parents[1] / "agent_core" / "contracts" / "schemas" / "api" / "commands.schema.json"
# Everything profile creation may ask for: a nickname, a picture token and the study facts. No PIN (D86).
ONBOARDING_FIELDS = {"display_name", "avatar", "age_band", "level", "subjects", "exam_date"}
PERSONAL = re.compile(
    r"(^|_)(name|names|surname|forename|firstname|lastname|given|family|birth|birthday|dob|born|address|street|"
    r"postcode|zip|phone|mobile|tel|email|mail|contact|school|gender|sex|nationality|religion|ethnicity)(_|$)"
)
DISPLAY_NAME = "Comet"  # a nickname, as onboarding suggests


def _personal(names: set[str]) -> set[str]:
    return {n for n in names if n != "display_name" and PERSONAL.search(n)}


def _columns(kind: str, table: str) -> set[str]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(DATABASES[kind])
        return {row[1] for row in conn.execute("SELECT * FROM pragma_table_info(?)", (table,))}
    finally:
        conn.close()


def _row(path: Path, table: str, profile_id: str) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = f"SELECT * FROM {table} WHERE profile_id IN (?, ?)"  # noqa: S608 - fixed table names
        rows = conn.execute(query, (profile_id, profile_id.removeprefix("prf_"))).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, (path, table, len(rows))
    return dict(rows[0])


def prv03_onboarding_minimal_fields(tmp_path: Path):
    # The contract: CreateProfile asks for nothing personal beyond a display name of at most 40 characters and an
    # age band (never a birth date), and refuses any field it does not name.
    schema = json.loads(COMMANDS.read_text())["$defs"]["CreateProfile"]
    assert set(schema["properties"]) == set(CreateProfile.model_fields) == ONBOARDING_FIELDS
    assert schema["additionalProperties"] is False
    assert schema["properties"]["display_name"]["maxLength"] == 40
    assert set(schema["required"]) == {"display_name", "avatar", "age_band", "level", "subjects"}
    assert _personal(ONBOARDING_FIELDS) == set()

    # The stores: the learner `profile` table and the device's `profiles_index` hold no name, birth date, address,
    # phone or e-mail column; the display name is capped at 40 characters in both.
    profile_columns, index_columns = _columns("learner", "profile"), _columns("device", "profiles_index")
    assert {"display_name", "age_band", "level", "subjects", "exam_date"} <= profile_columns
    assert _personal(profile_columns) == set() and _personal(index_columns) == set()
    for kind in ("learner", "device"):
        assert "CHECK (length(display_name) BETWEEN 1 AND 40)" in DATABASES[kind]

    # The flow: a profile with only the minimal fields, over the real local API (no adult setup, D86).
    async def scenario() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            for extra in ({"surname": "Mensah"}, {"date_of_birth": "2011-03-04"}, {"email": "a@example.org"}):
                refused = await api.call("POST", "/v1/profiles", {**student(DISPLAY_NAME), **extra})
                assert refused.status_code in (400, 422), (extra, refused.status_code)
            too_long = await api.call("POST", "/v1/profiles", student("x" * 41))
            assert too_long.status_code in (400, 422)
            body = {**student(DISPLAY_NAME), "exam_date": "2027-06-01"}
            profile_id = await api.add(body)
            unlocked = await api.unlock(profile_id)
            assert unlocked.status_code == 200 and unlocked.json()["profile_token"]  # onboarding is complete
            listed = (await api.call("GET", "/v1/profiles")).json()
        finally:
            await stop_core(r)
        learner_db = tmp_path / "profiles" / profile_id.removeprefix("prf_") / "learner.db"
        return (
            _row(learner_db, "profile", profile_id),
            _row(tmp_path / "device.db", "profiles_index", profile_id),
            listed,
        )

    profile, index, listed = LOOP.run_until_complete(scenario())

    assert profile["display_name"] == index["display_name"] == DISPLAY_NAME
    assert profile["age_band"] == "13_15" and profile["level"] == "O"
    assert "physics" in str(profile["subjects"]) and str(profile["exam_date"]).startswith("2027-06")
    # Nothing else in either row repeats the name or holds a calendar date other than the exam date: every other
    # value is an id, a picture token, a fixed choice, a JSON setting, a hash or a timestamp.
    for row in (profile, index):
        for column, value in row.items():
            if column == "display_name":
                continue
            assert DISPLAY_NAME not in str(value), column
            if column != "exam_date" and isinstance(value, str):
                assert not re.search(r"\b(19|20)\d\d-\d\d", value), (column, value)
    assert DISPLAY_NAME in json.dumps(listed)
