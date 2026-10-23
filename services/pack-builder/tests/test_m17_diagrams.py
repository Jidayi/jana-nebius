"""M17.c: the diagram library in packs (VSL-22, VSL-23, VSL-24, VSL-29, VSL-34, CUR-29).

The library entries and presets are our own drawings and parameters in the content tree. Until the specification
adopted the library fields (D83), a pack built under the bundled contract held them back; these tests build
under the contract with the additions applied, as the packs will be built once it lands. Seeded faults are applied to
copies of the source tree."""

from __future__ import annotations

import copy
import json
import re
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.contracts import document
from agent_core.contracts import errors as contract_errors
from agent_core.store import packs
from agent_core.store.packs import PackRejectedError, read_pack, table_sha256, verify, write_pack
from agent_core.store.svg import lint_problems, normalise, parts_problems, sanitise_problems
from pack_builder import source as tree
from pack_builder.build import BuildError
from pack_builder.build import build as _build
from pack_builder.diagrams import diagram_problems
from pack_builder.signing import sign
from signing_service.keys import DEV_KEY_ID, dev_key

REPO = Path(__file__).resolve().parents[3]
PHY = REPO / "content" / "curriculum" / "phy" / "o"
CHM = REPO / "content" / "curriculum" / "chm" / "o"
MIRROR = "dgm.phy.plane_mirror_reflection.v1"
SETTINGS = Settings()


@contextmanager
def visual_contract() -> Iterator[None]:
    """The pack tables the bundled content-pack contract declares, for the block."""
    tree._schema.cache_clear()
    saved = packs.TABLES
    packs.TABLES = packs.contract_tables()
    try:
        yield
    finally:
        packs.TABLES = saved
        tree._schema.cache_clear()


def build(source: Path, out: Path) -> Any:
    return _build(source, out, key=dev_key(), key_id=DEV_KEY_ID)


def _copy(tmp_path: Path, source: Path = PHY) -> Path:
    target = tmp_path / "src" / source.parent.name / "o"
    shutil.copytree(source, target)
    shutil.copytree(tree.ref_dir(source), tree.ref_dir(target))
    return target


def _entry(pack: Path, rid: str) -> dict[str, Any]:
    entry: dict[str, Any] = yaml.safe_load((pack / "diagrams" / f"{rid}.yaml").read_text())
    return entry


def _svg(pack: Path, entry: dict[str, Any]) -> str:
    return normalise((pack / entry["svg_path"]).read_text())


def _problems(source: Path, tmp_path: Path) -> str:
    with visual_contract(), pytest.raises(BuildError) as failed:
        build(source, tmp_path / "out")
    return "\n".join(failed.value.problems)


