"""ARC-29 versioned contracts between processes, and API-35 older-client compatibility."""

import copy
import json
import tomllib
from pathlib import Path

from agent_core.contracts import errors
from agent_core.contracts._compat import Version, current, interfaces, negotiate, negotiate_api, parse, read_event

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "evals" / "contracts"
ARCHITECTURE = REPO / "docs" / "specification" / "architecture.md"


def _fixture(rel: str) -> dict:
    return json.loads((CORPUS / rel).read_text())


def _arc29_rows() -> int:
    return len(tomllib.loads((REPO / "scripts/jana_tools/codegen/versions.toml").read_text())["interfaces"])


def arc29_contract_compatibility_matrix():
    table = interfaces()
    assert len(table) == _arc29_rows(), "every interface of TABLE ARC-29a has a version and a mismatch action"

    # Each interface with a current, a previous-minor and a next-major peer.
    for name, spec in table.items():
        now = current(name)
        newer_self = Version(now.major, now.minor + 1)
        assert negotiate(name, now).ok
        assert negotiate(name, now, ours=newer_self).ok == (name != "control"), name
        next_major = negotiate(name, Version(now.major + 1, 0))
        assert (next_major.ok, next_major.action) == (False, spec["on_mismatch"]), name

    # The listed behaviour through real contract instances.
    meta = _fixture("api/commands/Meta/valid/minimal.json")
    meta["protocol"] = {"major": 1, "min_minor": 0, "max_minor": 3}
    assert errors("api/commands#/$defs/Meta", meta) == []
    assert negotiate_api(meta["protocol"], "1.0").ok and negotiate_api(meta["protocol"], "1.3").ok
    assert negotiate_api(meta["protocol"], "1.4").action == "upgrade_required"  # client newer than the core
    assert negotiate_api(meta["protocol"], "2.0").action == "upgrade_required"

    hello = _fixture("scripts/worker_session.json")["exchanges"][0]["result"]
    for protocol, action in (({"major": 1, "minor": 0}, None), ({"major": 1, "minor": 1}, None),
                             ({"major": 2, "minor": 0}, "worker_disabled")):  # fmt: skip
        hello["protocol"] = protocol
        assert errors("tools/worker-protocol#/$defs/HelloResult", hello) == []
        assert negotiate("worker", hello["protocol"]).action == action

    # The shell's control.hello (contracts/control, at 1.4, D97): an older minor or a next major refuses to start.
    for protocol, action in (
        ({"major": 1, "minor": 3}, "refuse_start"),
        ({"major": 1, "minor": 4}, None),
        ({"major": 2, "minor": 0}, "refuse_start"),
    ):
        control = {"type": "control.hello", "protocol": protocol}
        assert errors("control/control#/$defs/ToCore", control) == []
        assert negotiate("control", control["protocol"]).action == action

    trace = _fixture("trace/turn-trace/valid/minimal.json")
    for version, ok in (("1.0", True), ("1.7", True)):
        trace["trace_version"] = version
        assert errors("trace/turn-trace", trace) == []
        assert negotiate("trace", trace["trace_version"]).ok is ok
    assert negotiate("trace", "2.0").action == "export_upgrades_or_refuses"

    pack = _fixture("content/content-pack/valid/minimal.json")
    for version, action in (("1.2.0", None), ("2.0.0", "pack_skipped")):
        pack["manifest"]["schema_version"] = version
        assert errors("content/content-pack", pack) == []
        assert negotiate("content_pack", pack["manifest"]["schema_version"]).action == action

    assert parse({"major": 1, "minor": 5}) == Version(1, 5)  # personal-sync and LAN protocol objects


def _v13_stream() -> list[dict]:
    """The recorded stream as a v1.3 core might send it: additive changes only (a new envelope field, a new
    optional field on an event, a new event type)."""
    envelopes = copy.deepcopy(_fixture("scripts/stream_guided_turn.json")["envelopes"])
    for envelope in envelopes:
        envelope["trace_ref"] = "trc_example"
    envelopes[3]["event"]["emphasis"] = True
    glow = copy.deepcopy(envelopes[3])
    glow["seq"] = 100
    glow["event"] = {"type": "hint.glow", "part_id": envelopes[3]["event"]["part_id"], "level": 2}
    return [*envelopes[:4], glow, *envelopes[4:]]


def api35_older_client_compatible():
    """A v1.0 client against a v1.3 core: the version check passes and every recorded scenario stream is read
    in full (the scenario suite through the real core runs from M5)."""
    assert negotiate_api({"major": 1, "min_minor": 0, "max_minor": 3}, "1.0").ok

    stream = _v13_stream()
    outcomes = [read_event(envelope, newer_minor=True) for envelope in stream]
    assert [o[0] for o in outcomes] == ["accept"] * 4 + ["skip"] + ["accept"] * 3
    accepted = [o[1] for o in outcomes if o[0] == "accept"]
    original = _fixture("scripts/stream_guided_turn.json")["envelopes"]
    assert [a["event"]["type"] for a in accepted] == [e["event"]["type"] for e in original]
    assert "".join(a["event"].get("delta", "") for a in accepted) == "".join(
        e["event"].get("delta", "") for e in original
    )

    # Without the tolerant reader the same stream would be rejected, and non-additive changes still are.
    assert read_event(stream[0], newer_minor=False)[0] == "reject"
    broken = copy.deepcopy(stream[2])
    del broken["event"]["kind"]
    assert read_event(broken, newer_minor=True)[0] == "reject"


def test_sidecar_refuses_another_control_major():
    """The core answers a shell of another control-channel major with protocol_mismatch and exits (ARC-29)."""
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "agent_core.api"], input='{"type":"control.hello","protocol":'
                          '{"major":2,"minor":0}}\n', capture_output=True, text=True, timeout=60)  # fmt: skip
    reply = json.loads(proc.stdout.splitlines()[0])
    expected = {"major": 1, "minor": 4}  # the control channel's version (ARC-29; 1.4 since D97)
    assert reply == {"type": "control.error", "code": "protocol_mismatch", "expected_protocol": expected}
    assert errors("control/control#/$defs/ToShell", reply) == []
    assert proc.returncode != 0
