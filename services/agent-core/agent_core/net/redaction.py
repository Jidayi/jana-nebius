"""The redaction check on every outgoing cloud request (MDL-25, PRV-25).

A request to a cloud model may carry only what DAT-18 lets leave the device: no name, contact detail, school name or
device identifier, and no profile id (a per-session pseudonym stands in). The check scans the whole request body for
the session's own identifying terms (the profile's display name, its ids, the device id) and for contact details and
identifiers by pattern; any match blocks the request before it leaves, and the router serves it locally."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent_core.config.personal_data import CONTACT, normalise, term_pattern

PATTERNS: dict[str, re.Pattern[str]] = {
    "profile_id": re.compile(r"(?<![^\W_])prf_?[0-9A-HJKMNP-TV-Z]{26}(?![^\W_])", re.I),
    **CONTACT,
}


@dataclass(frozen=True)
class Finding:
    kind: str  # "term" or a pattern name; never the matched text


class Redactor:
    """`terms` are the session's identifying strings: matched case-insensitively as whole terms. Every check runs
    on the normalised request (`config.personal_data.normalise`), so hidden or lookalike characters, fullwidth forms
    and escaped characters cannot carry a term or a contact detail past it."""

    def __init__(self, terms: Iterable[str] = ()) -> None:
        self._terms = term_pattern([t for t in terms if t])

    def findings(self, body: Any) -> list[Finding]:
        text = normalise(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))
        found = [Finding("term")] if self._terms is not None and self._terms.search(text) else []
        found += [Finding(name) for name, pattern in PATTERNS.items() if pattern.search(text)]
        return found

    def blocks(self, body: Any) -> bool:
        return bool(self.findings(body))
