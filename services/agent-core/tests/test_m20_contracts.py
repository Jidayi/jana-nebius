"""The shapes the M20 packaging code produces validate against the bundled contracts (D85 adopted the proposal):
control download frames, model pack and update manifests, revocation lists and crash reports. Every document here is
synthetic."""

from __future__ import annotations

from pathlib import Path

from agent_core.contracts import errors as contract_errors
from agent_core.net.crash_reports import build_report
from agent_core.store.updates import Platform, update_manifest
from m20_fixtures import SIGNED_AT, model_pack
from signing_service.hierarchy import dev_signer
from signing_service.keys import Purpose
from signing_service.revocation import dev_revocation_list


def test_m20_contracts_validate_what_the_code_writes(tmp_path: Path) -> None:
    frame = {"type": "control.download", "download_id": "dl_" + "0" * 26,
             "item": {"kind": "model_pack", "id": "mp.synth.8b.q4_k_m.low"},
             "files": [{"name": "model.gguf", "url": "https://downloads.dev.jana.invalid/m/model.gguf",
                        "size_bytes": 10, "sha256": "a" * 64, "chunk_sha256": ["a" * 64], "chunk_bytes": None}],
             "target": str(tmp_path / "incoming")}  # fmt: skip
    assert contract_errors("control/control#/$defs/ToShell", frame) == []
    state = {"type": "control.download_state", "download_id": "dl_" + "0" * 26, "state": "waiting_for_network",
             "bytes_done": 5, "bytes_total": 10, "eta_s": None, "error_code": "waiting_for_network"}  # fmt: skip
    assert contract_errors("control/control#/$defs/ToCore", state) == []
    hello = {"type": "control.hello", "protocol": {"major": 1, "minor": 0}}
    assert contract_errors("control/control#/$defs/ToCore", hello) == []

    manifest = model_pack(tmp_path / "mp.synth.8b.q4_k_m.low")
    assert contract_errors("ops/model-pack", manifest) == []
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"synthetic installer")
    platform = Platform("windows", "x86_64")
    unsigned = update_manifest("1.1.0", "stable", platform, installer, ["update.changes.fixes"], SIGNED_AT,
                               dev_revocation_list())  # fmt: skip
    update = dev_signer(Purpose.UPDATER).sign("offline_update_pack", unsigned, now=SIGNED_AT)
    assert contract_errors("ops/update-manifest", update) == []
    listing = dev_revocation_list(2, [{"key_id": "key_dev_x", "revoked_at": SIGNED_AT, "reason": "key_compromise"}])
    assert contract_errors("ops/revocation-list", listing) == []

    record = {"crash_id": "01JCRASH0000000000000000001", "process": "core", "kind": "exception", "version": "1.0.0",
              "error_type": "RuntimeError", "stack": [{"file": "x.py", "line": 1, "function": "f"}],
              "log_tail": ["line"], "detail": {}, "at_ms": 1_800_000_000_000}  # fmt: skip
    assert contract_errors("api/commands#/$defs/CrashReportList", {"reports": [build_report(record, "low")]}) == []

    export = {"kind": "diagnostic_bundle", "profile_ids": ["prf_" + "0" * 26], "include_session_ids": ["ses_1"],
              "destination": {"kind": "file", "path": str(tmp_path)}}  # fmt: skip
    assert contract_errors("api/commands#/$defs/CreateExport", export) != [], "a conversation needs a passphrase"
    sealed = {**export, "passphrase": "a long synthetic passphrase"}
    assert contract_errors("api/commands#/$defs/CreateExport", sealed) == []
