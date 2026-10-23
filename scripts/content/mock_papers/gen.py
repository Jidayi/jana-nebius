"""Generate the O level mock papers of the Chemistry, Accounting and Mathematics packs (ASM-15, ASM-22, CUR-31).

Each paper is assembled from the pack's own published items by a board-neutral blueprint: a paper kind, the item
types it takes, its length and time (the TABLE ASM-15a defaults, read from configuration), and topic weights taken
from the pack map's exam weights over the topics the paper covers. The items a paper names become the mock-reserved
pool (ASM-22), so the generator only takes an item while every KC it assesses keeps the S2 practice minimums of
CUR-31 among the items left (configuration keys, never numbers written here). Every paper is checked with the pack
builder's own mock-paper checks before it is written, as `verified`, one record per file in `mock-papers/`.

The output is deterministic: candidates are ordered by a hash of the paper's seed and the item id. A paper that has
left `verified` (banked or published) is never rewritten, since a published id is immutable (CUR-02): it is kept as
it is and its items stay reserved; change a published set by adding papers to the plan. Run from the repository root:

    uv run python scripts/content/mock_papers/gen.py              # write all three packs' papers
    uv run python scripts/content/mock_papers/gen.py --only chm   # one pack
    uv run python scripts/content/mock_papers/gen.py --check      # fail if the tree differs from the generator
"""

from __future__ import annotations

import argparse
import math
import sys
import zlib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.store.catalogue import diagnostic
from pack_builder import mocks
from pack_builder import source as tree

REPO = Path(__file__).resolve().parents[3]
CHOICE = ("mcq", "mcq_diagnostic")
VERSION = "0.1.0"
PROVENANCE = {"origin": "original", "licence": "LicenseRef-Own", "drafted_with_ai": True,
              "ai_model": "claude-opus-5-5", "sources": []}  # fmt: skip
AUTHORING = {"drafted_by": "rev_author_agent", "history": ["drafted", "verified"]}
OPEN = ("drafted", "verified")  # the review states in which the generator may still rewrite a paper


class PlanError(RuntimeError):
    """A paper the pack's reservable items cannot fill to its blueprint."""


@dataclass(frozen=True)
class Spec:
    """One paper of a subject's plan. `topics` limits the paper to those map topics (None: every topic that has
    items of the paper's types). Objective papers have `questions` one-mark questions; structured papers fill their
    time with their items' estimated working time."""

    kind: str
    title: str
    types: tuple[str, ...]
    minutes: str  # the configuration key holding the paper's time
    questions: str | None = None  # the configuration key holding an objective paper's question count
    topics: tuple[str, ...] | None = None


def p1(title: str) -> Spec:
    """An objective Paper 1 in the TABLE ASM-15a default format."""
    return Spec("paper_1_objective", title, CHOICE, "mock_o_paper1_minutes", "mock_o_paper1_questions")


def p2(title: str, types: tuple[str, ...]) -> Spec:
    """A structured Paper 2 in the TABLE ASM-15a default time."""
    return Spec("paper_2_structured", title, types, "mock_o_paper2_minutes")


def section(title: str, types: tuple[str, ...], topics: tuple[str, ...] | None = None) -> Spec:
    """A section mock for countdown weeks (TABLE ASM-15a)."""
    return Spec("section_mock", title, types, "mock_section_minutes", topics=topics)


