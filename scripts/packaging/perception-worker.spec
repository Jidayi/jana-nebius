# Fixed, separate M21 worker: no learner store or agent modules in its bundle.
# ruff: noqa
import hashlib
import json
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
ROOT = Path(SPECPATH).resolve().parents[1]
WORKER = ROOT / "services" / "perception-worker"
package = WORKER / "perception_worker"
asset = Path(os.environ.get("JANA_OCR_DATA_FILE", ""))
expected = json.loads((package / "ocr-assets.json").read_text())["eng.traineddata"]["sha256"]
if asset.name != "eng.traineddata" or not asset.is_file() or hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
    raise SystemExit("Set JANA_OCR_DATA_FILE to the reviewed English traineddata matching ocr-assets.json; no model is downloaded by this build.")
datas = collect_data_files("perception_worker", includes=["*.json"])
datas += [(str(asset), "perception_worker/native/tessdata")]
datas += [(str(path), "legal/perception") for path in (WORKER / "licences").iterdir() if path.is_file()]
datas += collect_data_files("cv2", includes=["data/*.xml", "LICENSE*.txt"])
binaries = collect_dynamic_libs("cv2") + collect_dynamic_libs("tesserocr")
a = Analysis([str(package / "__main__.py")], pathex=[str(WORKER)], datas=datas, binaries=binaries,
             hiddenimports=collect_submodules("perception_worker"),
             excludes=["agent_core", "tool_worker", "tkinter", "IPython", "pytest", "matplotlib"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="perception-worker", console=True, strip=False, upx=False)
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="perception-worker")
