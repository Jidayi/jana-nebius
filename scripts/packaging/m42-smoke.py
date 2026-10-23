"""Verify the frozen M42 document worker and native notices; never treats this as installer/signing approval."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path

from agent_core.config import Settings
from agent_core.tools.worker.sandbox import PERCEPTION_PROFILE, perception_job_limits, sandboxed
from pypdf import PdfWriter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bundle", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
root = args.bundle.resolve()
exe = root / "agent-core"
review_path = Path(__file__).resolve().parents[1] / "governance/m42-pdfium-native-review.json"
review = json.loads(review_path.read_text())
writer = PdfWriter()
writer.add_blank_page(width=200, height=200)
pdf = io.BytesIO()
writer.write(pdf)
cases = []
with tempfile.TemporaryDirectory(prefix="jana-m42-frozen-") as directory:
    scratch = Path(directory).resolve()
    command = sandboxed(
        [str(exe), "--study-document-worker"],
        scratch,
        reads=[root],
        limits=perception_job_limits(Settings()),
        profile=PERCEPTION_PROFILE,
    )
    if command.reduced_protection:
        raise RuntimeError("The frozen worker requires the real native sandbox")
    for kind, raw, name in [
        ("document", b"Enzymes are biological catalysts.", "source.txt"),
        ("pdf", pdf.getvalue(), "source.pdf"),
        ("raster_pdf", pdf.getvalue(), "1"),
    ]:
        request = {"kind": kind, "data": base64.b64encode(raw).decode(), "name": name, "max_units": 30}
        result = subprocess.run(
            command.argv,
            input=json.dumps(request).encode() + b"\n",
            capture_output=True,
            timeout=60,
            cwd=scratch,
            check=True,
        )
        value = json.loads(result.stdout)
        if "units" not in value:
            raise RuntimeError(f"Frozen {kind} decoder refused: {value.get('error')}")
        if kind == "raster_pdf" and not base64.b64decode(value["units"][0]["png"]).startswith(b"\x89PNG"):
            raise RuntimeError("Frozen PDF raster is not a PNG")
        cases.append({"kind": kind, "units": len(value["units"]), "passed": True})
legal = root / "_internal/legal/pypdfium2"
inventory = {str(p.relative_to(legal)) for p in legal.rglob("*") if p.is_file()}
platform = next(
    (
        p
        for p in review.get("platforms", [review])
        if {str(Path(f).relative_to("licenses")) for f in p["files"]} == inventory
    ),
    None,
)
if platform is None:
    raise RuntimeError("Packaged PDFium licence inventory does not match a reviewed platform")
for relative, digest in platform["files"].items():
    path = root / "_internal/legal/pypdfium2" / Path(relative).relative_to("licenses")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Packaged native licence differs: {relative}")
size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())
audio = any("libavcodec" in p.name or "libavformat" in p.name for p in root.rglob("*"))
if size > 90000000 or audio:
    raise RuntimeError("Core exceeds 90 MB or contains server-only recording decoder libraries")
report = {
    "release_signed": False,
    "signing": "development build; production signature not verified",
    "regular_bytes": size,
    "budget_decimal_bytes": 90000000,
    "cases": cases,
    "licence_files_checked": len(platform["files"]),
    "licence_file_hashes_match": True,
    "server_audio_libraries_excluded": not audio,
    "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
}
args.report.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, sort_keys=True))
