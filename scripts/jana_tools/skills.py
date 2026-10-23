"""Skill CI (SKL-01 to SKL-07, SKL-16 to SKL-18, SKL-22, SKL-24, SKL-25): schema, layout, lint rules L01 to L13 (L12
retired by D66) with references resolved against the registers and the packs, the injection scan, the always-on index
budget, the agent bundle, the pinned skill count and the KC → teaching skill coverage report.

`python -m jana_tools skills` checks every skill in the repository; `skills --bundle [--release]` builds the agent
bundle manifest (pedagogy and agent skills; teaching skills ship in content packs). A release bundle carries only
`reviewed` skills, and every gate is re-run when it is built; there is no human sign-off (SKL-18, D66)."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
COUNT_PIN = SKILLS / "counts.toml"
SPEC = REPO_ROOT / "docs" / "specification"
EXAMPLES = SPEC / "contracts" / "skills" / "examples"
CURRICULUM = REPO_ROOT / "content" / "curriculum"
COVERAGE_STAGE = "S2"  # the stage whose launched subject-levels SKL-25 covers (TABLE SKL-25a)

SECTIONS: dict[str, list[str]] = {
    "pedagogy": [
        "When to use",
        "What this skill does not do",
        "Objectives",
        "Method",
        "Branches by student state",
        "Confidence and escalation",
        "Worked exchange",
        "Verification checklist",
    ],
    "teaching": [
        "When to use",
        "What this skill does not do",
        "Objectives",
        "Prerequisite probe",
        "Teaching sequence",
        "Hint ladder",
        "Misconceptions",
        "Confidence and escalation",
        "Worked exchange",
        "Verification checklist",
    ],
    "agent": [
        "When to use",
        "What this skill does not do",
        "Inputs",
        "Procedure",
        "Output contract",
        "Pitfalls",
        "Verification checklist",
    ],
}
STEPS_SECTION = {"pedagogy": "Method", "teaching": "Teaching sequence", "agent": "Procedure"}
# Trigger words per kind for descriptions that are not tied to topics (SKL-04).
TRIGGERS = {
    "pedagogy": (
        "drill",
        "quiz",
        "test",
        "practise",
        "practice",
        "explain",
        "show",
        "help",
        "stuck",
        "solve",
        "step",
        "guide",
        "guided",
        "worked",
        "example",
        "hint",
        "revise",
        "recall",
        "check",
    ),
    "agent": (
        "diagnose",
        "classify",
        "mark",
        "plan",
        "check",
        "verify",
        "write",
        "summarise",
        "solve",
        "extract",
        "solution",
        "question",
        "answer",
        "working",
    ),
}
SUMMARY_NOT_FIRST = {"a", "an", "the", "this", "it", "for", "how", "when", "skill", "use", "used"}
FICTIONAL_NAMES = {"Ama", "Kofi", "Ayo", "Chidi", "Zara", "Tunde", "Nia", "Femi", "Lina", "Sam"}
NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
INJECTION = {
    "ignore_instructions": re.compile(r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(instructions|rules|prompt)", re.I),
    "reveal_prompt": re.compile(
        r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,30}\b(system|hidden)\s+(prompt|message)", re.I
    ),
    "role_reassignment": re.compile(r"\byou are now\b|\bact as (an? )?(admin|developer|system|different)", re.I),
    "always_load": re.compile(r"\balways (load|run|use|call) (this|the) skill\b", re.I),
    "url": re.compile(r"\bhttps?://|\bwww\.[a-z0-9-]+\.", re.I),
    "encoded_blob": re.compile(r"[A-Za-z0-9+/]{48,}={0,2}"),
    "invisible_unicode": re.compile("[​-‏‪-‮⁠-⁤﻿]"),
}
TOOL_DIRECTIVE = re.compile(r"\b(call|use|run|invoke)\s+(the\s+)?`?([a-z][a-z0-9_]{2,39})`?(\s+tool)?\b", re.I)
MISCONCEPTION = re.compile(r"^mc\.(mth|phy|chm|bio|acc)\.(o|a)\.[a-z0-9_]+$")


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.rule} {self.message}"


@dataclass
class Catalogue:
    """What references resolve against (L08)."""

    skills: set[str]
    tools: set[str]  # model-callable tool names
    visuals: set[str]
    misconceptions: set[str] | None = None  # None: no pack library in this build yet
    kcs: set[str] | None = None
    curriculum_refs: set[str] | None = None

    @classmethod
    def from_registers(cls, skill_names: set[str]) -> Catalogue:
        toolsets = json.loads((SPEC / "registers" / "toolsets.json").read_text())
        tools = {t["name"] for name, ts in toolsets["toolsets"].items() if name != "ui" for t in ts["tools"]}
        visuals = {k["kind"] for k in json.loads((SPEC / "registers" / "visual-catalogue.json").read_text())["kinds"]}
        return cls(skill_names, tools, visuals)

    def with_packs(self, curriculum: Path = CURRICULUM) -> Catalogue:
        """The same catalogue resolving `kcs`, `prerequisites`, `curriculum_refs` and misconception ids against the
        packs' sources: their KCs, curriculum map codes and misconception libraries (L06, L08; SKL-24, CUR-03)."""
        kcs: set[str] = set()
        codes: set[str] = set()
        misconceptions: set[str] = set()
        for pack in sorted(p.parent for p in curriculum.glob("*/*/map.yaml")):
            codes |= {str(n["code"]) for n in _yaml_records(pack / "map.yaml")}
            kcs |= {str(k["id"]) for path in sorted((pack / "kcs").glob("*.yaml")) for k in _yaml_records(path)}
            misconceptions |= {p.stem for p in (pack / "misconceptions").glob("mc.*.yaml")}
        return Catalogue(self.skills, self.tools, self.visuals, misconceptions, kcs, codes)


