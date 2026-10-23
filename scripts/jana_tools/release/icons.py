"""The app icon set and its release check (DSN-25).

The icon ships as Windows ICO (16 to 256 px), macOS ICNS (16 to 1,024 px) and Linux PNG (16 to 512 px). Until the
brand artwork is signed off, development builds carry a placeholder: the initial "J" in the `accent-ink` colour on
`accent`, drawn here from the design tokens with no font or image library. `icons/placeholder.json` lists the sha256
of every placeholder file; a release build fails while any bundled icon is one of them, and every installer and
bundle must carry the icon at each listed size.

    python -m jana_tools release icons --write          (re)draw the placeholder set
    python -m jana_tools release icons [--release] DIR   check a folder of icons (a bundle's or the source's)
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

from .. import REPO_ROOT

ICONS = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "icons"
TOKENS = REPO_ROOT / "packages" / "ui" / "src" / "generated" / "tokens.css"
PLACEHOLDER = "placeholder.json"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = {b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128, b"ic08": 256, b"ic09": 512, b"ic10": 1024}
PNG_SIZES = (16, 32, 48, 64, 128, 256, 512)
# The initial on a 5 x 7 grid ("#" is ink).
GLYPH = ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##..")


def _colour(name: str) -> tuple[int, int, int]:
    found = re.search(rf"--color-{name}:\s*#([0-9A-Fa-f]{{6}})", TOKENS.read_text())
    if not found:
        raise ValueError(f"no --color-{name} in the design tokens")
    value = found.group(1)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def png(size: int, background: tuple[int, int, int], ink: tuple[int, int, int]) -> bytes:
    """A square RGBA PNG of the placeholder at `size` pixels."""
    rows = len(GLYPH)
    cols = len(GLYPH[0])
    cell = max(1, (size * 6 // 10) // rows)
    left = (size - cell * cols) // 2
    top = (size - cell * rows) // 2
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            gy, gx = (y - top) // cell, (x - left) // cell
            inside = 0 <= gy < rows and 0 <= gx < cols and y >= top and x >= left and GLYPH[gy][gx] == "#"
            raw += bytes((*(ink if inside else background), 255))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def ico(images: dict[int, bytes]) -> bytes:
    """An ICO holding PNG images (Windows Vista and later read PNG entries)."""
    sizes = sorted(images)
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    body = b""
    for size in sizes:
        data = images[size]
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return out + body


def icns(images: dict[bytes, bytes]) -> bytes:
    body = b"".join(kind + struct.pack(">I", len(data) + 8) + data for kind, data in images.items())
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def png_size(data: bytes) -> int | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width) if width == height else None


def ico_sizes(data: bytes) -> set[int]:
    _, kind, count = struct.unpack("<HHH", data[:6])
    if kind != 1:
        return set()
    found = set()
    for n in range(count):
        dim, _, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * n : 22 + 16 * n])
        actual = png_size(data[offset : offset + size])
        found.add(actual if actual is not None else (dim or 256))
    return found


def icns_sizes(data: bytes) -> set[int]:
    if data[:4] != b"icns":
        return set()
    found, at = set(), 8
    while at + 8 <= len(data):
        kind, length = data[at : at + 4], struct.unpack(">I", data[at + 4 : at + 8])[0]
        if kind in ICNS_TYPES and png_size(data[at + 8 : at + length]) == ICNS_TYPES[kind]:
            found.add(ICNS_TYPES[kind])
        at += max(length, 8)
    return found


def write_placeholder(folder: Path = ICONS) -> list[Path]:
    """Draw the development placeholder set and record its hashes in `placeholder.json`."""
    background, ink = _colour("accent"), _colour("accent-ink")
    folder.mkdir(parents=True, exist_ok=True)
    every = sorted(set(ICO_SIZES) | set(ICNS_TYPES.values()) | set(PNG_SIZES))
    drawn = {size: png(size, background, ink) for size in every}
    written = {"icon.ico": ico({s: drawn[s] for s in ICO_SIZES}),
               "icon.icns": icns({k: drawn[s] for k, s in ICNS_TYPES.items()}),
               "icon.png": drawn[512],
               **{f"{s}x{s}.png": drawn[s] for s in PNG_SIZES}}  # fmt: skip
    for name, data in written.items():
        (folder / name).write_bytes(data)
    record = {"$comment": "Development placeholder icons (DSN-25): a release build fails while any bundled icon has "
                          "one of these hashes. Replace the files with the signed-off artwork; do not edit by hand.",
              "sha256": sorted(hashlib.sha256(d).hexdigest() for d in written.values())}  # fmt: skip
    (folder / PLACEHOLDER).write_text(json.dumps(record, indent=1) + "\n")
    return [folder / name for name in written]


def icon_errors(folder: Path, release: bool, placeholders: Path = ICONS / PLACEHOLDER) -> list[str]:
    """Every listed size present in the ICO, ICNS and PNG set; in a release, none of them the placeholder."""
    errors = []
    ico_file, icns_file = folder / "icon.ico", folder / "icon.icns"
    have_ico = ico_sizes(ico_file.read_bytes()) if ico_file.is_file() else set()
    if set(ICO_SIZES) - have_ico:
        errors.append(f"icon.ico lacks sizes {sorted(set(ICO_SIZES) - have_ico)}")
    have_icns = icns_sizes(icns_file.read_bytes()) if icns_file.is_file() else set()
    if set(ICNS_TYPES.values()) - have_icns:
        errors.append(f"icon.icns lacks sizes {sorted(set(ICNS_TYPES.values()) - have_icns)}")
    for size in PNG_SIZES:
        path = folder / f"{size}x{size}.png"
        if not path.is_file() or png_size(path.read_bytes()) != size:
            errors.append(f"{path.name} is missing or not {size} px square")
    if release and placeholders.is_file():
        known = set(json.loads(placeholders.read_text())["sha256"])
        for path in sorted(folder.glob("*")):
            if path.suffix in (".ico", ".icns", ".png") and hashlib.sha256(path.read_bytes()).hexdigest() in known:
                errors.append(f"{path.name} is the development placeholder; release builds need the signed-off artwork")
    return errors