STRUCTURED = ("numeric", "ordering")
SHORT_MARKS = 2  # layout only: a structured paper's questions of up to this many marks go in Section A
# Titles are our own; the topic groups of the accounting section mocks are our own board-neutral split of the map.
PLANS: dict[str, list[Spec]] = {
    "chm": [
        p1("Chemistry mock, objective paper, set 1"),
        p1("Chemistry mock, objective paper, set 2"),
        section("Chemistry section mock: calculations and sequences", STRUCTURED),
    ],
    "acc": [
        p1("Accounting mock, objective paper"),
        section(
            "Accounting section mock: recording, checking and control",
            ("numeric",),
            (
                "cur.acc.o.accounting_equation",
                "cur.acc.o.source_documents",
                "cur.acc.o.double_entry",
                "cur.acc.o.trial_balance",
                "cur.acc.o.bank_reconciliation",
                "cur.acc.o.control_accounts",
                "cur.acc.o.irrecoverable_debts",
                "cur.acc.o.costing",
            ),
        ),
        section(
            "Accounting section mock: year-end adjustments and final accounts",
            ("numeric",),
            (
                "cur.acc.o.depreciation",
                "cur.acc.o.inventory",
                "cur.acc.o.accruals_prepayments",
                "cur.acc.o.sole_trader_statements",
                "cur.acc.o.partnerships",
                "cur.acc.o.clubs",
                "cur.acc.o.incomplete_records",
                "cur.acc.o.ratios",
            ),
        ),
    ],
    "phy": [
        p1("Physics mock, objective paper, set 1"),
        p1("Physics mock, objective paper, set 2"),
        p2("Physics mock, structured paper, set 1", STRUCTURED),
        p2("Physics mock, structured paper, set 2", STRUCTURED),
    ],
    "mth": [
        p1("Mathematics mock, objective paper, set 1"),
        p1("Mathematics mock, objective paper, set 2"),
        p2("Mathematics mock, structured paper, set 1", STRUCTURED),
        p2("Mathematics mock, structured paper, set 2", STRUCTURED),
        p2("Mathematics mock, structured paper, set 3", STRUCTURED),
        section("Mathematics section mock: short structured questions", STRUCTURED),
    ],
}


def pack_dir(subject: str) -> Path:
    return REPO / "content" / "curriculum" / subject / "o"


def _marks(item: Mapping[str, Any]) -> int:
    return mocks.item_marks(item)


def _calculator(item: Mapping[str, Any]) -> bool:
    return bool((item.get("exam_style") or {}).get("calculator", True))


def _order(seed: int, item_id: str) -> int:
    return zlib.crc32(f"{seed}:{item_id}".encode())


@dataclass
class Pool:
    """The pack's items with what each KC can still give up to the mock pool and keep the S2 practice minimums."""

    items: list[dict[str, Any]]
    topic_of_kc: dict[str, str]
    slack: Counter[str]
    diagnostic_slack: Counter[str]
    used: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, tables: Mapping[str, list[dict[str, Any]]], settings: Settings) -> Pool:
        nodes = {n["id"]: n for n in tables["curriculum_nodes"]}

        def topic(node_id: str | None) -> str:
            while node_id is not None:
                if nodes[node_id]["kind"] == "topic":
                    return node_id
                node_id = nodes[node_id].get("parent_id")
            raise PlanError("a KC is not under a topic of the map")

        kcs = [k for k in tables["kcs"] if k["status"] == "active"]
        published = [i for i in tables["items"] if i["review"]["status"] == "published"]
        counts = Counter(k for i in published for k in i["kc_ids"])
        diagnostics = Counter(k for i in published if diagnostic(i) for k in i["kc_ids"])
        return cls(
            items=published,
            topic_of_kc={k["id"]: topic(k["node_id"]) for k in kcs},
            slack=Counter({k["id"]: counts[k["id"]] - settings.coverage_s2_items_per_kc for k in kcs}),
            diagnostic_slack=Counter(
                {k["id"]: diagnostics[k["id"]] - settings.coverage_s2_diagnostic_items_per_kc for k in kcs}),
        )  # fmt: skip

    def topic(self, item: Mapping[str, Any]) -> str | None:
        """The item's topic; items whose KCs span topics are left out of mocks (their marks would be split)."""
        topics = {self.topic_of_kc.get(k) for k in item["kc_ids"]}
        return topics.pop() if len(topics) == 1 else None

    def can_take(self, item: Mapping[str, Any]) -> bool:
        if item["id"] in self.used:
            return False
        return all(self.slack[k] > 0 and (not diagnostic(item) or self.diagnostic_slack[k] > 0)
                   for k in item["kc_ids"])  # fmt: skip

    def take(self, item: Mapping[str, Any]) -> None:
        self.used.add(item["id"])
        for k in item["kc_ids"]:
            self.slack[k] -= 1
            if diagnostic(item):
                self.diagnostic_slack[k] -= 1

    def spare(self, topic: str) -> int:
        """How many more items the topic's KCs can give up between them."""
        return sum(max(0, n) for k, n in self.slack.items() if self.topic_of_kc[k] == topic)

    def copy(self) -> Pool:
        slack, diagnostic_slack = Counter(self.slack), Counter(self.diagnostic_slack)
        return Pool(self.items, self.topic_of_kc, slack, diagnostic_slack, set(self.used))

    def candidates(self, spec: Spec) -> list[dict[str, Any]]:
        """The items a paper may use; an objective paper takes one-mark questions only."""
        return [i for i in self.items if i["type"] in spec.types and self.topic(i) is not None
                and (not _objective(spec) or _marks(i) == 1)
                and (spec.topics is None or self.topic(i) in spec.topics)]  # fmt: skip


