"""VSL-02: the client's renderers and the visual catalogue register stay in step. Renderer sources are synthetic."""

from __future__ import annotations

import shutil
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.visual_parity import (
    CLIENT_EVENTS,
    RENDERERS_SRC,
    build_stage,
    check,
    client_events,
    parity_errors,
    register_kinds,
    renderer_kinds,
)


def _client(tmp_path: Path, index: str, renderers: dict[str, str]) -> Path:
    """A copy of the client's event list with a synthetic renderers package."""
    src = tmp_path / RENDERERS_SRC
    src.mkdir(parents=True)
    (src / "index.ts").write_text(index)
    for name, kind in renderers.items():
        (src / f"{name}.tsx").write_text(f'export const {name}: VisualRenderer = {{\n  kind: "{kind}",\n}};\n')
    (tmp_path / CLIENT_EVENTS).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / CLIENT_EVENTS, tmp_path / CLIENT_EVENTS)
    return tmp_path


def vsl02_register_renderer_parity(tmp_path: Path) -> None:
    stage = build_stage()
    kinds = register_kinds()
    renderers, unreadable = renderer_kinds()
    events = client_events()
    # The repository as it stands passes, and the parity check is wired into the governance run.
    assert unreadable == [] and renderers, "RENDERERS lists readable renderers"
    assert check() == []
    from jana_tools.__main__ import CHECKS

    assert "visual-renderers" in CHECKS

    # A renderer for a kind the register does not list fails.
    assert parity_errors(kinds, [*renderers, "heart_3d"], events, stage) == [
        "renderer registered for heart_3d, which is not in the visual catalogue register"
    ]
    extra = _client(tmp_path / "extra", "export const RENDERERS = [functionGraph, heart];\n",
                    {"functionGraph": "function_graph", "heart": "heart_3d"})  # fmt: skip
    assert any("heart_3d" in e for e in check(extra))

    # A register kind at or before the build's stage without a renderer fails; a later-stage kind does not.
    early = [{**k, "stage": stage} if k["kind"] == "free_body" else k for k in kinds]
    without = [r for r in renderers if r != "free_body"]
    assert parity_errors(early, without, events, stage) == [f"free_body (stage {stage}) has no renderer in a "
                                                              f"{stage} build"]  # fmt: skip
    assert parity_errors(kinds, without, events, stage) == []
    missing = _client(tmp_path / "missing", "export const RENDERERS = [];\n", {})
    later = [k["kind"] for k in kinds if k.get("channel") == "visual.spec" and k["stage"] == "S2"]
    assert later
    errors = check(missing, stage="S2")
    assert all(any(e.startswith(f"{kind} (stage S2)") for e in errors) for kind in later)

    # The S1 board kinds are drawn from their board events; a client that drops one fails.
    s1_board = [k for k in kinds if k["stage"] == "S1" and k.get("channel", "").startswith("board.")]
    assert s1_board, "the S1 register has board kinds"
    dropped = parity_errors(kinds, renderers, events - {"board.knowns"}, "S1")
    assert dropped == ["knowns_panel (stage S1) is carried by board.knowns, which the client does not handle"]
    assert len(parity_errors(kinds, renderers, set(), "S1")) == len(s1_board)

    # One renderer per kind (VSL-18).
    assert parity_errors(kinds, [*renderers, renderers[0]], events, stage) == [
        f"more than one renderer registered for {renderers[0]}"
    ]
