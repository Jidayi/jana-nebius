"""The installers' own words (LOC-01, PLT-24, PLT-01, PLT-06). `apps/desktop/src-tauri/installer/strings.json` is the
catalogue, one object per locale; `strings.nsh`, the LangString include that `hooks.nsh` reads, is generated from it,
leaving out the `janaPrecheck*` keys: those are the precheck's messages, which `jana-precheck` reads from the catalogue
itself (`src/installer.rs` embeds it). The check fails when strings.nsh is stale, when a locale lacks a key English
has, when hooks.nsh shows a word on screen (a MessageBox, an nsDialogs control or a DetailPrint line) that is not a
catalogue key, and when the precheck names a key the catalogue does not define."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import REPO_ROOT

INSTALLER = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "installer"
# The Windows language id of each locale the app may ship (D20): NSIS selects the strings by the system language.
LANGUAGE_IDS = {"en": 1033, "fr": 1036, "pt": 2070, "ar": 1025}
HEADER = (
    "; Generated from strings.json by `uv run python -m jana_tools installer-strings --write`; do not edit (LOC-01).\n"
    "; Numeric language ids: this file is included before the installer loads its languages.\n"
)
_SHOWN = re.compile(r"MessageBox|NSD_Create|DetailPrint")
PRECHECK_PREFIX = "janaPrecheck"  # read by jana-precheck, not by NSIS
_PRECHECK_KEY = re.compile(r'"(janaPrecheck\w+)"')
_QUOTED = re.compile(r'"((?:[^"$]|\$.)*)"')
_KEY = re.compile(r"\$\((\w+)\)")


def _escape(text: str) -> str:
    return text.replace("$", "$$").replace('"', '$\\"').replace("\n", "$\\r$\\n")


def catalogue(folder: Path = INSTALLER) -> dict[str, dict[str, str]]:
    raw = json.loads((folder / "strings.json").read_text())
    return {locale: words for locale, words in raw.items() if not locale.startswith("_")}


def render(words: dict[str, dict[str, str]]) -> str:
    lines = [
        f'LangString {key} {LANGUAGE_IDS[locale]} "{_escape(text)}"'
        for locale in sorted(words, key=lambda loc: (loc != "en", loc))
        for key, text in words[locale].items()
        if not key.startswith(PRECHECK_PREFIX)
    ]
    return HEADER + "\n".join(lines) + "\n"


def installer_string_errors(folder: Path = INSTALLER) -> list[str]:
    words = catalogue(folder)
    errors = [f"LOC-01: installer locale {loc} has no Windows language id" for loc in words if loc not in LANGUAGE_IDS]
    english = set(words.get("en", {}))
    errors += [f"LOC-01: installer locale {loc} lacks {sorted(english - set(w))}" for loc, w in words.items()
               if english - set(w)]  # fmt: skip
    if errors:
        return errors
    nsh = folder / "strings.nsh"
    if not nsh.is_file() or nsh.read_text() != render(words):
        errors.append("LOC-01: installer/strings.nsh is stale; run: python -m jana_tools installer-strings --write")
    hooks = (folder / "hooks.nsh").read_text()
    for number, line in enumerate(hooks.splitlines(), 1):
        if line.lstrip().startswith(";") or not _SHOWN.search(line):
            continue
        for text in _QUOTED.findall(line):
            shown = _KEY.sub("", re.sub(r"\$(?:R?\d|\\r|\\n)", "", text)).strip()
            if shown:
                errors.append(f"LOC-01: hooks.nsh:{number} shows words that are not an installer string key: {text}")
    errors += [f"LOC-01: hooks.nsh uses {key}, which strings.json does not define" for key in _KEY.findall(hooks)
               if key not in english]  # fmt: skip
    source = folder.parent / "src" / "installer.rs"
    if source.is_file():
        errors += [f"LOC-01: the precheck shows {key}, which strings.json does not define"
                   for key in sorted(set(_PRECHECK_KEY.findall(source.read_text()))) if key not in english]  # fmt: skip
    return errors


def write(folder: Path = INSTALLER) -> Path:
    path = folder / "strings.nsh"
    path.write_text(render(catalogue(folder)))
    return path