def _weights(spec: Spec, pool: Pool, nodes: list[dict[str, Any]]) -> dict[str, float]:
    """The blueprint: the map's exam weights over the topics the paper covers, scaled to sum to one."""
    covered = {pool.topic(i) for i in pool.candidates(spec)}
    topics = [n for n in nodes if n["kind"] == "topic" and n.get("status", "active") == "active"
              and n["id"] in covered and float(n.get("exam_weight", 0)) > 0]  # fmt: skip
    total = sum(float(n["exam_weight"]) for n in topics)
    weights = {n["id"]: round(float(n["exam_weight"]) / total, 4) for n in topics}
    largest = max(weights, key=lambda t: (weights[t], t))
    weights[largest] = round(weights[largest] + 1 - sum(weights.values()), 4)
    return weights


def _rank(pool: Pool, item: Mapping[str, Any], seed: int, need: float | None) -> tuple[Any, ...]:
    """Most to spare in its KCs first; for a structured paper (`need` marks still wanted) the largest item that
    fits; plain before diagnostic; then the seeded order."""
    spare = min(pool.slack[k] for k in item["kc_ids"])
    fit = () if need is None else (0 if _marks(item) <= need + 0.5 else 1, -_marks(item))
    return (-spare, fit, diagnostic(item), _order(seed, item["id"]))


def _pick(pool: Pool, spec: Spec, topic: str, seed: int, want_marks: float, objective: bool) -> list[dict[str, Any]]:
    """Items of one topic up to `want_marks`, spread over the KCs with the most to spare; plain items before
    diagnostic ones, so the diagnostic walk keeps the most."""
    chosen: list[dict[str, Any]] = []
    got = 0
    here = [i for i in pool.candidates(spec) if pool.topic(i) == topic]
    while got < want_marks - (0 if objective else 0.5):
        pickable = [i for i in here if pool.can_take(i)]
        if not pickable:
            break
        need = want_marks - got
        item = min(pickable, key=lambda i: _rank(pool, i, seed, None if objective else need))
        pool.take(item)
        chosen.append(item)
        got += _marks(item)
    return chosen


