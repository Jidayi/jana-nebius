"""The readability lint (LOC-22): lesson text and interface catalogues in plain English.

For each lesson and each interface catalogue: the average sentence length in words and the Flesch-Kincaid grade, with
subject terms excepted (a subject term counts as one short word: the pack's own vocabulary from its KC names, lesson
titles and misconception names, and the interface's product words). Targets come from configuration: at most
`readability_max_sentence_words` words per sentence, and a grade of at most `readability_max_grade_o` for O level
(interface copy included) or `readability_max_grade_a` for A level. Placeholders (`{count}`, ICU arguments) and LaTeX
are not words."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

CURRICULUM = REPO_ROOT / "content" / "curriculum"
CATALOGUES = (REPO_ROOT / "packages" / "i18n" / "locales" / "en.json",)
_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|[:;]\s*\n|\n{2,}")
_NOISE = re.compile(r"\{[^{}]*(\{[^{}]*\}[^{}]*)*\}|\$[^$]*\$|\\[A-Za-z]+|`[^`]*`|https?://\S+")
PRODUCT_TERMS = frozenset({"jana", "tutor", "online", "offline", "settings", "profile", "password", "laptop"})


@dataclass(frozen=True)
class Reading:
    words: int
    sentences: int
    sentence_words: float
    grade: float


def syllables(word: str) -> int:
    """A vowel-group count with the usual English corrections; at least one."""
    w = word.lower().strip("'-" + chr(0x2019))
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def measure(text: str, terms: frozenset[str] = frozenset()) -> Reading:
    clean = _NOISE.sub(" ", text)
    pieces = [p for p in _SENTENCE_END.split(clean) if _WORD.search(p)]
    words = [w for p in pieces for w in _WORD.findall(p)]
    if not words:
        return Reading(0, 0, 0.0, 0.0)
    count = sum(1 if w.lower() in terms else syllables(w) for w in words)
    per_sentence = len(words) / max(1, len(pieces))
    grade = 0.39 * per_sentence + 11.8 * count / len(words) - 15.59
    return Reading(len(words), len(pieces), round(per_sentence, 1), round(max(0.0, grade), 1))


def _texts(value: Any) -> list[str]:
    """The English text fields of a lesson record."""
    if isinstance(value, dict):
        if set(value) >= {"en"} and isinstance(value["en"], str):
            return [value["en"]]
        return [t for k, v in value.items() if k not in ("provenance", "review", "authoring") for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    return []


def pack_terms(pack: Path) -> frozenset[str]:
    """The pack's own subject vocabulary: words of its KC names, lesson titles and misconception names."""
    words: set[str] = set()
    for folder, keys in (("kcs", ("name", "title")), ("lessons", ("title",)), ("misconceptions", ("student_name",))):
        for path in sorted((pack / folder).glob("*.yaml")):
            loaded = yaml.safe_load(path.read_text())
            for record in loaded if isinstance(loaded, list) else [loaded]:
                for key in keys:
                    if isinstance(record, dict) and isinstance(record.get(key), str):
                        words.update(w.lower() for w in _WORD.findall(record[key]) if syllables(w) >= 3)
    return frozenset(words)


def lint_errors(curriculum: Path = CURRICULUM, catalogues: tuple[Path, ...] = CATALOGUES,
                settings: Any = None) -> list[str]:  # fmt: skip
    from agent_core.config import Settings

    settings = settings or Settings()
    errors = []
    for pack in sorted(p.parent for p in curriculum.glob("*/*/pack.yaml")):
        level = pack.name.upper()
        grade_cap = settings.readability_max_grade_a if level == "A" else settings.readability_max_grade_o
        terms = pack_terms(pack)
        for path in sorted((pack / "lessons").glob("*.yaml")):
            reading = measure("\n\n".join(_texts(yaml.safe_load(path.read_text()))), terms)
            errors += _problems(path.relative_to(REPO_ROOT).as_posix(), reading, grade_cap, settings)
    for catalogue in catalogues:
        if catalogue.is_file():
            strings = [v for v in json.loads(catalogue.read_text()).values() if isinstance(v, str)]
            reading = measure("\n\n".join(strings), PRODUCT_TERMS)
            errors += _problems(catalogue.relative_to(REPO_ROOT).as_posix(), reading,
                                settings.readability_max_grade_o, settings)  # fmt: skip
    return errors


def _problems(name: str, reading: Reading, grade_cap: float, settings: Any) -> list[str]:
    out = []
    if reading.sentence_words > settings.readability_max_sentence_words:
        out.append(f"{name}: {reading.sentence_words} words per sentence (at most "
                   f"{settings.readability_max_sentence_words:g}; LOC-22)")  # fmt: skip
    if reading.grade > grade_cap:
        out.append(f"{name}: readability grade {reading.grade} (at most {grade_cap:g}; LOC-22)")
    return out
