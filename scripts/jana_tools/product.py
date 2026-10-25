"""Product governance as code: problem trace (PRD-01), principle trace and review template (PRD-02),
scope boundary (PRD-10), non-goals (PRD-20) and the minors-first feature review (PRV-01).

The specification is read at run time from docs/; only IDs, numbers and short labels appear here."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from . import REPO_ROOT
from .spec import DOCS, ID, requirements, table_rows

GOVERNANCE = REPO_ROOT / "scripts" / "governance"
VISION = "product/vision-and-scope.md"
CAPABILITY_TABLES = tuple(f"TABLE PRD-{n}a" for n in range(12, 17))


def _vision(docs: Path) -> str:
    return (docs / VISION).read_text()


def _list_items(text: str, label: str) -> list[str]:
    """Numbered items of the list that follows the line starting with `label`, joined per item."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(label))
    items: list[str] = []
    for line in lines[start + 1 :]:
        if re.match(r"^\d+\. ", line):
            items.append(line)
        elif items and line.startswith("   ") and line.strip():
            items[-1] += " " + line.strip()
        elif items and not line.strip():
            continue
        elif items:
            break
    return items


def decided_decisions(docs: Path = DOCS) -> set[str]:
    data = json.loads((docs / "specification" / "registers" / "decisions.json").read_text())
    items = data if isinstance(data, list) else data.get("decisions", [])
    return {d["id"] for d in items if d.get("status") == "decided"}


# --- PRD-01 ---------------------------------------------------------------------------------


def problems(docs: Path = DOCS) -> set[str]:
    return {row[0] for row in table_rows(_vision(docs), "TABLE PRD-01a")}


def capabilities(docs: Path = DOCS) -> list[str]:
    text = _vision(docs)
    return [row[0] for table in CAPABILITY_TABLES for row in table_rows(text, table)]


def scope_trace_errors(docs: Path = DOCS, mapping_path: Path = GOVERNANCE / "scope-trace.toml") -> list[str]:
    mapping: dict[str, list[str]] = tomllib.loads(mapping_path.read_text())["capabilities"]
    known = problems(docs)
    caps = capabilities(docs)
    errors = []
    for cap in caps:
        traced = [p for p in mapping.get(cap, []) if p in known]
        if not traced:
            errors.append(f"capability {cap!r} traces to no problem of PRD-01")
    errors += [f"scope-trace.toml lists {c!r}, which is not a capability row" for c in mapping if c not in caps]
    return errors


# --- PRD-02 ---------------------------------------------------------------------------------


def principles(docs: Path = DOCS) -> list[tuple[str, list[str]]]:
    """(principle name, requirement IDs it cites) in precedence order."""
    out = []
    for item in _list_items(_vision(docs), "LIST PRD-02a"):
        name = re.search(r"\*\*(.+?)\*\*", item)
        out.append((name[1].rstrip(".") if name else item, ID.findall(item)))
    return out


def principle_trace(docs: Path = DOCS) -> list[tuple[str, list[str]]]:
    """For each principle, the active `must` requirements in other specification files that enforce it."""
    reqs = requirements(docs)
    vision = (docs / VISION).resolve()
    trace = []
    for name, ids in principles(docs):
        enforcing = [
            rid
            for rid in ids
            if rid in reqs
            and not reqs[rid].retired
            and reqs[rid].priority == "must"
            and reqs[rid].file.resolve() != vision
        ]
        trace.append((name, enforcing))
    return trace


def principle_trace_errors(docs: Path = DOCS) -> list[str]:
    trace = principle_trace(docs)
    errors = [f"principle {i} ({name}) has no enforcing must requirement" for i, (name, ids) in enumerate(trace, 1)
              if not ids]  # fmt: skip
    return errors or ([] if trace else ["LIST PRD-02a has no principles"])


def review_template_errors(docs: Path = DOCS) -> list[str]:
    templates = sorted((docs / "review").glob("*template*.md"))
    if not templates:
        return ["no design review template in docs/review/"]
    names = [name for name, _ in principles(docs)]
    errors = []
    for template in templates:
        text = template.read_text()
        positions = [text.find(name) for name in names]
        if -1 in positions:
            missing = [n for n, p in zip(names, positions, strict=True) if p == -1]
            errors.append(f"{template.name}: missing principles {missing}")
        elif positions != sorted(positions):
            errors.append(f"{template.name}: principles are not in precedence order")
        if "Declared trade-off:" not in text:
            errors.append(f"{template.name}: no 'Declared trade-off:' field")
        if "Non-goals touched:" not in text:
            errors.append(f"{template.name}: no 'Non-goals touched:' field")
    return errors


