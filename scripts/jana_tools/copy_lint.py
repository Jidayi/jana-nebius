"""The copy linter for minors (LRN-35): no dark patterns in any locale file.

Each rule names a pattern LRN-35 bans and the phrasings that carry it: loss-framed streak messages, countdown pressure
outside mock exams, variable or random rewards, leaderboards and peer rankings, guilt after missed days, purchase or
upgrade prompts inside learning flows, infinite feeds, fake scarcity and praise of the person (praise the work, never
the person). The phrase list is the project's own; it is checked over every message of every catalogue in
`packages/i18n/locales`, and any other copy a caller passes (the core's plan card text, for one).

Scopes: countdown wording is allowed in the mock-exam keys (`mock.`), where a timed sitting is the point; purchase
wording is banned only in the learning flows (the keys below), since Settings names the subscription plainly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import REPO_ROOT

LOCALES = REPO_ROOT / "packages" / "i18n" / "locales"
# Key prefixes of the learning flows: the tutor, lessons, practice, the board, plans, progress and their cards.
LEARNING_FLOWS = (
    "tutor.", "card.", "input.", "lesson.", "board.", "check.", "practice.", "home.", "map.", "sheet.", "notes.",
    "mastery.", "dock.", "composer.", "transcript.", "turn.", "message.", "calm.", "maths.", "part.", "assessment.",
    "visual.", "sim.", "plan.", "progress.", "streak.", "knows.",
)  # fmt: skip


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    only: tuple[str, ...] = ()  # key prefixes the rule applies to (empty: every key)
    except_: tuple[str, ...] = ()  # key prefixes the rule never applies to


def _p(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{a})" for a in alternatives), re.IGNORECASE)


RULES = (
    Rule("loss_framed_streak", _p(
        r"\b(lose|lost|losing|break|broke|broken|end|ends|ended)\b[^.]{0,25}\bstreak",
        r"\bstreak\b[^.]{0,25}\b(lost|gone|over|at risk|broken|ends?|ended|dies?)\b",
        r"\bdon'?t (lose|break|miss)\b",
    )),
    Rule("countdown_pressure", _p(
        r"\bhurry\b", r"\btime is running out\b", r"\bbefore it'?s too late\b",
        r"\bonly \{?\w*\}? ?(minutes?|hours?|days?|seconds?) left\b", r"\bact (now|fast)\b", r"\bquick,? before\b",
    ), except_=("mock.",)),
    Rule("random_reward", _p(
        r"\bmystery (reward|prize|box|gift)\b", r"\bspin (the|to win)\b", r"\blucky (draw|spin)\b",
        r"\brandom (reward|prize|bonus)\b", r"\bloot\b", r"\bjackpot\b", r"\bsurprise (reward|prize)\b",
    )),
    Rule("leaderboard", _p(
        r"\bleaderboards?\b", r"\branked\b", r"\branking\b", r"\btop \d+ (students|learners|pupils)\b",
        r"\bbeat (your )?(friends|classmates|others)\b", r"\bbetter than \{?\w+\}?%? of\b",
    )),
    Rule("guilt", _p(
        r"\bwe missed you\b", r"\byou (missed|skipped|forgot)\b[^.]{0,20}\b(day|days|lesson|practice|study)",
        r"\byou haven'?t (studied|practised|practiced|been)\b", r"\bdisappointed\b",
        r"\byou let\b[^.]{0,20}down", r"\bshame\b",
    )),
    Rule("purchase_in_learning", _p(
        r"\bupgrade\b", r"\bbuy\b", r"\bpurchase\b", r"\bsubscribe\b", r"\bgo premium\b",
        r"\bunlock (more|premium|everything|full)\b", r"\bpay (now|to)\b",
    ), only=LEARNING_FLOWS),
    Rule("infinite_feed", _p(r"\bendless\b", r"\binfinite (scroll|feed)\b", r"\bkeep scrolling\b")),
    Rule("fake_scarcity", _p(
        r"\blimited[- ]time\b", r"\blast chance\b", r"\bonly today\b", r"\bexpires? (soon|today)\b",
        r"\bwhile (stocks|places) last\b", r"\bonly \d+ (places|spots) left\b",
    )),
    Rule("praise_of_person", _p(
        r"\byou'?re (so |really |such an? )?(smart|clever|brilliant|gifted|talented|a genius|a natural)\b",
        r"\bgenius\b", r"\bgood (boy|girl)\b", r"\bsmart (boy|girl|kid|cookie)\b", r"\bnatural talent\b",
        r"\bwhat a star\b",
    )),
)  # fmt: skip


def violations(messages: Mapping[str, str], source: str = "copy") -> list[str]:
    """Every message that matches a banned pattern in its scope, as `source: key: rule ("matched words")`."""
    out = []
    for key, text in sorted(messages.items()):
        for rule in RULES:
            if rule.only and not key.startswith(rule.only):
                continue
            if rule.except_ and key.startswith(rule.except_):
                continue
            found = rule.pattern.search(str(text))
            if found:
                out.append(f'{source}: {key}: {rule.name} ("{found.group(0)}")')
    return out


def locale_files(root: Path = LOCALES) -> list[Path]:
    return sorted(root.glob("*.json"))


def copy_lint_errors(root: Path = LOCALES) -> list[str]:
    """The LRN-35 check over every locale file."""
    out = []
    for path in locale_files(root):
        out += violations(json.loads(path.read_text()), path.name)
    return out
