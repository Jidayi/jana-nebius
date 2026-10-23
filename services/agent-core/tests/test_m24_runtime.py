"""Execution-boundary regressions for OPS-10/11/28/29. Synthetic inputs only."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from agent_core.assets.skills import SkillSet
from agent_core.config import Environment
from agent_core.config.operations import DevicePolicy
from agent_core.engine.operations import install_operations, presented_content
from agent_core.store.pack_index import PackIndex
from agent_core.tools.executor import ToolCall
from agent_core.tools.spec import SessionCtx
from engine_harness import close, make_engine
from signing_service.hierarchy import dev_signer, dev_trust

AT = "2026-10-16T00:00:00Z"


def restrict(policy, entries, sequence=1):
    doc = {
        "sequence": sequence,
        "channel": "stable",
        "issued_at": AT,
        "entries": [
            {
                "entry_id": f"drill-{kind}-{target}",
                "target_kind": kind,
                "target": target,
                "action": action,
                "reason_code": "synthetic",
                "incident_id": "inc_synthetic",
                "lift_when": None,
            }
            for kind, target, action in entries
        ],
    }
    assert policy.adopt_safety(dev_signer().sign("safety_configuration", doc, now=AT))


def test_ops_runtime_keeps_turn_snapshot_and_denies_tool(tmp_path: Path):
    async def run():
        engine, _ = await make_engine(tmp_path, {}, worker=False)
        policy = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())
        try:
            runtime = install_operations(engine, policy, lambda: {})
            engine._begin("ask")
            restrict(policy, [("tool", "skill", "disable"), ("router_candidate", "local:qwen3-vl-8b", "disable")])
            assert not runtime.blocked("tool", "skill")
            engine._begin("ask")
            assert runtime.blocked("tool", "skill")
            reply = await engine.deps.executor.run_one(ToolCall("call_ops_1", "skill", {}), "coach", SessionCtx())
            assert reply["status"] == "error" and reply["error"]["code"] == "policy_denied"
            _, candidates, dropped = await engine.deps.router.candidates("coach")
            assert all(str(c) != "local:qwen3-vl-8b" for c in candidates)
            assert dropped["local:qwen3-vl-8b"] == "safety restriction"
        finally:
            await close(engine)

    asyncio.run(run())


def ops28_skill_pin_previous(tmp_path: Path):
    async def run():
        engine, _ = await make_engine(tmp_path, {}, worker=False)
        policy = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())
        try:
            current = next(iter(engine.deps.assets.skills.skills.values()))
            newer = replace(
                current,
                meta={**current.meta, "version": "2.0.0"},
                body=current.body + "\nSynthetic current-only fragment.",
            )
            previous = replace(current, meta={**current.meta, "version": "1.0.0", "status": "reviewed"})
            engine.deps.assets = replace(engine.deps.assets, skills=SkillSet({current.name: newer}))
            install_operations(engine, policy, lambda: {}, previous_skills=SkillSet({current.name: previous}))
            restrict(policy, [("skill", current.name, "pin_previous")])
            turn = engine._begin("ask")
            selected = engine.deps.assets.skills.skills[current.name]
            assert selected.version == "1.0.0" and selected.sha256 == previous.sha256
            assert engine.deps.assets.skills.manifest()[0]["sha256"] == previous.sha256
            from agent_core.tools.spec import CallContext

            role = previous.meta["roles"][0]
            delivered = await engine._skill(
                {"skill_name": current.name}, CallContext("call_ops_1", SessionCtx(role=role))
            )
            assert delivered["content"] and delivered["sha256"] == previous.sha256
            assert "Synthetic current-only fragment." not in delivered["content"]
            assert selected.sha256 != newer.sha256
            assert turn.trace.skills[-1]["version"] == "1.0.0"
            assert turn.trace.skills[-1]["sha256"] == previous.sha256
        finally:
            await close(engine)

    asyncio.run(run())


def test_ops_presented_records_do_not_change_historical_index(tmp_path: Path):
    policy = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())
    restrict(policy, [("item", "itm.old", "withdraw"), ("lesson", "les.old", "withdraw")])
    policy.turn_boundary({})
    original = PackIndex(
        records={
            "items": {"itm.old": {"id": "itm.old"}, "itm.ok": {"id": "itm.ok"}},
            "lessons": {"les.old": {"id": "les.old"}},
        }
    )
    presented = presented_content(original, policy)
    assert presented.record("items", "itm.old") is None and presented.record("lessons", "les.old") is None
    assert presented.record("items", "itm.ok")
    assert original.record("items", "itm.old") == {"id": "itm.old"}


def test_ops_gateway_role_is_metadata_only():
    from agent_core.providers.base import Message
    from agent_core.providers.gateway import GatewayProvider

    async def run():
        provider = GatewayProvider(None, lambda: "gateway.invalid", "primary")
        body, headers, _ = await provider._prepare(
            "fast-model", [Message("user", "synthetic")], [], {"role": "coach"}, stream=False
        )
        assert headers["x-jana-role"] == "coach"
        assert "role" not in body
        _, headers, _ = await provider._prepare(
            "fast-model", [Message("user", "synthetic")], [], {"role": "untrusted student name"}, stream=False
        )
        assert "x-jana-role" not in headers

    asyncio.run(run())


def test_ops_provider_unavailable_uses_immediate_local_fallback_reason():
    from agent_core.net.client import Response
    from agent_core.providers.gateway import GatewayProvider

    provider = GatewayProvider(None, lambda: "gateway.invalid", "primary")
    error = provider._failure(Response(503, {}, {"error": {"code": "provider_unavailable"}}))
    assert error.reason == "network_unavailable"


def ops29_withdraw_last_model(tmp_path: Path):
    async def run():
        engine, _ = await make_engine(tmp_path, {}, worker=False)
        policy = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())
        try:
            install_operations(engine, policy, lambda: {}, local_models=lambda: {"only_model"})
            restrict(policy, [("model_pack", "only_model", "disable")])
            engine._begin("ask")
            assert engine.state.hardware_class == "content_only"
            assert engine.deps.router.hardware_class == "content_only"
        finally:
            await close(engine)

    asyncio.run(run())