# --- PRD-10 ---------------------------------------------------------------------------------


# Out-of-scope phrases that the plan may word differently.
SYNONYMS = {"other subjects": ("new subjects", "additional subjects")}


def out_of_scope_terms(docs: Path = DOCS) -> list[tuple[str, frozenset[str]]]:
    """(phrase, decision IDs its scope row names) for each "out until decided" phrase of PRD-10."""
    terms = []
    for row in table_rows(_vision(docs), "TABLE PRD-10a"):
        decisions = frozenset(re.findall(r"\bD\d+\b", row[2]))
        cell = re.sub(r"\([^)]*\)", "", row[2])
        for part in re.split(r",|;| and (?=other )", cell):
            part = re.sub(r"\s+", " ", part).strip(" .")
            if len(part) >= 3:
                terms += [(phrase, decisions) for phrase in (part, *SYNONYMS.get(part, ()))]
    return terms


def plan_epics(plan_text: str) -> list[str]:
    """Milestone and work-package titles from section 10 of the implementation plan."""
    section = plan_text.split("## 10. Milestones in detail", 1)[-1]
    epics = re.findall(r"^## (M\d+ — .+)$", section, re.MULTILINE)
    epics += re.findall(r"^\| (M\d+\.[a-z] — [^|]+?) \|", section, re.MULTILINE)
    return epics


def _milestone_sections(plan_text: str) -> dict[str, str]:
    section = plan_text.split("## 10. Milestones in detail", 1)[-1]
    parts = re.split(r"^(?=## M\d+ — )", section, flags=re.MULTILINE)
    return {m[1]: part for part in parts if (m := re.match(r"## (M\d+) — ", part))}


def _settle_before_start(section: str) -> set[str]:
    """The decisions a milestone lists under "Decisions to settle before start" (it cannot start until they are)."""
    line = re.search(r"Decisions to settle before start:(.*)", section)
    if line is None:
        return set()
    before = line[1].split("before exit", 1)[0]
    return set(re.findall(r"\bD\d+\b", before))


def epic_scope_errors(docs: Path = DOCS, plan_text: str | None = None) -> list[str]:
    """An epic matching an out-of-scope phrase must cite (in its title or milestone section) the decision that
    governs it (one its scope row names when the row names any, otherwise any decision in its title), and that
    decision is decided or listed by the epic's milestone to settle before it starts (PRD-10)."""
    plan_text = plan_text if plan_text is not None else (docs / "implementation" / "plan.md").read_text()
    decided = decided_decisions(docs)
    sections = _milestone_sections(plan_text)
    errors = []
    for epic in plan_epics(plan_text):
        milestone = re.match(r"(M\d+)", epic)
        section = sections.get(milestone[1], "") if milestone else ""
        context = epic + section
        cited = set(re.findall(r"\bD\d+\b", context))
        gate = decided | _settle_before_start(section)
        for phrase, row_decisions in out_of_scope_terms(docs):
            if not re.search(rf"\b{re.escape(phrase)}\b", epic, re.IGNORECASE):
                continue
            allowed = (cited & row_decisions) if row_decisions else set(re.findall(r"\bD\d+\b", epic))
            if not allowed & gate:
                need = ", ".join(sorted(row_decisions)) or "a decision"
                errors.append(f"epic {epic!r} is outside the scope boundary ({phrase}) until {need} is decided or "
                              "listed by its milestone to settle before start")  # fmt: skip
    return errors


# --- PRV-01 and PRD-20 feature review (pull requests) ---------------------------------------

_FIELD = re.compile(r"^(PRV-01a items affected|Non-goals touched|Declared trade-off):[ \t]*(.*)$", re.MULTILINE)


def _fields(body: str) -> dict[str, str]:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    return {m[1]: m[2].strip() for m in _FIELD.finditer(body)}


def feature_review_paths(path: Path = GOVERNANCE / "review-paths.toml") -> list[str]:
    return [p for group in tomllib.loads(path.read_text())["prv01"].values() for p in group]


def feature_review_errors(body: str, changed: list[str], decided: set[str], review_paths: list[str]) -> list[str]:
    fields = _fields(body)
    errors = []
    if "PRV-01a items affected" not in fields or "Non-goals touched" not in fields:
        return ["the pull request description is missing the feature review checklist (PRV-01, PRD-20)"]
    touched = [p for p in changed if any(p.startswith(prefix) for prefix in review_paths)]
    if touched:
        items = {int(n) for n in re.findall(r"\b([1-9])\b", fields["PRV-01a items affected"])}
        if not items:
            errors.append(f"changes to {touched[0]} need a PRV-01a entry naming the principles affected (1-9)")
    non_goals = fields["Non-goals touched"]
    if non_goals.lower() not in ("none", "none."):
        numbers = re.findall(r"\b(10|[1-9])\b", re.sub(r"\bD\d+\b", "", non_goals))
        cited = set(re.findall(r"\bD\d+\b", non_goals))
        if not numbers:
            errors.append("'Non-goals touched' must be 'none' or list non-goal numbers with a decided decision ID")
        elif not cited & decided:
            errors.append(f"non-goals {', '.join(numbers)} touched without a decided decision ID")
    return errors


