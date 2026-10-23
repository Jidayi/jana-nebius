# PyInstaller one-dir bundle of the tool worker (PLT-02: `resources/tool-worker/`, budget 80 MB; D36, SEC-07, SEC-09).
# Only the worker's locked dependency closure goes in; the modules jana_tools.worker_bundle.BUNDLE_EXCLUDES names (a
# console that runs code supplied at run time) are left out, and plt03_worker_bundle_inventory checks the result
# against the import allow-list. Run from the repository root:  pyinstaller scripts/packaging/tool-worker.spec
# ruff: noqa
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - SPECPATH is defined by PyInstaller
WORKER = ROOT / "services" / "tool-worker"
EXCLUDES = ["isympy", "tkinter", "IPython", "pytest", "matplotlib", "pip", "setuptools"]

a = Analysis(  # noqa: F821
    [str(WORKER / "tool_worker" / "__main__.py")],
    pathex=[str(WORKER)],
    datas=collect_data_files("tool_worker", includes=["**/*.json", "**/*.lark", "**/*.txt"]),
    hiddenimports=collect_submodules("tool_worker"),
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="tool-worker", console=True, strip=False, upx=False)  # noqa: F821
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="tool-worker")  # noqa: F821
