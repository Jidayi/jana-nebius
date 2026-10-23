"""EVL-22, MEM-26: allow-listed research exports at the API's engine boundary."""

from __future__ import annotations

import sqlite3
from typing import Any

from agent_core.store.exports import research_rows
from agent_core.trace.research import project


def export_rows(conn: sqlite3.Connection) -> dict[str, Any]:
    return project(research_rows(conn))