_FEATURE = re.compile(r"`([a-z_]+)`")
_ONLINE_MARK = "(online, optional)"


def offline_behaviour_errors(docs: Path = DOCS, policy_path: Path | None = None) -> list[str]:
    """PRD-03: every way the product uses the network states its offline behaviour. The specification names those
    ways in TABLE ARC-07a (each online feature), TABLE PRD-03a (its mirror), TABLE DAT-18a (each data class that
    leaves the device) and the journeys' optional online steps and branches; the network policy the core enforces
    (agent_core/net/policy.json) holds the same features. A row or step without its offline behaviour fails."""
    if docs == DOCS:
        inventory = json.loads((REPO_ROOT / "contracts/policies/online-features.json").read_text())
        policy = json.loads((policy_path or REPO_ROOT / "services/agent-core/agent_core/net/policy.json").read_text())
        errors = []
        for feature, row in policy["features"].items():
            if feature not in inventory:
                errors.append(f"PRD-03: the network policy has {feature}, which TABLE ARC-07a does not")
            elif not row.get("queued"):
                errors.append(f"PRD-03: the network policy gives {feature} no offline queueing rule")
        missing = sorted(set(inventory) - set(policy["features"]))
        if missing:
            errors.append(f"PRD-03: the network policy lacks online features {missing}")
        for feature, row in inventory.items():
            if not row.get("queued"):
                errors.append(f"PRD-03: public feature {feature} has no offline queueing rule")
        return errors
    errors: list[str] = []
    architecture = (docs / "specification" / "architecture.md").read_text()
    arc = {}
    for row in table_rows(architecture, "TABLE ARC-07a"):
        found = _FEATURE.search(row[0])
        feature = found[1] if found else row[0]
        if len(row) < 5 or not row[3].strip() or not row[4].strip():
            errors.append(f"PRD-03: TABLE ARC-07a {feature} states no offline equivalent or queueing")
        if found:  # the web client row is a client, not a feature of the installed app's policy (D21)
            arc[feature] = row
    prd = {}
    for row in table_rows(_vision(docs), "TABLE PRD-03a"):
        found = _FEATURE.search(row[0])
        if found is None:
            continue  # the web client row: not an installed client's feature (D21)
        prd[found[1]] = row
        if len(row) < 3 or not row[2].strip():
            errors.append(f"PRD-03: TABLE PRD-03a {found[1]} states no offline behaviour")
    if set(prd) != set(arc):
        errors.append(f"PRD-03: TABLE PRD-03a does not mirror TABLE ARC-07a ({sorted(set(prd) ^ set(arc))})")
    data_model = (docs / "specification" / "data-model.md").read_text()
    for row in table_rows(data_model, "TABLE DAT-18a"):
        if len(row) >= 5 and not row[1].lower().startswith(("no", "never")) and not row[4].strip():
            errors.append(f"PRD-03: TABLE DAT-18a {row[0]} leaves the device with no stated offline behaviour")
    # A journey step is one table row; a failure branch is one bullet with its indented continuation lines.
    blocks: list[str] = []
    for line in (docs / "product" / "personas-and-journeys.md").read_text().splitlines():
        if line.startswith("  ") and blocks and blocks[-1].startswith("- "):
            blocks[-1] += " " + line.strip()
        else:
            blocks.append(line)
    for block in blocks:
        if _ONLINE_MARK in block and "offline" not in block.lower():
            errors.append(f"PRD-03: an optional online journey step states no offline path: {block.strip()[:60]}")
    policy = json.loads((policy_path or REPO_ROOT / "services/agent-core/agent_core/net/policy.json").read_text())
    for feature, row in policy["features"].items():
        if feature not in arc:
            errors.append(f"PRD-03: the network policy has {feature}, which TABLE ARC-07a does not")
        elif not row.get("queued"):
            errors.append(f"PRD-03: the network policy gives {feature} no offline queueing rule")
    missing = sorted(set(arc) - set(policy["features"]))
    if missing:
        errors.append(f"PRD-03: the network policy lacks online features {missing}")
    return errors
