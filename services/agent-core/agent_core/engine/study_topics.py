"""Conservative local topic suggestions from verified installed pack titles; never mastery evidence."""

from __future__ import annotations

import re
from typing import Any


def matching_topics(content: Any, text: str) -> dict[str, Any]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    haystack, tokens = " " + " ".join(words) + " ", set(words)
    matches = []
    for node_id, node in sorted(content.nodes.items()):
        title = str(node.get("title", ""))
        terms = re.findall(r"[a-z0-9]+", title.lower())
        if not terms or node.get("status", "active") != "active":
            continue
        # Exact title phrases (including a meaningful single word) are an interpretable suggestion.
        # No semantic/model inference can invent a pack ID, and generic one-word titles are excluded.
        if " " + " ".join(terms) + " " not in haystack or (len(terms) == 1 and len(terms[0]) < 5):
            continue
        if not set(terms) <= tokens or node.get("kind") not in ("topic", "subtopic"):
            continue
        kcs = sorted(
            str(k["id"])
            for k in content.table("kcs")
            if k.get("node_id") == node_id and k.get("status", "active") == "active"
        )[:100]
        if not kcs:
            continue
        lessons = sorted(
            str(lesson["id"])
            for lesson in content.table("lessons")
            if set(lesson.get("kc_ids", [])) & set(kcs) and lesson.get("status", "active") == "active"
        )[:20]
        matches.append(
            {
                "node_id": node_id,
                "title": title,
                "subject": ".".join(node_id.split(".")[:3]),
                "kc_ids": kcs,
                "lesson_ids": lessons,
                "objectives": [
                    {"kc_id": k, "statement": str(content.kc_statement(k) or k)} for k in kcs
                ],
            }
        )
        if len(matches) == 10:
            break
    return {"items": matches}


# --- STU-21: topics from the material itself --------------------------------------------------------------------

_NUMBERING = re.compile(
    r"^\s*(?:#{1,6}\s+|(?:\d+(?:\.\d+)*|[IVXivx]+|[A-Za-z])[.)]\s+|(?:chapter|unit|section|topic)\s+\d+[:.]?\s*)",
    re.IGNORECASE,
)
_STOP = frozenset(
    "about above after again against also among another because been before being below between both could does "
    "doing during each either every from further have having here into itself just more most much must never only "
    "other others over same should since some such than that their them then there these they this those through "
    "under until upon very were what when where which while whose will with within without would your yours also "
    "used using uses called means example examples figure table page slide answer question questions".split()
)


def _heading(line: str) -> str | None:
    """A short heading-like line: a section title, never a sentence."""
    raw = line.strip()
    marked = bool(_NUMBERING.match(raw))
    text = _NUMBERING.sub("", raw).strip().rstrip(":").strip(" -\u2013\u2014*_#")
    words = text.split()
    if not 1 <= len(words) <= 9 or not 3 <= len(text) <= 80:
        return None
    if text[-1] in ".?!,;" or not text[0].isalpha():
        return None
    if not marked and not (raw.endswith(":") or text[0].isupper()):
        return None
    if sum(ch.isalpha() for ch in text) < len(text.replace(" ", "")) * 0.7:
        return None
    return text[0].upper() + text[1:]


def material_topics(chunks: list[dict[str, Any]], limit: int = 20) -> dict[str, Any]:
    """Topics a learner can pick for generation (STU-21), extracted deterministically from the material's own
    headings (a slide or a section title covers its chunks until the next heading); a source without headings falls
    back to its most repeated terms. Titles are the material's own words: no model call, no syllabus claim."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    headed = 0
    for chunk in chunks:
        lines = [line for line in chunk["text"].splitlines() if line.strip()]
        # A chunk opening with running text continues the section before it; every heading inside it names it.
        names = [] if not lines or _heading(lines[0]) else [current] if current else []
        for line in lines:
            title = _heading(line)
            # A one-line chunk of running text (a paragraph) is not a heading however it is capitalised.
            if title is None or (len(lines) == 1 and len(chunk["text"]) > 120):
                continue
            key = title.casefold()
            current = next((t for t in sections if t.casefold() == key), title)
            sections.setdefault(current, [])
            names.append(current)
            headed += 1
        for name in names:
            if chunk["chunk_id"] not in sections[name]:
                sections[name].append(chunk["chunk_id"])
    if headed >= 2:
        items = [{"title": t[:120], "chunk_ids": ids} for t, ids in sections.items() if ids]
        return {"items": items[:limit]}
    counts: dict[str, int] = {}
    where: dict[str, list[str]] = {}
    shown: dict[str, str] = {}
    for chunk in chunks:
        for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", chunk["text"]):
            key = word.casefold()
            if key in _STOP:
                continue
            counts[key] = counts.get(key, 0) + 1
            shown.setdefault(key, word if word[0].isupper() else word.capitalize())
            ids = where.setdefault(key, [])
            if chunk["chunk_id"] not in ids:
                ids.append(chunk["chunk_id"])
    ranked = sorted((k for k, n in counts.items() if n >= 2), key=lambda k: (-counts[k], k))[: min(limit, 8)]
    order = {k: i for i, k in enumerate(counts)}
    return {"items": [{"title": shown[k], "chunk_ids": where[k]} for k in sorted(ranked, key=order.__getitem__)]}
