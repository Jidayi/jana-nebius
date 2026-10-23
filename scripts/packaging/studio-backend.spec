# Internal Studio only. The learner application never includes this executable, authoring tools or assets.
# Production previews and evaluations dynamically load engine roles, schemas and worker functions, so those
# packages' submodules and package data are explicit. Signing service and test/reference libraries are excluded.
# ruff: noqa
from pathlib import Path
import hashlib
import json
import os
import subprocess
import importlib.metadata
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
PACK = ROOT / 'services/pack-builder'
paths = [str(ROOT/'services'/p) for p in ('pack-builder', 'agent-core', 'tool-worker')] + [str(ROOT/'scripts')]
datas = []
for package in ('agent_core', 'tool_worker', 'pack_builder', 'jana_tools'):
    datas += collect_data_files(package, includes=['**/*.json', '**/*.yaml', '**/*.sql', '**/*.lark', '**/*.md', '**/*.txt', '**/*.mjs'])
for directory in ('content/agent', 'evals/personas', 'docs/specification/registers'):
    for path in (ROOT/directory).rglob('*'):
        if path.is_file():
            datas.append((str(path), str(Path('authoring-data')/path.parent.relative_to(ROOT))))
datas += [(str(ROOT/'spec.lock'), 'authoring-data'), (str(ROOT/'uv.lock'), 'authoring-data')]
node = Path(os.environ['JANA_STUDIO_NODE']).resolve(strict=True)
node_license = Path(os.environ['JANA_STUDIO_NODE_LICENSE']).resolve(strict=True)
katex = (ROOT/'packages/ui/node_modules/katex').resolve(strict=True)
for name in ('package.json', 'LICENSE', 'dist/katex.js'):
    item = katex/name
    datas.append((str(item), str(Path('authoring-data/node_modules/katex')/Path(name).parent)))
datas += [(str(ROOT/'packages/ui/package.json'), 'authoring-data'),
          (str(node_license), 'authoring-data/legal/node')]
metadata = ROOT/'dist/studio-runtime-inputs.json'
metadata.parent.mkdir(parents=True, exist_ok=True)
metadata.write_text(json.dumps({'node_version': subprocess.check_output([str(node), '--version'], text=True).strip(),
    'node_input_sha256': hashlib.sha256(node.read_bytes()).hexdigest(),
    'node_licence_sha256': hashlib.sha256(node_license.read_bytes()).hexdigest(),
    'katex_version': json.loads((katex/'package.json').read_text())['version'],
    'katex_js_sha256': hashlib.sha256((katex/'dist/katex.js').read_bytes()).hexdigest()}, indent=2)+'\n')
datas.append((str(metadata), 'authoring-data'))
for name in ('LICENSE', 'THIRD_PARTY_NOTICES'):
    datas.append((str(ROOT/name), 'authoring-data/legal/jana'))
installer = importlib.metadata.distribution('pyinstaller')
for entry in installer.files or []:
    if entry.name == 'COPYING.txt':
        datas.append((str(installer.locate_file(entry)), 'authoring-data/legal/pyinstaller'))
hidden = []
for package in ('pack_builder', 'agent_core', 'tool_worker'):
    hidden += collect_submodules(package)
hidden += ['jana_tools.skills', 'jana_tools.skill_evals', 'jana_tools.harness.simulator']
a = Analysis([str(PACK/'pack_builder/studio.py')], pathex=paths, datas=datas, binaries=[(str(node), 'authoring-data/node')],
    hiddenimports=hidden, excludes=['tkinter', 'IPython', 'pytest', 'matplotlib', 'sklearn', 'pyBKT', 'fsrs',
                                   'signing_service', 'cloud_gateway', 'ingest', 'pip', 'mypy', 'hypothesis', 'datamodel_code_generator', 'black'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='studio-backend', console=True, strip=False, upx=False)
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='studio-backend')
