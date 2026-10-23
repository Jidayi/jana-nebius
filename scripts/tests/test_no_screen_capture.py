"""PRV-29 shipping source audit plus seeded API/permission controls; compiled bundles remain external."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from jana_tools import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts/ci/no-screen-capture.mjs"


def node() -> str:
    return os.environ.get("JANA_NODE", shutil.which("node") or "node")


def prv29_no_screen_capture() -> None:
    result = subprocess.run([node(), str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    audit = json.loads(result.stdout)
    assert audit["files"] > 300 and audit["failures"] == []
    assert set(audit["roots"]) == {
        "apps/desktop/src",
        "apps/desktop/src-tauri",
        "services/agent-core/agent_core",
        "packages/client-core/src",
        "packages/ui/src",
    }


def test_screen_capture_audit_detects_seeded_interfaces_and_allows_photo_events() -> None:
    forbidden = [
        "navigator.mediaDevices.getDisplayMedia({video:true})",
        "navigator['clipboard']['read'+'Text']()",
        "const clip = navigator.clipboard; clip.read()",
        "const take = navigator.mediaDevices.getDisplayMedia; take()",
        "const {readText: read} = navigator.clipboard; read()",
        "navigator.clipboard.readText.bind(navigator.clipboard)()",
        "navigator.mediaDevices.getUserMedia({video:{mediaSource:'screen'}})",
        '<rescap:Capability Name="graphicsCapture"/>',
        "desktopCapturer.getSources({types:['window']})",
        "webContents.capturePage()",
        "CGWindowListCreateImage(0,0,0,0)",
        "SCStream(config)",
        "Windows.Graphics.Capture.GraphicsCaptureItem",
        "from PIL.ImageGrab import grab",
        "import mss as photo",
        'Command::new("screencapture")',
        'Command::new("pbpaste")',
        "<key>com.apple.security.screen-capture</key><true/>",
        "<key>com.apple.security.accessibility</key><true/>",
        '"clipboard-manager:allow-read-text"',
        "screenshots = '1'",
        'invoke("capture_window")',
    ]
    allowed = [
        "navigator.mediaDevices.getUserMedia({video:true})",
        "navigator.clipboard.writeText(text)",
        "function onPaste(event) { return event.clipboardData.getData('text/plain') }",
        "canvas.getContext('2d').drawImage(video,0,0)",
        "<key>com.apple.security.device.camera</key><true/>",
    ]
    data = [{"path": f"probe{i}.tsx", "source": source} for i, source in enumerate(forbidden + allowed)]
    result = subprocess.run(
        [node(), str(SCRIPT), "--probe"],
        input=json.dumps(data),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    failures = {row["path"] for row in json.loads(result.stdout)["failures"]}
    assert failures == {f"probe{i}.tsx" for i in range(len(forbidden))}
