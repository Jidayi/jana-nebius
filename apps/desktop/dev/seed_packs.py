"""Development only: the O level content packs for a `pnpm dev` run (UXS-22, CUR-08).

Builds each O level pack from the repository's curriculum sources with the pack builder (held-out items are excluded
by every build), signs it with the published development key, which pilot and production builds never trust (OPS-35),
and installs it into the dev data folder the way a USB kit install does (`PackStore.install`, verified before it is
used). A build runs every content gate and takes minutes, so built packs are kept in a cache outside the repository,
keyed by a hash of each pack's sources; an unchanged pack installs in a moment. A pack that fails to build is reported
and skipped; the others still install.

Usage: uv run python apps/desktop/dev/seed_packs.py <data_dir> [<cache_dir>]
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

from agent_core.config.environments import Environment
from agent_core.store.pack_store import PackStore
from pack_builder.build import BuildError, build
from signing_service.hierarchy import dev_signer

REPO = Path(__file__).resolve().parents[3]
CURRICULUM = REPO / "content" / "curriculum"


def source_hash(source: Path) -> str:
    """The pack's sources and the shared reference lists, so any edit builds the pack again."""
    digest = hashlib.sha256()
    for root in (source, CURRICULUM / "ref"):
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(CURRICULUM)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:24]


def built_pack(source: Path, cache: Path) -> Path:
    folder = cache / f"{source.parent.name}-{source.name}-{source_hash(source)}"
    found = sorted(folder.glob("*.pack"))
    if found:
        return found[0]
    signer = dev_signer()
    with tempfile.TemporaryDirectory(prefix="jana-dev-pack-") as out:
        built = build(source, Path(out), sign_with=lambda m: signer.sign("content_pack", m))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / built.pack_path.name
        shutil.copyfile(built.pack_path, target)
    return target


def seed(data_dir: Path, cache: Path) -> list[str]:
    store = PackStore(data_dir / "packs", Environment.DEV)
    installed: list[str] = []
    for source in sorted(p.parent for p in CURRICULUM.glob("*/o/pack.yaml")):
        try:
            manifest = store.install(built_pack(source, cache))
        except (BuildError, ValueError, OSError) as error:
            print(f"dev packs: {source.relative_to(REPO)} skipped: {error}", file=sys.stderr)
            continue
        installed.append(f"{manifest['pack_id']} {manifest['version']}")
    return installed


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    cache = Path(argv[2]) if len(argv) == 3 else Path(tempfile.gettempdir()) / "jana-dev-packs"
    for line in seed(Path(argv[1]), cache):
        print(f"dev packs: installed {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
