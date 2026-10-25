"""Run a drill checklist: print the steps, collect what the person observed, and write the probe record and the
JANA_M24_EVIDENCE index entry (format `ops/field-evidence`, records `ops/probe-record`).

Three answer sources: a person at the keyboard (the normal case), an answers file (a record prepared from a tool's
output, still reviewed by a person), and `--dry-run`, which rehearses the checklist with marked example answers and
writes a record every gate refuses: its candidate and specification are all zeros and every free-text value, the
device and the reviewer carry `DRY-RUN`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_core.config import Settings
from agent_core.contracts import validate

from .. import REPO_ROOT
from ..release.field_evidence import SOURCES
from .drills import DEVICE, Answers, Ask, Drill, Repeat
from .placeholders import DRY_RUN, FILL_IN

ZERO = "0" * 40
REVIEWER = Ask("reviewer", "Reviewer: who checked this record against the raw proofs (name and role)", "text")
SHA = re.compile(r"[a-f0-9]{64}")


def evidence_home() -> Path:
    return Path(os.environ.get("JANA_EVIDENCE_HOME", Path.home() / "jana-evidence")).expanduser()


def current_candidate() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def current_spec() -> str:
    return (REPO_ROOT / "spec.lock").read_text().strip()


def outside_repository(folder: Path) -> None:
    """Real evidence names people and holds raw proofs: it lives in a private folder, never in the monorepo."""
    if folder.expanduser().resolve().is_relative_to(REPO_ROOT.resolve()):
        raise ValueError(f"evidence folder {folder} is inside the repository; use a private folder outside it")


class Invalid(ValueError):
    pass


@dataclass
class Session:
    folder: Path  # the evidence root holding the index
    drill_dir: Path
    dry_run: bool
    now: Callable[[], datetime]
    base: datetime  # dry-run time origin for example offsets
    proofs: list[tuple[str, str]] = field(default_factory=list)  # (relative path, sha256), in order

    def add_proof(self, source: Path) -> str:
        source = source.expanduser()
        if not source.is_file():
            raise Invalid(f"no such file: {source}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if any(d == digest for _, d in self.proofs):
            return digest
        self.drill_dir.mkdir(parents=True, exist_ok=True)
        target = self.drill_dir / source.name
        n = 1
        while target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            target = self.drill_dir / f"{source.stem}-{n}{source.suffix}"
            n += 1
        if not target.exists():
            shutil.copyfile(source, target)
        self.proofs.append((target.relative_to(self.folder).as_posix(), digest))
        return digest


def _items(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    if text.lower() in ("", "none", "-"):
        return []
    return [part.strip() for part in re.split(r"[,\n]", text) if part.strip()]


def _numbers(raw: Any) -> list[float]:
    if isinstance(raw, list):
        values = raw
    else:
        text = str(raw).strip()
        if text.startswith("@"):
            text = Path(text[1:]).expanduser().read_text()
        values = [v for v in re.split(r"[,\s]+", text) if v]
    result = [float(v) for v in values]
    if any(not math.isfinite(v) or v < 0 for v in result):
        raise Invalid("numbers must be finite and not negative")
    return result


def parse(ask: Ask, raw: Any, session: Session, default: Any = None) -> Any:
    """One answer, checked for its kind. Raises Invalid with a message the person can act on."""
    text = raw.strip() if isinstance(raw, str) else raw
    if ask.later and isinstance(text, str) and text.lower() == "later":
        return f"{FILL_IN}: {ask.question}"
    if text == "" and default is not None:
        return default
    try:
        if ask.kind in ("text", "note"):
            if not isinstance(text, str) or (ask.kind == "text" and not text):
                raise Invalid("an answer is required")
            return text
        if ask.kind == "int":
            value = int(text)
            if value < 0 or isinstance(text, bool):
                raise Invalid("a whole number, 0 or more")
            return value
        if ask.kind == "number":
            number = float(text)
            if not math.isfinite(number) or number < 0 or isinstance(text, bool):
                raise Invalid("a number, 0 or more")
            return number
        if ask.kind == "yes":
            if isinstance(text, bool):
                return text
            if str(text).lower() in ("y", "yes", "true"):
                return True
            if str(text).lower() in ("n", "no", "false"):
                return False
            raise Invalid("answer y or n")
        if ask.kind == "time":
            if text in ("", "now"):
                return session.now().astimezone().isoformat(timespec="seconds")
            moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
            if moment.utcoffset() is None:
                raise Invalid("include the time zone, e.g. 2026-11-03T14:05:00+01:00")
            if moment > session.now() + timedelta(minutes=1) and ask.key not in ("due",):
                raise Invalid("that time is in the future; record times only after they happen")
            return moment.isoformat(timespec="seconds")
        if ask.kind == "date":
            return date.fromisoformat(str(text)).isoformat()
        if ask.kind == "dates":
            return [date.fromisoformat(d).isoformat() for d in _items(text)]
        if ask.kind == "list":
            return _items(text)
        if ask.kind == "numbers":
            return _numbers(text)
        if ask.kind == "steps":
            chosen = list(ask.choices) if str(text).strip().lower() == "all" else _items(text)
            if not set(chosen) <= set(ask.choices):
                raise Invalid("choose from: " + ", ".join(ask.choices))
            return sorted(set(chosen))
        if ask.kind == "choice":
            if text not in ask.choices:
                raise Invalid("choose one of: " + ", ".join(ask.choices))
            return text
        if ask.kind == "zone":
            ZoneInfo(str(text))
            return str(text)
        if ask.kind == "sha":
            if not isinstance(text, str) or not SHA.fullmatch(text.lower()):
                raise Invalid("64 hexadecimal characters")
            return text.lower()
        if ask.kind == "proof":
            return session.add_proof(Path(str(text)))
    except Invalid:
        raise
    except (ValueError, TypeError, OSError, ZoneInfoNotFoundError) as error:
        raise Invalid(str(error) or "not understood") from error
    raise Invalid(f"unknown answer kind {ask.kind}")


def rehearsal(ask: Ask, session: Session, label: str) -> Any:
    """The marked example answer a dry run uses in place of an observation."""
    if ask.kind == "time":
        return (session.base + timedelta(minutes=float(ask.example or 0))).isoformat(timespec="seconds")
    if ask.kind in ("text", "note"):
        return f"{DRY_RUN} {ask.example or ask.key}"
    if ask.kind == "list":
        return [f"{DRY_RUN} {item}" for item in _items(ask.example or "")]
    if ask.kind == "sha":
        return hashlib.sha256(f"{DRY_RUN} {label} {ask.key}".encode()).hexdigest()
    if ask.kind == "proof":
        session.drill_dir.mkdir(parents=True, exist_ok=True)
        stub = session.drill_dir / f"{re.sub(r'[^a-z0-9]+', '-', (label + ' ' + ask.key).lower()).strip('-')}.txt"
        stub.write_text(f"{DRY_RUN}: rehearsal file for {label} / {ask.key}; not evidence of any event\n")
        return session.add_proof(stub)
    if ask.kind == "date" and ask.later:
        return f"{FILL_IN}: {ask.question}"
    return parse(ask, ask.example, session)


class Source:
    """Where answers come from. Interactive asks a person; Scripted reads a prepared answers file."""

    dry_run = False

    def raw(self, ask: Ask, label: str, path: tuple[Any, ...], default: Any) -> Any:
        raise NotImplementedError

    def more(self, repeat: Repeat, path: tuple[Any, ...], count: int) -> bool:
        raise NotImplementedError

    def say(self, text: str) -> None:
        print(text)


class Interactive(Source):
    def __init__(self, read: Callable[[str], str] = input, write: Callable[[str], None] = print) -> None:
        self.read, self.write = read, write

    def say(self, text: str) -> None:
        self.write(text)

    def raw(self, ask: Ask, label: str, path: tuple[Any, ...], default: Any) -> Any:
        hint = f" [Enter keeps {default}]" if default is not None else ""
        if ask.later:
            hint += " ('later' allowed)"
        return self.read(f"  {ask.question}{hint}: ")

    def more(self, repeat: Repeat, path: tuple[Any, ...], count: int) -> bool:
        return self.read(f"  Add {'another ' if count else 'a '}{repeat.title.lower()}? [y/N]: ").strip().lower() in (
            "y",
            "yes",
        )


class Scripted(Source):
    def __init__(self, answers: dict[str, Any], quiet: bool = True) -> None:
        self.answers, self.quiet = answers, quiet

    def say(self, text: str) -> None:
        if not self.quiet:
            print(text)

    def _lookup(self, path: tuple[Any, ...]) -> Any:
        value: Any = self.answers
        for step in path:
            value = value[step]
        return value

    def raw(self, ask: Ask, label: str, path: tuple[Any, ...], default: Any) -> Any:
        try:
            return self._lookup(path)
        except (KeyError, IndexError, TypeError) as error:
            if default is not None:
                return ""
            raise Invalid(f"answers file has no value for {'.'.join(map(str, path))}") from error

    def more(self, repeat: Repeat, path: tuple[Any, ...], count: int) -> bool:
        try:
            return count < len(self._lookup(path))
        except (KeyError, TypeError):
            return False


class Rehearsal(Source):
    dry_run = True

    def raw(self, ask: Ask, label: str, path: tuple[Any, ...], default: Any) -> Any:
        return None

    def more(self, repeat: Repeat, path: tuple[Any, ...], count: int) -> bool:
        return count < 1


def answer(ask: Ask, source: Source, session: Session, label: str, path: tuple[Any, ...], default: Any = None) -> Any:
    if source.dry_run:
        value = rehearsal(ask, session, label)
        shown = f"rehearsal file {session.proofs[-1][0]}" if ask.kind == "proof" else value
        source.say(f"  {ask.question}: {shown}  (dry run)")
        return value
    while True:
        try:
            return parse(ask, source.raw(ask, label, path, default), session, default)
        except Invalid as error:
            if not isinstance(source, Interactive):
                raise Invalid(f"{'.'.join(map(str, path))}: {error}") from error
            source.say(f"    -> {error}")


def collect(drill: Drill, source: Source, session: Session, defaults: dict[str, Any], cfg: Settings) -> Answers:
    answers: Answers = {}
    for item in drill.asks:
        if isinstance(item, Ask):
            default = defaults.get(item.key) if drill.append else None
            answers[item.key] = answer(item, source, session, drill.id, (item.key,), default)
            continue
        entries: list[dict[str, Any]] = []
        presets = item.presets(answers, cfg) if item.presets else None
        index = 0
        while (index < len(presets)) if presets is not None else source.more(item, (item.key,), index):
            preset = presets[index] if presets is not None else {}
            title = item.title.format(**preset)
            source.say(f"\n {title}")
            entry = dict(preset)
            for ask in item.asks:
                entry[ask.key] = answer(ask, source, session, title, (item.key, index, ask.key))
            entries.append(entry)
            index += 1
        answers[item.key] = entries
    return answers


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body)
    temporary.replace(path)
    return hashlib.sha256(body.encode()).hexdigest()


def index_path(folder: Path) -> Path:
    return folder / "evidence.json"


def run(
    drill: Drill,
    folder: Path,
    source: Source,
    *,
    candidate: str,
    spec_revision: str,
    cfg: Settings | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Run one checklist and write its records. Returns the paths written and the gate's verdict on them."""
    cfg = cfg or Settings()
    if source.dry_run:
        candidate = spec_revision = ZERO
    else:
        outside_repository(folder)
    folder = folder.expanduser().resolve()
    index_file = index_path(folder)
    index: dict[str, Any] = (
        json.loads(index_file.read_text())
        if index_file.is_file()
        else {
            "format": "jana.ops.evidence.1",
            "candidate_commit": candidate,
            "spec_revision": spec_revision,
            "synthetic_data_only": True,
            "records": {},
        }
    )
    if index["candidate_commit"] != candidate or index["spec_revision"] != spec_revision:
        raise ValueError(
            f"{index_file} holds evidence for candidate {index['candidate_commit']} and specification "
            f"{index['spec_revision']}; use a separate folder for candidate {candidate}"
        )
    started = now()
    session = Session(folder, folder / drill.id, source.dry_run, now, started.replace(microsecond=0))
    previous: dict[str, Any] = {}
    first_test = drill.tests[0]
    if drill.append and first_test in index["records"]:
        receipt = index["records"][first_test]
        prior = json.loads((folder / receipt["proofs"][0]["path"]).read_text())
        previous = prior["data"]
        started = min(started, datetime.fromisoformat(prior["started_at"]))
        session.proofs += [(p["path"], p["sha256"]) for p in receipt["proofs"][1:]]

    source.say(f"\n== {drill.title}\n   Requirements: {drill.requirements}\n   Tests: {', '.join(drill.tests)}")
    source.say(f"   People: {drill.who}")
    if drill.targets:
        source.say("   Judged against: " + ", ".join(f"{key}={getattr(cfg, key)}" for key in drill.targets))
    if source.dry_run:
        source.say("   DRY RUN: example answers, marked DRY-RUN; the gate refuses everything this writes.")
    source.say("\nSteps:")
    for number, step in enumerate(drill.steps, 1):
        text = step(cfg) if callable(step) else step
        source.say(f"  {number}. {text}")
    source.say("\nRecord what you observed (Enter on a time stamps it now):")
    device = (
        f"{DRY_RUN} rehearsal device"
        if source.dry_run
        else answer(DEVICE, source, session, drill.id, ("device",), previous.get("device") if drill.append else None)
    )
    answers = collect(drill, source, session, previous, cfg)
    outputs = drill.build(answers, cfg, previous)
    reviewer = f"{DRY_RUN} reviewer" if source.dry_run else answer(REVIEWER, source, session, drill.id, ("reviewer",))
    completed = now()
    written: list[str] = []
    for name, data in outputs.items():
        if name.startswith("@"):
            side = folder / name[1:]
            _write_json(side, data)
            written.append(str(side))
            continue
        record = {
            "format": "jana.ops.probe.1",
            "test_name": name,
            "candidate_commit": candidate,
            "spec_revision": spec_revision,
            "source": SOURCES[name],
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "data": {**data, "device": device},
        }
        validate("ops/probe-record", record)
        probe = folder / drill.id / f"{name}.probe.json"
        digest = _write_json(probe, record)
        index["records"][name] = {
            "source": SOURCES[name],
            "reviewer": reviewer,
            "proofs": [{"path": probe.relative_to(folder).as_posix(), "sha256": digest}]
            + [{"path": path, "sha256": sha} for path, sha in session.proofs],
        }
        written.append(str(probe))
    validate("ops/field-evidence", index)
    _write_json(index_file, index)
    verdict = {name: check(index_file, name, now=now, cfg=cfg, spec_revision=spec_revision) for name in drill.tests}
    return {"index": str(index_file), "written": written, "verdict": verdict}


def check(index_file: Path, name: str, *, candidate: str | None = None, now: Callable[[], datetime] | None = None,
          cfg: Settings | None = None, spec_revision: str | None = None) -> list[str]:  # fmt: skip
    """What the JANA_M24_EVIDENCE acceptance check would say about one record ([] means it would pass)."""
    from ..release.field_evidence import field_errors, read_evidence

    moment = (now or (lambda: datetime.now(UTC)))()
    try:
        index = json.loads(index_file.read_text())
        evidence = read_evidence(
            index_file, name, candidate or index.get("candidate_commit", ""), spec_revision or current_spec(), moment
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [str(error)]
    return field_errors(name, evidence, moment, cfg)
