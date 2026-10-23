"""CUR-36, CUR-02, D98: a corrected item names the retired item it replaces (`corrects`), and the pack carries it.

The builder takes `corrects` from the item source into the pack, where the device's content index returns it; it
refuses a `corrects` naming the item's own id or an id the pack has not retired. Copies of the S1 physics source with
one edit each; the edits are invented test data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.store.pack_index import PackIndex
from agent_core.store.packs import read_pack
from test_m6cd_packs import _copy, _edit, _problems, build

RETIRED = "itm.phy.o.motion.0999"  # a withdrawn item of an earlier version (never in this source)


def _correct(target: str) -> Any:
    def change(data: dict[str, Any]) -> None:
        data["items"][0]["corrects"] = target

    return change


def test_corrects_is_carried_into_the_pack_and_read_back(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    _edit(source, "pack.yaml", lambda d: d.update(retired_ids=[RETIRED]))
    _edit(source, "items.yaml", _correct(RETIRED))
    built = build(source, tmp_path / "out")
    assert RETIRED in built.manifest["retired_ids"] and built.manifest["schema_version"] == "1.4.0"
    path = next((tmp_path / "out").glob("*.pack"))
    _, tables = read_pack(path)
    corrected = [i for i in tables["items"] if i.get("corrects")]
    assert [i["corrects"] for i in corrected] == [RETIRED]
    index = PackIndex.from_tables([read_pack(path)])
    assert index.record("items", corrected[0]["id"])["corrects"] == RETIRED  # type: ignore[index]


def test_corrects_must_name_a_retired_id_never_its_own(tmp_path: Path) -> None:
    source = _copy(tmp_path / "own")
    _edit(source, "items.yaml", lambda d: d["items"][0].update(corrects=d["items"][0]["id"]))
    assert "corrects its own id" in _problems(source, tmp_path)
    source = _copy(tmp_path / "unretired")
    _edit(source, "items.yaml", _correct(RETIRED))
    assert f"corrects {RETIRED}, which is not a retired id" in _problems(source, tmp_path)
    # Retired by the build's own list (an earlier version's ids) is retired too.
    source = _copy(tmp_path / "earlier")
    _edit(source, "items.yaml", _correct(RETIRED))
    assert build(source, tmp_path / "out2", retired=[RETIRED]).manifest["retired_ids"] == [RETIRED]
