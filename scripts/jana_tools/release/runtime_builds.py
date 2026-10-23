"""Fetching the pinned llama.cpp builds into the bundle at build time (PLT-04, PLT-02; the M11 packaging gap).

The pins live in `scripts/release/runtime-builds.toml`: one upstream release, one archive per OS and variant, each
with its sha256. `fetch` refuses any placeholder, downloads each archive once (to a cache folder, so the same archive
serving two variants is fetched once), checks its sha256 before opening it, and extracts only the members the pin
lists, never a path that leaves the target, into `<out>/runtime/<variant>/` with a `BUILD.json` naming the release,
commit, archive and hash. A wrong hash fails the build with nothing extracted.

This runs in the release job only (it needs the network and the owner's pins); tests drive it with `file://` URLs.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import tarfile
import tomllib
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any

from .. import REPO_ROOT

PINS = REPO_ROOT / "scripts" / "release" / "runtime-builds.toml"
PLACEHOLDER = "PLACEHOLDER"
OSES = ("windows", "macos", "linux")
BLOCK = 1024 * 1024
Opener = Callable[[str], IO[bytes]]


class FetchRefused(ValueError):
    pass


@dataclass(frozen=True)
class Build:
    os: str
    variant: str
    asset: str
    sha256: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Pins:
    release: str
    commit: str
    licence: str
    source: str
    builds: tuple[Build, ...]

    def url(self, build: Build) -> str:
        return self.source.format(release=self.release, asset=build.asset.format(release=self.release))


def load_pins(path: Path = PINS) -> Pins:
    data: dict[str, Any] = tomllib.loads(path.read_text())
    head = data["llama_cpp"]
    builds = tuple(Build(b["os"], b["variant"], b["asset"], b["sha256"], tuple(b["members"])) for b in data["build"])
    return Pins(head["release"], head["commit"], head["licence"], head["source"], builds)


def placeholder_errors(pins: Pins, os_name: str) -> list[str]:
    """What the owner still has to pin before a release can fetch for `os_name`."""
    errors = [f"llama_cpp.{field} is a placeholder" for field in ("release", "commit")
              if PLACEHOLDER in getattr(pins, field)]  # fmt: skip
    errors += [f"{b.os}/{b.variant}: sha256 is a placeholder" for b in pins.builds
               if b.os == os_name and PLACEHOLDER in b.sha256]  # fmt: skip
    if not any(b.os == os_name for b in pins.builds):
        errors.append(f"no runtime build is pinned for {os_name}")
    return errors


def _download(url: str, target: Path, sha256: str, opener: Opener) -> Path:
    if target.is_file() and _file_sha256(target) == sha256:
        return target
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    with opener(url) as source, partial.open("wb") as out:
        while block := source.read(BLOCK):
            digest.update(block)
            out.write(block)
    if digest.hexdigest() != sha256:
        partial.unlink()
        raise FetchRefused(f"{url}: sha256 {digest.hexdigest()} does not match the pinned {sha256}")
    partial.replace(target)
    return target


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _wanted(name: str, members: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in members)


def _safe_name(name: str) -> str | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.name:
        return None
    return path.name  # flattened: every runtime file sits beside llama-server


def _extract(archive: Path, members: tuple[str, ...], target: Path) -> list[str]:
    taken: list[str] = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = _safe_name(info.filename)
                if info.is_dir() or name is None or not _wanted(info.filename, members):
                    continue
                with bundle.open(info) as source, (target / name).open("wb") as out:
                    shutil.copyfileobj(source, out)
                taken.append(name)
    else:
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                name = _safe_name(member.name)
                if not member.isfile() or name is None or not _wanted(member.name, members):
                    continue
                source = bundle.extractfile(member)
                if source is None:
                    continue
                with source, (target / name).open("wb") as out:
                    shutil.copyfileobj(source, out)
                taken.append(name)
    return sorted(taken)


def fetch(pins: Pins, os_name: str, out: Path, cache: Path, opener: Opener = urllib.request.urlopen,
          allow_placeholders: bool = False) -> list[Path]:  # fmt: skip
    """Fetch, check and extract every pinned build for `os_name`; returns the variant folders written."""
    problems = [] if allow_placeholders else placeholder_errors(pins, os_name)
    if problems:
        raise FetchRefused("; ".join(problems))
    cache.mkdir(parents=True, exist_ok=True)
    written = []
    for build in (b for b in pins.builds if b.os == os_name):
        asset = build.asset.format(release=pins.release)
        archive = _download(pins.url(build), cache / asset, build.sha256, opener)
        target = out / "runtime" / build.variant
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        taken = _extract(archive, build.members, target)
        server = "llama-server.exe" if os_name == "windows" else "llama-server"
        if server not in taken:
            shutil.rmtree(target)
            raise FetchRefused(f"{asset}: no {server} among the pinned members")
        if os_name != "windows":
            (target / server).chmod(0o755)
        (target / "BUILD.json").write_text(json.dumps({"release": pins.release, "commit": pins.commit,
                                                       "licence": pins.licence, "asset": asset,
                                                       "sha256": build.sha256, "files": taken},
                                                      indent=1, sort_keys=True) + "\n")  # fmt: skip
        written.append(target)
    return written