@pytest.fixture(scope="module")
def built_phy(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("phy")
    with visual_contract():
        built = build(PHY, out)
        doc: dict[str, Any] = json.loads(built.json_path.read_text())
        doc["_pack_path"] = str(built.pack_path)
        doc["_report"] = json.loads(built.report_path.read_text())
    return doc


# --- VSL-22 and CUR-29 ----------------------------------------------------------------------------------------------


def vsl22_library_entries_valid(built_phy: dict[str, Any], tmp_path: Path) -> None:
    with visual_contract():
        chm = json.loads(build(CHM, tmp_path / "chm").json_path.read_text())
    entries = [*built_phy["diagrams"], *chm["diagrams"]]
    assert len(entries) >= 4 and built_phy["_report"]["held_back"] == []
    heart_dir = REPO / "packages" / "renderers" / "fixtures" / "library"
    heart = json.loads((heart_dir / "dgm.bio.heart.v1.json").read_text())
    entries.append({**heart, "svg": normalise((heart_dir / "heart_v1.svg").read_text())})
    for record in entries:
        entry = {k: v for k, v in record.items() if k != "svg"}
        assert contract_errors("visuals/diagram-entry", entry) == [], record["id"]
        drawn = re.findall(r'data-part="([^"]+)"', record["svg"])
        declared = [p["id"] for p in entry["parts"]]
        assert sorted(drawn) == sorted(declared), record["id"]
        assert parts_problems(entry, record["svg"]) == [], record["id"]


def vsl22_entry_projects_to_diagram_ref(built_phy: dict[str, Any]) -> None:
    base = document("content/content-pack")["$defs"]["DiagramRef"]
    shared = set(base["properties"])
    part_fields = set(base["properties"]["parts"]["items"]["properties"])
    step_fields = set(base["properties"]["sequences"]["items"]["properties"]["steps"]["items"]["properties"])
    seq_fields = set(base["properties"]["sequences"]["items"]["properties"])
    with visual_contract():
        for record in built_phy["diagrams"]:
            stripped = {k: copy.deepcopy(v) for k, v in record.items() if k in shared}
            stripped["parts"] = [{k: v for k, v in p.items() if k in part_fields} for p in stripped["parts"]]
            stripped["sequences"] = [
                {
                    **{k: v for k, v in s.items() if k in seq_fields},
                    "steps": [{k: v for k, v in st.items() if k in step_fields} for st in s["steps"]],
                }
                for s in stripped.get("sequences", [])
            ]
            # With approval retired (D65), a library-only-free entry is a DiagramRef (the replace in the additions).
            assert contract_errors("content/content-pack#/$defs/DiagramRef", stripped) == [], record["id"]
            assert contract_errors("content/content-pack#/$defs/DiagramRef", record) == [], record["id"]


def test_bundled_contract_carries_the_library(tmp_path: Path) -> None:
    """With the library fields and the visual_presets table in the contract (D83), the build carries every diagram,
    with its sanitised SVG, and every preset; nothing is held back."""
    built = build(PHY, tmp_path / "out")
    report = json.loads(built.report_path.read_text())
    assert report["held_back"] == []
    _, tables = read_pack(built.pack_path)
    diagrams = {d["id"]: d for d in tables["diagrams"]}
    assert MIRROR in diagrams and all(d.get("svg") for d in diagrams.values())
    assert tables["visual_presets"]


def cur29_diagram_parts_resolve(tmp_path: Path) -> None:
    source = _copy(tmp_path / "missing")
    svg = source / _entry(source, MIRROR)["svg_path"]
    text = svg.read_text()
    svg.write_text(re.sub(r'  <g data-part="angle_r">.*?</g>\n', "", text, flags=re.S))
    assert "part angle_r has no element in the SVG" in _problems(source, tmp_path / "a")
    source = _copy(tmp_path / "sequence")
    path = source / "diagrams" / f"{MIRROR}.yaml"
    entry = yaml.safe_load(path.read_text())
    entry["sequences"][0]["steps"][0]["highlight"] = ["periscope"]
    path.write_text(tree.canonical(entry, "diagrams"))
    problems = _problems(source, tmp_path / "b")
    assert "names unknown part periscope" in problems or "periscope" in problems


# --- VSL-23 ---------------------------------------------------------------------------------------------------------


def vsl23_event_handler_rejected(built_phy: dict[str, Any], tmp_path: Path) -> None:
    # At build: a drawing with an onload attribute is refused.
    source = _copy(tmp_path / "onload")
    svg = source / _entry(source, MIRROR)["svg_path"]
    svg.write_text(svg.read_text().replace("<svg ", '<svg onload="alert(1)" ', 1))
    assert "has an event handler (onload)" in _problems(source, tmp_path / "build")
    # At load: a signed pack whose stored drawing carries one is refused, though its hashes and signature are good.
    with visual_contract():
        manifest, tables = read_pack(Path(built_phy["_pack_path"]))
        tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        tables["diagrams"][0]["svg"] = tables["diagrams"][0]["svg"].replace("<svg ", '<svg onload="alert(1)" ', 1)
        unsigned = {k: v for k, v in manifest.items() if k != "signature"}
        unsigned["tables"] = [{**t, "sha256": table_sha256(t["name"], tables[t["name"]])} for t in manifest["tables"]]
        signed = sign(unsigned, dev_key(), DEV_KEY_ID)
        bad = tmp_path / "onload.pack"
        write_pack(bad, signed, tables)
        with pytest.raises(PackRejectedError, match="event handler"):
            verify(bad, Environment.DEV)
        assert verify(Path(built_phy["_pack_path"]), Environment.DEV)["pack_id"] == "pack.phy.o"
    # The allow-list in full: scripts, foreign content, outside references and data URLs are refused.
    clean = _svg(PHY, _entry(PHY, MIRROR))
    limit = SETTINGS.visual_library_svg_max_kb * 1024
    for seeded, expected in (
        ("<script>alert(1)</script>", "<script> is not allowed"),
        ("<foreignObject><div/></foreignObject>", "foreignObject"),
        ('<use href="https://example.org/x.svg#a"/>', "refers outside the document"),
        ('<rect fill="url(https://example.org/p.png)"/>', "external url()"),
        ('<image href="data:image/png;base64,AAAA"/>', "<image> is not allowed"),
        ('<rect style="fill:red"/>', "style attribute"),
    ):
        text = clean.replace("</svg>", f"{seeded}</svg>")
        assert any(expected in p for p in sanitise_problems(text, limit)), seeded
    assert sanitise_problems("<!DOCTYPE svg><svg/>", limit) == ["a doctype or entity declaration"]
    assert sanitise_problems(clean, limit) == []


# --- VSL-24 ---------------------------------------------------------------------------------------------------------


def vsl24_noncommercial_rejected(tmp_path: Path) -> None:
    source = _copy(tmp_path / "nc")
    path = source / "diagrams" / f"{MIRROR}.yaml"
    entry = yaml.safe_load(path.read_text())
    entry["licence"] = "CC-BY-NC-4.0"
    entry["attribution"] = "A borrowed drawing"
    entry["sources"] = [
        {
            "title": "Some textbook figure",
            "url": "https://example.org/figure",
            "licence": "CC-BY-NC-4.0",
            "attribution": "Someone else",
            "modifications": "none",
            "retrieved": "2026-10-01",
        }
    ]
    path.write_text(tree.canonical(entry, "diagrams"))
    problems = _problems(source, tmp_path / "out")
    assert "non-commercial or no-derivatives and cannot ship (VSL-24)" in problems
    assert "licence CC-BY-NC-4.0 is not allowed for diagrams" in problems
    # A share-alike drawing is a diagram-only exception, with its attribution and sources (CUR-23).
    source = _copy(tmp_path / "sa")
    path = source / "diagrams" / f"{MIRROR}.yaml"
    entry = yaml.safe_load(path.read_text())
    entry["licence"] = "CC-BY-SA-4.0"
    entry["sources"] = [
        {
            "title": "A share-alike figure",
            "url": "https://example.org/sa",
            "licence": "CC-BY-SA-4.0",
            "attribution": "Its author",
            "modifications": "redrawn",
            "retrieved": "2026-10-01",
        }
    ]
    path.write_text(tree.canonical(entry, "diagrams"))
    with visual_contract():
        built = build(source, tmp_path / "sa-out")
    credits = json.loads(built.report_path.read_text())["credits"]
    assert any(c["title"] == "A share-alike figure" and MIRROR in c["used_by"] for c in credits)


# --- VSL-34 ---------------------------------------------------------------------------------------------------------

STROKE = 'stroke="var(--color-muted)"'
ARC = 'fill="none" stroke="var(--color-diagram-stroke)"'
PINK = 'fill="var(--content-pink)" data-content-colour="pink"'
NORMAL = 'fill="var(--color-ink)" data-label-for="normal"'


def _swap(old: str, new: str) -> Callable[[str], str]:
    return lambda svg: svg.replace(old, new, 1)


SEEDED: dict[str, tuple[Callable[[str], str] | None, str]] = {
    "overlapping labels": (_swap('x="340" y="90"', 'x="44" y="92"'), "overlap"),
    "a part without a name": (None, "has no name"),
    "a part without a label anchor": (None, "has no label anchor"),
    "a colour outside the tokens": (_swap(STROKE, 'stroke="#ff0000"'), "fixed colour"),
    "a status token in a drawing": (_swap(STROKE, 'stroke="var(--color-danger)"'), "not a drawing token"),
    "a stroke outside the style guide": (_swap('stroke-width="1.5"', 'stroke-width="2.5"'), "style guide"),
    "text below the minimum size": (_swap('font-size="13"', 'font-size="9"'), "at least 12"),
    "faint label text": (_swap(NORMAL, NORMAL.replace("ink", "faint")), "too faint"),
    "a content colour without its name": (
        _swap(ARC, f'{PINK} stroke="var(--color-line-strong)"'),
        "not named in a label",
    ),
    "a content colour without an outline": (
        _swap(ARC, f'{PINK} stroke="var(--color-diagram-stroke)"'),
        "no line-strong outline",
    ),
    "parts out of tab order": (None, "not their tab order"),
}


def vsl34_lint_seeded_defects() -> None:
    entry = _entry(PHY, MIRROR)
    clean = _svg(PHY, entry)
    assert lint_problems(clean, entry) == [] and diagram_problems(entry, clean, SETTINGS) == []
    for defect, (change, expected) in SEEDED.items():
        svg, seeded = clean, copy.deepcopy(entry)
        if change is not None:
            svg = change(clean)
            assert svg != clean, defect
        elif defect == "a part without a name":
            seeded["parts"][0]["name"] = " "
        elif defect == "a part without a label anchor":
            del seeded["parts"][1]["label_anchor"]
        elif defect == "parts out of tab order":
            seeded["parts"][0]["tab_order"], seeded["parts"][1]["tab_order"] = 1, 0
        found = lint_problems(svg, seeded)
        assert any(expected in p for p in found), (defect, found)
        # The build reports the same lint problem for the entry.
        assert any(expected in p for p in diagram_problems(seeded, svg, SETTINGS)), defect


# --- VSL-29 ---------------------------------------------------------------------------------------------------------


def test_presets_carried_pre_resolved(built_phy: dict[str, Any]) -> None:
    presets = {p["id"]: p for p in built_phy["visual_presets"]}
    assert {"dgm.phy.circuit_series_two_lamps.v1", "dgm.phy.ray_converging_beyond_2f.v1"} <= set(presets)
    for rid, preset in presets.items():
        resolved = preset["resolved"]
        assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == [], rid
        assert resolved["ref"] == rid and resolved["status"] == "ok"
        # Every number it shows is traced: build checks and the preset's own pack record.
        assert any(s.startswith("chk_build_") for s in resolved["numbers_from"]), rid
        assert f"pack:pack.phy.o/visual_presets/{rid}" in resolved["numbers_from"], rid


def test_preset_with_bad_params_fails_the_build(tmp_path: Path) -> None:
    source = _copy(tmp_path / "preset")
    path = source / "presets" / "dgm.phy.ray_converging_beyond_2f.v1.yaml"
    preset = yaml.safe_load(path.read_text())
    preset["params"]["optic"] = "periscope"
    path.write_text(yaml.safe_dump(preset, sort_keys=True, allow_unicode=True))
    assert "dgm.phy.ray_converging_beyond_2f.v1: does not resolve (visual_param_invalid" in _problems(source, tmp_path)
