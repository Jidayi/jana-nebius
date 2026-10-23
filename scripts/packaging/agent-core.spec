# PyInstaller one-dir bundle of the agent core (PLT-02: `resources/agent-core/`, budget 90 MB; PLT-03, G44).
# Built by scripts/packaging/build-sidecars.sh from the locked uv environment; signed afterwards with every other
# executable (PLT-05). Run from the repository root:  pyinstaller scripts/packaging/agent-core.spec
# ruff: noqa
from pathlib import Path
from importlib.metadata import distribution

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - SPECPATH is defined by PyInstaller
CORE = ROOT / "services" / "agent-core"

datas = collect_data_files("agent_core", includes=["**/*.json", "**/*.yaml", "**/*.sql", "**/*.md", "**/*.txt"])
datas += collect_data_files("pypdfium2_raw")
# Keep every upstream PDFium/native-dependency notice from this platform's pinned wheel.
pdf_distribution = distribution("pypdfium2")
for relative in pdf_distribution.files or ():
    if ".dist-info/licenses/" in str(relative):
        parts = relative.parts
        destination = Path("legal/pypdfium2").joinpath(*parts[2:-1])
        datas.append((str(pdf_distribution.locate_file(relative)), str(destination)))
pdf_binaries = collect_dynamic_libs("pypdfium2_raw")
hidden = ["study_worker"] + collect_submodules("pypdfium2") + collect_submodules("pypdf") + collect_submodules("agent_core") + collect_submodules("uvicorn")

a = Analysis(  # noqa: F821
    [str(CORE / "agent_core" / "api" / "__main__.py")],
    pathex=[str(CORE)],
    datas=datas,
    binaries=pdf_binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "pytest", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="agent-core", console=True, strip=False, upx=False)  # noqa: F821
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="agent-core")  # noqa: F821
