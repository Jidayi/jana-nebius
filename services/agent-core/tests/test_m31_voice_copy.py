"""Every reason or message key the voice code can show has student copy (VOC-14, VOC-16, UXS-34): no raw key."""

import json
import re

from jana_tools import REPO_ROOT

SOURCES = [
    "services/agent-core/agent_core/api/voice.py",
    "services/agent-core/agent_core/api/voice_adapter.py",
    "services/agent-core/agent_core/api/voice_activities.py",
    "services/agent-core/agent_core/engine/voice_bridge.py",
    "services/agent-core/agent_core/net/voice_launch.py",
    "packages/client-core/src/voice.ts",
    "packages/client-core/src/speech.ts",
    "packages/ui/src/voice/SpeechTools.tsx",
    "apps/desktop/src/VoiceBar.tsx",
    "apps/desktop/src/SpeechTools.tsx",
    "apps/desktop/src/VoiceSettings.tsx",
]
# Event and wire type names, not copy.
NOT_COPY = {"voice.state", "voice.caption", "voice.answer", "voice.ready", "voice.error"}


def emitted_keys():
    keys = set()
    for relative in SOURCES:
        text = (REPO_ROOT / relative).read_text()
        keys |= set(re.findall(r"""["'`](voice\.[a-z_]+(?:\.[a-z_]+)*)["'`]""", text))
    return keys - NOT_COPY


def test_every_voice_reason_the_code_can_emit_has_copy():
    catalogue = json.loads((REPO_ROOT / "packages/i18n/locales/en.json").read_text())
    keys = emitted_keys()
    # The reasons the review found shown raw, and the launch reasons the core maps (VOC-14).
    assert {"voice.disconnected", "voice.protocol_error", "voice.audio_backpressure", "voice.endpoint_error",
            "voice.endpoint_unavailable", "voice.stopped_working", "voice.pack_unavailable"} <= keys  # fmt: skip
    missing = sorted(key for key in keys if key not in catalogue)
    assert missing == []


def test_voc04_every_voice_state_has_a_label():
    from agent_core.engine.voice_bridge import VoiceBridge  # noqa: F401 -- the states live in the events contract

    catalogue = json.loads((REPO_ROOT / "packages/i18n/locales/en.json").read_text())
    schema = json.loads((REPO_ROOT / "services/agent-core/agent_core/contracts/schemas/api/events.schema.json")
                        .read_text())  # fmt: skip
    states = set(re.findall(r'"(idle|listening|thinking|speaking|interrupted|unavailable)"', json.dumps(schema)))
    assert states and all(f"voice.state.{state}" in catalogue for state in states)


def test_launch_reasons_the_socket_reports_have_copy():
    from agent_core.api.voice import LAUNCH_REASONS

    catalogue = json.loads((REPO_ROOT / "packages/i18n/locales/en.json").read_text())
    assert all(reason in catalogue for reason in LAUNCH_REASONS.values())
