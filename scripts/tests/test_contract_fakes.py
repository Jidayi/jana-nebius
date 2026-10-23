"""The contract fakes (M1.a): contract-valid by construction, and usable over their real transports."""

import copy
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from agent_core.contracts import ContractViolationError
from jana_tools.fakes import FakeToolWorker, ScriptedEventSource, ScriptedModelProvider
from jana_tools.fixtures import CORPUS

SCRIPTS = CORPUS / "scripts"


def test_scripted_event_source_serves_valid_sse_over_loopback():
    source = ScriptedEventSource.from_file(SCRIPTS / "stream_guided_turn.json")
    url = source.serve()
    try:
        assert url.startswith("http://127.0.0.1:")
        request = urllib.request.Request(url, headers={"Last-Event-ID": "5"})  # noqa: S310 (loopback test server)
        body = urllib.request.urlopen(request, timeout=5).read().decode()  # noqa: S310 (loopback test server)
    finally:
        source.close()
    frames = [f for f in body.split("\n\n") if f]
    assert [f.splitlines()[0] for f in frames] == ["id: 6", "id: 7"]
    assert json.loads(frames[-1].splitlines()[2].removeprefix("data: "))["event"]["type"] == "turn.end"


def test_scripted_event_source_rejects_invalid_or_unordered_streams():
    envelopes = json.loads((SCRIPTS / "stream_guided_turn.json").read_text())["envelopes"]
    broken = copy.deepcopy(envelopes)
    broken[2]["event"]["kind"] = "hologram"
    with pytest.raises(ContractViolationError):
        ScriptedEventSource(broken)
    unordered = copy.deepcopy(envelopes)
    unordered[3]["seq"] = 1
    with pytest.raises(ValueError, match="not increasing"):
        ScriptedEventSource(unordered)


def test_fake_tool_worker_over_stdio():
    lines = [
        {"jsonrpc": "2.0", "id": "1", "method": "worker.hello",
         "params": {"protocol": {"major": 1, "minor": 0}, "host_version": "0.0.0", "placement": "device"}},
        {"jsonrpc": "2.0", "id": "2", "method": "worker.ping", "params": {}},
        {"jsonrpc": "2.0", "id": "3", "method": "worker.shutdown", "params": {}},
    ]  # fmt: skip
    proc = subprocess.run(
        [sys.executable, "-m", "jana_tools.fakes.worker", str(SCRIPTS / "worker_session.json")],
        input="".join(json.dumps(line) + "\n" for line in lines), capture_output=True, text=True, timeout=30,
        check=True,
    )  # fmt: skip
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in replies] == ["1", "2", "3"]
    assert replies[0]["result"]["kind"] == "hello" and replies[1]["result"]["kind"] == "pong"


def test_fake_tool_worker_rejects_off_contract_requests():
    worker = FakeToolWorker.from_file(SCRIPTS / "worker_session.json")
    with pytest.raises(ContractViolationError):
        worker.handle({"jsonrpc": "2.0", "id": 7, "method": "worker.ping", "params": {}})  # id must be a string
    unknown = worker.handle({"jsonrpc": "2.0", "id": "8", "method": "fn.cancel", "params": {"call_id": "c1"}})
    assert unknown["error"]["code"] == -32601


def test_scripted_model_provider():
    provider = ScriptedModelProvider.from_file(SCRIPTS / "provider_guided_turn.json")
    coach = provider.complete({"role": "coach", "messages": []})
    assert coach["contract"] == "agents/tutor-turn" and json.loads(coach["content"])
    assert provider.complete({"role": "reflector"})["contract"] is None
    with pytest.raises(LookupError):
        provider.complete({"role": "coach"})
    bad = json.loads((SCRIPTS / "provider_guided_turn.json").read_text())["replies"]
    bad[0]["json"]["__unknown__"] = 1
    with pytest.raises(ContractViolationError):
        ScriptedModelProvider(bad)


def test_scripts_are_synthetic():
    for path in Path(SCRIPTS).glob("*.json"):
        assert "ynthetic" in json.loads(path.read_text())["description"]