def _yaml_records(path: Path) -> list[dict[str, Any]]:
    import yaml

    loaded = yaml.safe_load(path.read_text()) if path.is_file() else None
    return loaded if isinstance(loaded, list) else [loaded] if isinstance(loaded, dict) else []


def _sections(body: str) -> list[tuple[str, int]]:
    return [(m.group(1).strip(), body[: m.start()].count("\n")) for m in re.finditer(r"^## (.+)$", body, re.M)]


def _section_text(body: str, title: str) -> tuple[str, int] | None:
    match = re.search(rf"^## {re.escape(title)}\s*$", body, re.M)
    if not match:
        return None
    rest = body[match.end() :]
    end = re.search(r"^## ", rest, re.M)
    return (rest[: end.start()] if end else rest), body[: match.end()].count("\n")


def lint(path: Path, catalogue: Catalogue, text: str | None = None) -> list[Finding]:
    """Every lint finding for one SKILL.md (L01 to L13, plus schema and layout)."""
    from agent_core.assets.skills import FRONTMATTER, NAME, SkillError, split_front_matter
    from agent_core.contracts import errors as contract_errors

    text = text if text is not None else path.read_text()
    rel = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    found: list[Finding] = []

    def add(rule: str, line: int, message: str) -> None:
        found.append(Finding(rule, rel, line, message))

    try:
        meta, body, start = split_front_matter(text)
    except (SkillError, ValueError) as error:
        return [Finding("schema", rel, 1, str(error))]
    for problem in contract_errors(FRONTMATTER, meta):
        add("schema", 1, problem)
    kind = meta.get("kind")
    name = str(meta.get("name", ""))
    if kind not in SECTIONS:
        return found
    # Layout (SKL-01, SKL-02): kind matches the top folder, name equals the folder, name pattern.
    parts = path.parent.parts
    if kind not in parts:
        add("layout", 1, f"kind {kind} does not match the folder")
    if path.parent.name != name:
        add("layout", 1, f"name {name} does not equal its folder {path.parent.name}")
    if not NAME.match(name) or ".." in name or "/" in name:
        add("layout", 1, f"name {name!r} breaks the name pattern")

    # L01 summary
    summary = str(meta.get("summary", ""))
    first = summary.split(" ", 1)[0].lower() if summary else ""
    if (
        len(summary) > 80
        or summary.endswith(".")
        or not first.isalpha()
        or first in SUMMARY_NOT_FIRST
        or first.endswith("ing")
    ):
        add("L01", 1, "summary must be at most 80 characters, start with a verb and have no full stop")
    # L02 description
    description = str(meta.get("description", ""))
    triggers = [t.lower() for t in meta.get("topics", [])] if kind == "teaching" else list(TRIGGERS[kind])
    head = description[:60].lower()
    if len(description) > 300 or "Not for:" not in description or not any(t in head for t in triggers):
        add("L02", 1, "description must be at most 300 characters, put a trigger in its first 60 and say 'Not for:'")
    # L03 sections present and ordered
    titles = [t for t, _ in _sections(body)]
    required = SECTIONS[kind]
    present = [t for t in titles if t in required]
    if present != required:
        missing = [t for t in required if t not in titles]
        add("L03", start, f"sections out of order or missing: {', '.join(missing) or 'order'}")
    # L04 numbered steps end with "Done when …"
    steps = _section_text(body, STEPS_SECTION[kind])
    if steps:
        for offset, line in enumerate(steps[0].splitlines()):
            if re.match(r"^\d+\.\s", line) and not re.search(r"Done when [^.]+\.?\s*$", line):
                add("L04", start + steps[1] + offset + 1, "a numbered step does not end with 'Done when …'")
    # L05 hint ladder
    if kind == "teaching":
        ladder = _section_text(body, "Hint ladder")
        rungs = re.findall(r"^\d+\.\s.*$", ladder[0], re.M) if ladder else []
        if len(rungs) != 5 or "not mastered" not in (rungs[-1] if rungs else ""):
            add(
                "L05",
                start + (ladder[1] if ladder else 0),
                "the hint ladder needs exactly 5 rungs; rung 5 says it counts as not mastered",
            )
    # L06 misconceptions
    if kind == "teaching":
        section = _section_text(body, "Misconceptions")
        seen: set[str] = set()
        for offset, line in enumerate((section[0] if section else "").splitlines()):
            if not line.startswith("- "):
                continue
            ids = re.findall(r"`([^`]+)`", line)
            ident = ids[0] if ids else ""
            bad = (
                not MISCONCEPTION.match(ident)
                or ident in seen
                or "→" not in line
                or not re.search(r"\?[\"”]?\s*$", line)
                or (catalogue.misconceptions is not None and ident not in catalogue.misconceptions)
            )
            if bad:
                add(
                    "L06",
                    start + (section[1] if section else 0) + offset + 1,
                    f"misconception {ident or '?'} needs a library id, a signature and a question",
                )
            seen.add(ident)
    # L07 worked exchange: tutor numbers are given, said by the student, or carry a check note
    if kind in ("pedagogy", "teaching"):
        exchange = _section_text(body, "Worked exchange")
        if not exchange:
            add("L07", start, "worked exchange missing")
        else:
            known: set[str] = set()
            lines = [ln for ln in exchange[0].splitlines() if ln.startswith(">")]
            for offset, line in enumerate(lines):
                speaker, _, said = line[1:].strip().partition(":")
                numbers = set(re.findall(r"\d+(?:\.\d+)?", said))
                words = {NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", said.lower()) if w in NUMBER_WORDS}
                poses_question = re.search(r"\b(you try|new question|next question)\b[^:]*:", said, re.I)
                if offset == 0 or speaker.strip().lower() != "tutor" or poses_question:
                    known |= numbers | words
                    continue
                untraced = numbers - known
                if untraced and "checked" not in said.lower():
                    add("L07", start + exchange[1] + offset + 1, f"tutor numbers {sorted(untraced)} have no check note")
                known |= numbers
    # L08 dangling references
    for key in ("related", "pedagogy", "conflicts_with"):
        for ref in meta.get(key, []):
            if ref not in catalogue.skills:
                add("L08", 1, f"{key} names unknown skill {ref}")
    for tool in meta.get("requires_tools", []):
        if tool not in catalogue.tools:
            add("L08", 1, f"requires_tools names {tool}, which is not a model-callable tool")
    for visual in meta.get("visuals", []):
        if visual not in catalogue.visuals:
            add("L08", 1, f"visuals names unknown kind {visual}")
    for key, known_set in (
        ("kcs", catalogue.kcs),
        ("prerequisites", catalogue.kcs),
        ("curriculum_refs", catalogue.curriculum_refs),
    ):
        if known_set is not None:
            for ref in meta.get(key, []):
                if ref not in known_set:
                    add("L08", 1, f"{key} names unknown id {ref}")
    for link in re.findall(r"\]\((references/[^)]+)\)", body):
        if not (path.parent / link).is_file():
            add("L08", 1, f"linked file {link} does not exist")
    # L09 length
    if body.count("\n") > 250:
        add("L09", start, "body is longer than 250 lines")
    for ref in sorted((path.parent / "references").glob("*.md")) if (path.parent / "references").is_dir() else []:
        if ref.read_text().count("\n") > 400:
            add("L09", 1, f"{ref.name} is longer than 400 lines")
    # L10 do-not-capture
    in_exchange = exchange_span(body)
    for offset, line in enumerate(body.splitlines()):
        number = start + offset
        if re.search(
            r"\b(19|20)\d\d-\d\d-\d\d\b|\b\d{1,2} (January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\b",
            line,
        ):
            add("L10", number, "dates of sessions or events are not captured in skills")
        if re.search(r"[\w.+-]+@[\w-]+\.\w+|\+?\d[\d -]{8,}\d", line):
            add("L10", number, "contact details are not captured in skills")
        if not (in_exchange[0] <= offset < in_exchange[1]):
            quotes = re.findall(r"[\"“]([^\"”]+)[\"”]", line)
            spoken = [q for q in quotes if len(q.split()) >= 5 and re.search(r"\b(I|my|me|I'm)\b", q)]
            if line.startswith(">") or spoken:
                add("L10", number, "quoted student dialogue outside the worked exchange")
        for person in re.findall(r"\b(?:student|learner|pupil) ([A-Z][a-z]+)\b", line):
            if person not in FICTIONAL_NAMES:
                add("L10", number, f"personal name {person} is not on the fictional-names list")
    # L11 appended corrections
    for offset, line in enumerate(body.splitlines()):
        if re.search(r"(?i:\bupdate:|\bactually\b)|\bEDIT\b", line):
            add("L11", start + offset, "fix the skill in place; no appended corrections")
    # L13 objectives match success criteria
    if kind in ("pedagogy", "teaching"):
        objectives = _section_text(body, "Objectives")
        items = [
            re.sub(r"^\d+\.\s*", "", ln).strip().rstrip(".")
            for ln in (objectives[0] if objectives else "").splitlines()
            if re.match(r"^\d+\.\s", ln)
        ]
        criteria = [str(c).strip().rstrip(".") for c in meta.get("success_criteria", [])]
        if items != criteria:
            add(
                "L13",
                start + (objectives[1] if objectives else 0),
                "objectives and success_criteria do not match one to one",
            )
    return found


def exchange_span(body: str) -> tuple[int, int]:
    lines = body.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Worked exchange"), len(lines))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def injection_scan(path: Path, requires_tools: set[str], all_tools: set[str], text: str | None = None) -> list[Finding]:
    """Attack-vocabulary hits in a skill body or reference file (SKL-22). Ordinary firm teaching prose is fine."""
    text = text if text is not None else path.read_text()
    rel = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for pattern_id, pattern in INJECTION.items():
            if pattern.search(line):
                hits.append(Finding(f"injection:{pattern_id}", rel, number, "attack pattern"))
        for match in TOOL_DIRECTIVE.finditer(line):
            tool = match.group(3).lower()
            if tool in all_tools and tool not in requires_tools:
                hits.append(
                    Finding("injection:tool_directive", rel, number, f"directs a call to {tool}, not in requires_tools")
                )
    return hits


@dataclass
class Bundle:
    manifest: list[dict[str, str]]
    indexes: dict[str, list[str]]


def build_bundle(root: Path = SKILLS, release: bool = False, pin: Path | None = COUNT_PIN,
                 results: Path | None = None) -> Bundle:  # fmt: skip
    """The agent bundle's skills: pedagogy and agent kinds. Fails on lint or injection findings, unreviewed skills in
    a release, a reviewed skill without a passing colocated eval run (EVL-07), an index over budget, or a count that
    differs from the pin."""
    from agent_core.assets.skills import SkillError, SkillSet, discover, parse

    from .skill_evals import RESULTS, review_errors

    paths = discover(root, ("pedagogy", "agent", "teaching"))
    names = {p.parent.name for p in paths} | {p.name for p in EXAMPLES.iterdir() if p.is_dir()}
    catalogue = Catalogue.from_registers(names).with_packs()
    problems: list[str] = []
    for path in paths:
        problems += [str(f) for f in lint(path, catalogue)]
    for path in discover(root, ("teaching",)):  # teaching skills ship in packs, and are scanned here too (SKL-22)
        try:
            meta = parse(path).meta
        except (SkillError, ValueError):
            continue  # the schema finding is already reported by lint
        tools = set(meta.get("requires_tools", []))
        files = [path, *sorted((path.parent / "references").glob("*.md"))]
        problems += [str(f) for file in files for f in injection_scan(file, tools, catalogue.tools)]
    skills = SkillSet.load(
        root,
        frozenset({"reviewed"}) if release else frozenset({"draft", "in_review", "reviewed"}),
        ("pedagogy", "agent"),
    )
    for skill in skills.skills.values():
        tools = set(skill.meta.get("requires_tools", []))
        for file in [skill.path, *sorted((skill.folder / "references").glob("*.md"))]:
            body = skill.body if file == skill.path else None
            problems += [str(f) for f in injection_scan(file, tools, catalogue.tools, body)]
        if release and skill.status != "reviewed":
            problems.append(f"{skill.name}: status {skill.status}; a release bundle carries only reviewed skills")
    if pin is not None:
        problems += count_pin_errors(root, pin)
    problems += review_errors(root, results or RESULTS)
    indexes = {}
    for role in ("coach", "diagnoser", "solver", "checker", "reflector"):
        try:
            indexes[role] = skills.index(role)
        except ValueError as error:
            problems.append(str(error))
    if problems:
        raise BundleError(problems)
    shipped = [m for m in skills.manifest() if not release or m["status"] == "reviewed"]
    return Bundle(shipped, indexes)


MAJOR_FIELDS = ("kcs", "answer_policy")  # with the objectives and the misconception ids (SKL-19)


def version_bump_errors(name: str, before: str, after: str) -> list[str]:
    """SKL-19 for one edited SKILL.md: any edit bumps the minor version; a change to the objectives, `kcs`,
    `answer_policy` or the misconception ids bumps the major version."""
    from agent_core.assets.skills import split_front_matter

    if before == after:
        return []
    old_meta, old_body, _ = split_front_matter(before)
    new_meta, new_body, _ = split_front_matter(after)

    def parts(version: Any) -> tuple[int, int]:
        major, _, minor = str(version).partition(".")
        return int(major), int(minor or 0)

    old_v, new_v = parts(old_meta.get("version", "0.0")), parts(new_meta.get("version", "0.0"))
    objectives = (_section_text(old_body, "Objectives") or ("", 0))[0] != (_section_text(new_body, "Objectives")
                                                                          or ("", 0))[0]  # fmt: skip
    ids = sorted(re.findall(r"`(mc\.[^`]+)`", old_body)) != sorted(re.findall(r"`(mc\.[^`]+)`", new_body))
    major = objectives or ids or any(old_meta.get(k) != new_meta.get(k) for k in MAJOR_FIELDS)
    if major and new_v[0] <= old_v[0]:
        return [f"{name}: objectives, kcs, answer_policy or misconception ids changed; bump the major version "
                f"(still {new_meta.get('version')})"]  # fmt: skip
    if new_v <= old_v:
        return [f"{name}: edited without a version bump (still {new_meta.get('version')}; SKL-19)"]
    return []


class BundleError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def counts(root: Path = SKILLS) -> dict[str, int]:
    from agent_core.assets.skills import discover

    return {kind: len(discover(root, (kind,))) for kind in ("pedagogy", "agent", "teaching")}


def count_pin_errors(root: Path = SKILLS, pin: Path = COUNT_PIN) -> list[str]:
    pinned = tomllib.loads(pin.read_text())["skills"] if pin.is_file() else {}
    actual = counts(root)
    return [
        f"skill count for {kind} is {actual[kind]}, pinned {pinned.get(kind)}; update {pin.name} deliberately"
        for kind in actual
        if actual[kind] != pinned.get(kind)
    ]


@dataclass(frozen=True)
class KcSkill:
    kc_id: str
    skill: str | None  # the one teaching skill whose `kcs` contain the KC; None when none or several do
    status: str | None  # that skill's lifecycle status


@dataclass
class SkillCoverage:
    """The KC → teaching skill coverage report of a stage (SKL-25): one row per active KC of each launched
    subject-level that has a pack."""

    stage: str
    rows: list[KcSkill] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def awaiting_review(self) -> list[str]:
        """Teaching skills that map KCs but are not `reviewed` yet, so they do not ship (SKL-18)."""
        return sorted({r.skill for r in self.rows if r.skill and r.status != "reviewed"})


def kc_skill_coverage(stage: str = COVERAGE_STAGE, root: Path = SKILLS, curriculum: Path = CURRICULUM) -> SkillCoverage:
    """Every taught KC of each launched subject-level maps to exactly one teaching skill, of that level, and the KC's
    `skill_ids` name that skill (SKL-25, CUR-04). A teaching skill naming a KC that is not active in its pack is an
    error too. Whether the skills are reviewed is reported, not judged: review is the lifecycle's (SKL-18)."""
    from agent_core.assets.skills import SkillError, discover, parse

    from .kc_coverage import launched

    found = SkillCoverage(stage)
    teaching = []
    for path in discover(root, ("teaching",)):
        try:
            teaching.append(parse(path))
        except (SkillError, ValueError):
            continue  # lint reports it
    for subject, level in launched(stage):
        pack = curriculum / subject / level
        if not (pack / "kcs").is_dir():
            continue
        kcs = [k for path in sorted((pack / "kcs").glob("*.yaml")) for k in _yaml_records(path)]
        active = {str(k["id"]): k for k in kcs if k.get("status") == "active"}
        prefix = f"kc.{subject}.{level}."
        skills = [s for s in teaching if s.name.startswith(f"{subject}-{level}-")]
        for skill in skills:
            if level.upper() not in skill.meta.get("levels", []):
                found.errors.append(f"{skill.name}: its levels do not include {level.upper()}")
            for kc_id in skill.meta.get("kcs", []):
                if kc_id.startswith(prefix) and kc_id not in active:
                    found.errors.append(f"{skill.name}: teaches {kc_id}, which is not an active KC of its pack")
        for kc_id, kc in active.items():
            teachers = sorted(s.name for s in skills if kc_id in s.meta.get("kcs", []))
            if len(teachers) != 1:
                found.errors.append(f"{kc_id}: taught by {len(teachers)} teaching skills ({', '.join(teachers)}); "
                                    f"SKL-25 needs exactly one")  # fmt: skip
            named = list(kc.get("skill_ids") or [])
            if len(teachers) == 1 and named != teachers:
                found.errors.append(f"{kc_id}: skill_ids {named} do not name its teaching skill {teachers[0]}")
            skill = next((s for s in skills if [s.name] == teachers), None)
            found.rows.append(KcSkill(kc_id, skill.name if skill else None, skill.status if skill else None))
    return found


def check(root: Path = SKILLS) -> list[str]:
    """Everything CI runs on skills/ (SKL-24), and the KC → teaching skill mapping (SKL-25)."""
    try:
        build_bundle(root, release=False)
    except BundleError as error:
        return error.problems
    return kc_skill_coverage(root=root).errors
