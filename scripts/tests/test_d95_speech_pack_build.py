"""D95, VOC-02, VOC-03: the speech pack build records every runtime file's licence and source, refuses unknown
licences, unowned files and modified LGPL libraries, and lays out a read-aloud-only pack per class. Synthetic wheels
only; the real build runs outside the repository (`python -m jana_tools.release.speech_pack build`)."""

import base64
import hashlib
from pathlib import Path

import pytest
from jana_tools.release import speech_pack as build


def wheel(site: Path, name: str, version: str, files: dict[str, bytes], *, licence_text: bool = True) -> None:
    info = site / f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    files = {**files, f"{info.name}/METADATA": metadata}
    if licence_text:
        files = {**files, f"{info.name}/COPYING": b"licence text"}
    rows = []
    for relative, payload in files.items():
        (site / relative).parent.mkdir(parents=True, exist_ok=True)
        (site / relative).write_bytes(payload)
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        rows.append(f"{relative},sha256={digest},{len(payload)}")
    rows += [f"{info.name}/RECORD,,", f"../../../bin/{name},,"]
    (info / "RECORD").write_text("\n".join(rows) + "\n")


def test_d95_runtime_files_carry_their_distribution_licence(tmp_path):
    site = tmp_path / "site"
    wheel(site, "num2words", "0.5.14", {"num2words/__init__.py": b"lgpl library"})
    wheel(site, "misaki", "0.9.4", {"misaki/en.py": b"g2p", "misaki/espeak.py": b"gpl wrapper"})
    plan = build.Plan()
    build.add_site(plan, site, "runtime/kokoro-cpu", ["low", "mid"])
    paths = {entry.path: entry for entry in plan.entries}
    assert "runtime/kokoro-cpu/misaki/espeak.py" not in paths  # pruned: the gate refuses espeak by name
    lgpl = paths["runtime/kokoro-cpu/num2words/__init__.py"]
    assert lgpl.spdx == "LGPL-2.1-or-later" and lgpl.expected_sha256 == hashlib.sha256(b"lgpl library").hexdigest()
    assert lgpl.source_url == "https://pypi.org/project/num2words/0.5.14/" and "separate library" in lgpl.attribution
    assert paths["runtime/kokoro-cpu/misaki/en.py"].spdx == "Apache-2.0"
    assert not any(p.endswith("bin/num2words") for p in paths)  # console scripts are not shipped


@pytest.mark.parametrize("problem", ["unknown_licence", "stray_file", "lgpl_without_record_hash"])
def test_d95_build_refuses_what_it_cannot_account_for(tmp_path, problem):
    site = tmp_path / "site"
    if problem == "unknown_licence":
        wheel(site, "mystery", "1.0", {"mystery/__init__.py": b"x"})
    else:
        wheel(site, "num2words", "0.5.14", {"num2words/__init__.py": b"lgpl library"})
    if problem == "stray_file":
        (site / "loose.py").write_text("owned by no distribution")
    if problem == "lgpl_without_record_hash":
        record = site / "num2words-0.5.14.dist-info" / "RECORD"
        record.write_text(record.read_text().replace("num2words/__init__.py,sha256=", "num2words/__init__.py,x="))
    with pytest.raises(build.BuildError):
        build.add_site(build.Plan(), site, "runtime/kokoro-cpu", ["low", "mid"])


def test_d95_profiles_and_entry_points():
    profiles = build.profiles()
    assert {c: (p["stt"], p["tts"], p["speaker"], p["device"]) for c, p in profiles.items()} == {
        "low": ("none", "kokoro", "af_heart", "cpu"),
        "mid": ("none", "kokoro", "af_heart", "cpu"),
        "high": ("none", "qwen3", "Ryan", "mps"),
    }
    entry = build.ENTRY.format(runtime="kokoro-cpu")
    # The shell clears the environment: no PATH lookups, an isolated interpreter, only the pack's own folders.
    assert "-I -S" in entry and "dirname" not in entry and "kokoro-cpu" in entry
    assert "addsitedir" in build.BOOTSTRAP and "kokoro-cpu" in build.BOOTSTRAP