def _sections(spec: Spec, chosen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One multiple-choice section, or short answers then longer questions; questions numbered through the paper."""
    if _objective(spec):
        groups = [("A", "Multiple choice: one answer each", chosen)]
    else:
        groups = [
            ("A", "Short answers: show your working", [i for i in chosen if _marks(i) <= SHORT_MARKS]),
            ("B", "Longer questions: show every step", [i for i in chosen if _marks(i) > SHORT_MARKS]),
        ]
    sections, number = [], 0
    for sid, title, group in groups:
        if not group:
            continue
        questions = []
        for item in group:
            number += 1
            questions.append({"question_id": str(number), "item_id": item["id"], "marks": _marks(item),
                              "kc_ids": list(item["kc_ids"])})  # fmt: skip
        sections.append({"section_id": sid, "title": title, "item_types": sorted({i["type"] for i in group}),
                         "marks": sum(q["marks"] for q in questions), "questions": questions})  # fmt: skip
    return sections


def _objective(spec: Spec) -> bool:
    return set(spec.types) <= set(CHOICE)


def _size(spec: Spec, pool: Pool, settings: Settings) -> float:
    """An objective paper's question count, or a structured paper's marks."""
    found = pool.candidates(spec)
    budget = int(getattr(settings, spec.minutes)) * 60 * settings.mock_working_time_share  # the rest: checking
    seconds = sum(int(i["estimated_seconds"]) for i in found)
    if spec.questions is not None:
        return float(getattr(settings, spec.questions))
    if _objective(spec):  # as many one-mark questions as the working time holds at the pool's own pace
        return float(math.floor(budget * len(found) / seconds))
    return budget * sum(_marks(i) for i in found) / seconds  # as many marks as the working time holds


def _floor_counts(spec: Spec, pool: Pool, nodes: list[dict[str, Any]], settings: Settings) -> dict[str, int]:
    """The fewest items per topic a paper may have and still match its blueprint within one item: for an objective
    paper whole questions, for a structured one its share less its largest question, in its topic's largest items."""
    size = _size(spec, pool, settings)
    weights = _weights(spec, pool, nodes)
    if _objective(spec):
        return {t: max(0, math.ceil(w * size - 1 - 1e-9)) for t, w in weights.items()}
    found = pool.candidates(spec)
    largest = max(_marks(i) for i in found)
    floors = {}
    for t, w in weights.items():
        biggest = max(_marks(i) for i in found if pool.topic(i) == t)
        floors[t] = max(0, math.ceil((w * size - largest) / biggest - 1e-9))
    return floors


def _counts(name: str, weights: Mapping[str, float], count: int, room: Mapping[str, int]) -> dict[str, int]:
    """Whole questions per topic summing to `count`, each within one of its blueprint share and within the `room`
    the topic has once later papers' minimums are set aside; nearest the blueprint first."""
    exact = {t: w * count for t, w in weights.items()}
    low = {t: max(0, math.ceil(v - 1 - 1e-9)) for t, v in exact.items()}
    high = {t: min(math.floor(v + 1 + 1e-9), room[t]) for t, v in exact.items()}
    short = sorted(t for t in exact if high[t] < low[t])
    if short:
        raise PlanError(f"{name}: too few reservable items on {', '.join(short)}")
    counts = {t: min(max(round(v), low[t]), high[t]) for t, v in exact.items()}
    while sum(counts.values()) != count:
        up = sum(counts.values()) < count
        movable = [t for t in counts if (counts[t] < high[t] if up else counts[t] > low[t])]
        if not movable:
            raise PlanError(f"{name}: the topics cannot hold {count} questions within the blueprint")
        t = min(movable, key=lambda t: ((counts[t] - exact[t]) if up else (exact[t] - counts[t]), t))
        counts[t] += 1 if up else -1
    return counts


def paper(spec: Spec, number: int, subject: str, pool: Pool, nodes: list[dict[str, Any]], settings: Settings,
          later: list[Spec]) -> dict[str, Any]:  # fmt: skip
    name = f"mck.{subject}.o.{number:04d}"
    seed = zlib.crc32(name.encode())
    weights = _weights(spec, pool, nodes)
    order = {n["id"]: n.get("order", 0) for n in nodes}
    objective = _objective(spec)
    total = _size(spec, pool, settings)
    if objective:  # leave each topic what the later papers need at least: of its choice items, and of its KCs
        held, held_choice = Counter[str](), Counter[str]()
        for other in later:
            floors = _floor_counts(other, pool, nodes, settings)
            held.update(floors)
            if _objective(other):
                held_choice.update(floors)
        room = {t: min(len(_pick(pool.copy(), spec, t, seed, math.inf, True)) - held_choice[t],
                       pool.spare(t) - held[t]) for t in weights}  # fmt: skip
        targets = {t: float(c) for t, c in _counts(name, weights, round(total), room).items()}
    else:
        targets = {t: w * total for t, w in weights.items()}
    chosen: list[dict[str, Any]] = []
    for topic in sorted(targets, key=lambda t: (-weights[t], t)):
        got = _pick(pool, spec, topic, seed, targets[topic], objective)
        if objective and len(got) < targets[topic]:
            raise PlanError(f"{name}: {topic} has {len(got)} of {targets[topic]} items left")
        chosen += got
    chosen.sort(key=lambda i: (order[pool.topic(i) or ""], float(i["difficulty"]["prior"]), i["id"]))
    sections = _sections(spec, chosen)
    return {
        "id": name, "version": VERSION, "subject": subject, "level": "o", "paper_kind": spec.kind,
        "title": spec.title, "duration_minutes": int(getattr(settings, spec.minutes)),
        "total_marks": sum(s["marks"] for s in sections), "calculator": any(_calculator(i) for i in chosen),
        "blueprint": {"topic_weights": weights, "seed": seed}, "sections": sections,
        "provenance": dict(PROVENANCE), "review": {"status": "verified", "reviewers": []},
        "authoring": {"drafted_by": AUTHORING["drafted_by"], "history": list(AUTHORING["history"])},
    }  # fmt: skip


def papers_for(subject: str, settings: Settings | None = None) -> list[dict[str, Any]]:
    """The subject's mock papers, generated afresh from its pack source and checked as the build checks them."""
    from pack_builder.build import load_source

    settings = settings or Settings()
    source = load_source(pack_dir(subject))
    tables = source.tables
    pool = Pool.of(tables, settings)
    by_id = {i["id"]: i for i in tables["items"]}
    fixed = {p["id"]: {**p, "authoring": source.authoring.get(p["id"], {})} for p in tables.get("mock_papers", [])
             if p["review"]["status"] not in OPEN}  # fmt: skip
    for kept in fixed.values():  # their items stay reserved
        for question in (q for s in kept["sections"] for q in s["questions"]):
            pool.take(by_id[question["item_id"]])
    plan = PLANS[subject]
    records = [fixed.get(f"mck.{subject}.o.{n:04d}")
               or paper(spec, n, subject, pool, tables["curriculum_nodes"], settings, plan[n:])
               for n, spec in enumerate(plan, 1)]  # fmt: skip
    records += [p for pid, p in sorted(fixed.items()) if pid not in {r["id"] for r in records}]
    bare = [{k: v for k, v in r.items() if k != "authoring"} for r in records]
    problems = mocks.paper_problems(bare, source.pack, tables["items"], tables["curriculum_nodes"], tables["kcs"],
                                    settings.mock_blueprint_weight_tolerance)  # fmt: skip
    if problems:
        raise PlanError("\n".join(problems))
    return records


def summary(subject: str, records: Iterable[dict[str, Any]], settings: Settings | None = None) -> dict[str, Any]:
    """What the papers reserve, and what each KC keeps for practice (ASM-22, CUR-31)."""
    from pack_builder.build import load_source

    settings = settings or Settings()
    records = list(records)
    tables = load_source(pack_dir(subject)).tables
    reserved = {q["item_id"] for r in records for s in r["sections"] for q in s["questions"]}
    items = [i for i in tables["items"] if i["review"]["status"] == "published"]
    free = [i for i in items if i["id"] not in reserved]
    counts = Counter(k for i in free for k in i["kc_ids"])
    diagnostics = Counter(k for i in free if diagnostic(i) for k in i["kc_ids"])
    kcs = [k["id"] for k in tables["kcs"] if k["status"] == "active"]
    return {
        "papers": [{"id": r["id"], "kind": r["paper_kind"], "minutes": r["duration_minutes"],
                    "marks": r["total_marks"], "questions": sum(len(s["questions"]) for s in r["sections"]),
                    "calculator": r["calculator"], "topics": len(r["blueprint"]["topic_weights"])}
                   for r in records],
        "reserved": len(reserved), "bank": len(items), "reserved_share": round(len(reserved) / len(items), 3),
        "reserved_share_target": settings.mock_reserved_bank_share,
        "kcs": len(kcs),
        "unreserved_items_per_kc": dict(sorted(Counter(counts[k] for k in kcs).items())),
        "unreserved_diagnostic_per_kc": dict(sorted(Counter(diagnostics[k] for k in kcs).items())),
        "kcs_below_minimum": [k for k in kcs if counts[k] < settings.coverage_s2_items_per_kc
                              or diagnostics[k] < settings.coverage_s2_diagnostic_items_per_kc],
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--only", default=",".join(PLANS), help="comma-separated subject codes")
    parser.add_argument("--check", action="store_true", help="fail if the source tree differs from the generator")
    args = parser.parse_args(argv)
    stale = []
    for subject in args.only.split(","):
        records = papers_for(subject)
        directory = pack_dir(subject) / tree.PER_RECORD["mock_papers"]
        if args.check:
            have = {p.name: p.read_text(encoding="utf-8") for p in directory.glob("*.yaml")}
            want = {f"{r['id']}.yaml": tree.canonical(r, "mock_papers") for r in records}
            stale += [f"{subject}: {n}" for n in sorted(set(have) | set(want)) if have.get(n) != want.get(n)]
        else:
            tree.write_table(pack_dir(subject), "mock_papers", records)
        print(json.dumps({"subject": subject, **summary(subject, records)}, indent=1))
    if stale:
        print("stale mock papers:\n  " + "\n  ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
