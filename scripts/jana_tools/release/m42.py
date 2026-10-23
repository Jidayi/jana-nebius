"""M42 production preflight and offline DPIA signing handoff. Never manufactures approval or signatures.

Run `python -m jana_tools.release.m42 --help` with the workspace environment. All evidence is hash-bound to
files supplied by the release operator; a successful preflight is a consistency check, not a specialist review.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_core.config.environments import Environment
from agent_core.config.trust import TrustStore, canonical_bytes, unsigned_bytes
from agent_core.net.dpia import verify
from cloud_gateway.config import load_config
from cloud_gateway.providers.vertex import vertex_scope

from .dpia import build_list, record_errors


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def write_new(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def evidence(base: Path, ref: Any, label: str, errors: list[str]) -> Any:
    if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
        errors.append(f"{label}: missing path and SHA-256")
        return {}
    path = base / ref["path"]
    if not path.is_file() or sha(path) != ref["sha256"]:
        errors.append(f"{label}: file absent or SHA-256 mismatch")
        return {}
    try:
        document = read(path)
        if not isinstance(document, dict):
            raise ValueError("expected an object")
        return document
    except (ValueError, UnicodeError):
        errors.append(f"{label}: expected a JSON evidence record")
        return {}


def preflight(manifest_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    manifest = read(manifest_path)
    base = manifest_path.parent
    errors: list[str] = []
    moment = now or datetime.now(UTC)
    refs = manifest.get("evidence", {})
    if manifest.get("version") != 1:
        errors.append("manifest: unsupported version")
    config_ref = refs.get("gateway_config", {})
    config_path = base / str(config_ref.get("path", "missing"))
    config = None
    provider_endpoint = None
    provider_scope = None
    if not config_path.is_file() or sha(config_path) != config_ref.get("sha256"):
        errors.append("gateway_config: file absent or SHA-256 mismatch")
    else:
        try:
            config = load_config(config_path)
        except (ValueError, OSError) as error:
            errors.append("gateway_config: invalid configuration: " + type(error).__name__)
    origin = manifest.get("gateway_origin", "")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.endswith(".invalid")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        errors.append("gateway_origin: real HTTPS origin required")
    for field in ("hosting_environment", "region", "image_digest", "signing_key_reference"):
        if not manifest.get(field) or str(manifest[field]).startswith(("REQUIRED", "TODO")):
            errors.append(f"{field}: actual deployment value required")
    if (
        not str(manifest.get("image_digest", "")).startswith("sha256:")
        or len(str(manifest.get("image_digest", ""))) != 71
    ):
        errors.append("image_digest: immutable SHA-256 image reference required")
    if config:
        if config.environment != "production" or config.audience_host != parsed.hostname:
            errors.append("gateway_config: environment/audience does not match production origin")
        if config.open_registration or not config.entitlement_keys:
            errors.append("gateway_config: closed signed-entitlement registration required")
        if not config.secrets_dir or not config.secrets_dir.is_absolute():
            errors.append("gateway_config: absolute secret-manager mount required")
        provider_slot, alias = config.study_model.split("/")
        provider = config.providers[config.slots[provider_slot]]
        model = provider.models[alias].id
        if model != "gemini-3.8-flash":
            errors.append("gateway_config: approved M42 model is Gemini 3.8 Flash")
        provider_endpoint = provider.base_url
        if provider.adapter == "vertex":
            try:
                provider_scope = vertex_scope(provider_endpoint)
            except ValueError:
                errors.append("gateway_config: invalid Vertex project/location endpoint")
        elif provider.adapter != "gemini" or provider_endpoint != "https://generativelanguage.googleapis.com/v1beta":
            errors.append("gateway_config: unqualified M42 provider endpoint")
        if config.study_worker_command:
            errors.append("gateway_config: use bundled fail-closed sandbox, not an unreviewed command override")
    policy = evidence(base, refs.get("network_policy"), "network_policy", errors)
    if policy.get("services", {}).get("production", {}).get("gateway") != parsed.hostname:
        errors.append("network_policy: production gateway host mismatch")
    pins = policy.get("pins", {}).get("production", [])
    try:
        pins_valid = len(set(pins)) >= 2 and all(len(base64.b64decode(p, validate=True)) == 32 for p in pins)
    except (ValueError, TypeError):
        pins_valid = False
    if not pins_valid:
        errors.append("network_policy: distinct valid primary and backup SPKI SHA-256 pins required")
    anchors = evidence(base, refs.get("trust_anchors"), "trust_anchors", errors)
    signed_list = evidence(base, refs.get("dpia_list"), "dpia_list", errors)
    try:
        trust = TrustStore.from_document(anchors)
        result = verify(signed_list, Environment.PRODUCTION, trust)
        if result.problem or "study_materials" not in result.features:
            errors.append("dpia_list: production signature and explicit study_materials approval required")
    except (ValueError, KeyError, TypeError):
        errors.append("trust_anchors: invalid production public hierarchy")
    retention = evidence(base, refs.get("provider_retention"), "provider_retention", errors)
    if (
        provider_endpoint is None
        or retention.get("provider_endpoint") != provider_endpoint
        or retention.get("model") != "gemini-3.8-flash"
        or not retention.get("project_reference")
        or retention.get("paid_service") is not True
        or retention.get("zero_data_retention_verified") is not True
        or retention.get("request_logging_disabled") is not True
        or not retention.get("verified_by")
        or not retention.get("provider_confirmation_reference")
    ):
        errors.append("provider_retention: verified paid project, ZDR and logging configuration evidence required")
    if provider_scope and (
        retention.get("project_reference") != provider_scope[0]
        or retention.get("location") != provider_scope[1]
        or retention.get("adapter") != "vertex"
    ):
        errors.append("provider_retention: exact Vertex adapter, project and location binding required")
    try:
        if datetime.fromisoformat(retention["valid_until"].replace("Z", "+00:00")) <= moment:
            errors.append("provider_retention: verification expired")
    except (KeyError, ValueError, TypeError):
        errors.append("provider_retention: valid_until timestamp required")
    cost = evidence(base, refs.get("measured_costs"), "measured_costs", errors)
    try:
        if datetime.fromisoformat(cost["valid_until"].replace("Z", "+00:00")) <= moment:
            errors.append("measured_costs: prices or measurements expired")
    except (KeyError, ValueError, TypeError):
        errors.append("measured_costs: valid_until timestamp required")
    if config:
        expected = {
            "page_usd": config.study_extract_page_usd,
            "minute_usd": config.study_extract_minute_usd,
            "prices": config.prices[model].model_dump(),
        }
        if cost.get("configured") != expected or not cost.get("measurement_reference") or not cost.get("reviewer"):
            errors.append("measured_costs: actual measured extraction costs and current token prices must match config")
        if expected["prices"] in (
            {"input": 0.75, "cached_input": 0.075, "output": 3.75},
            {"input": 0.825, "cached_input": 0.0825, "output": 4.125},
        ):
            try:
                if datetime.fromisoformat(cost["valid_until"].replace("Z", "+00:00")) > datetime(
                    2027, 1, 1, tzinfo=UTC
                ):
                    errors.append("measured_costs: introductory prices cannot be approved beyond 2026-12-31")
            except (KeyError, TypeError, ValueError):
                pass  # already reported above
    deployment = evidence(base, refs.get("deployment_checks"), "deployment_checks", errors)
    for key in (
        "no_swap",
        "core_dumps_disabled",
        "temporary_memory_only",
        "body_logs_disabled",
        "sandbox_network_denied",
        "secret_mount_outside_checkout",
        "secret_mount_read_only",
        "provider_egress_restricted",
        "runtime_identity_least_privilege",
        "linux_sandbox_smoke_passed",
    ):
        if deployment.get(key) is not True:
            errors.append(f"deployment_checks: {key} not verified")
    if deployment.get("image_digest") != manifest.get("image_digest"):
        errors.append("deployment_checks: image digest mismatch")
    native = evidence(base, refs.get("native_distribution"), "native_distribution", errors)
    if (
        native.get("image_digest") != manifest.get("image_digest")
        or not native.get("sbom_sha256")
        or not native.get("source_build_offer_reference")
        or native.get("licence_review_passed") is not True
    ):
        errors.append(
            "native_distribution: image-bound SBOM, licence review and PyAV/FFmpeg source/build offer required"
        )
    quality = evidence(base, refs.get("quality"), "quality", errors)
    corpus = evidence(base, refs.get("quality_corpus"), "quality_corpus", errors)
    expected_ids = {c.get("id") for c in corpus.get("cases", [])}
    actual_ids = [c.get("id") for c in quality.get("cases", [])]
    if (
        len(expected_ids) < 100
        or set(actual_ids) != expected_ids
        or len(actual_ids) != len(expected_ids)
        or quality.get("corpus_sha256") != refs.get("quality_corpus", {}).get("sha256")
        or quality.get("provider") not in ("real", "Vertex AI EU attached identity")
    ):
        errors.append("quality: exact full corpus, source digest and real-provider provenance required")
    if provider_scope and quality.get("provider_endpoint") != provider_endpoint:
        errors.append("quality: exact configured Vertex endpoint/project/location qualification required")
    if (
        quality.get("passed") is not True
        or quality.get("complete") is not True
        or quality.get("model") != "gemini-3.8-flash"
        or len(quality.get("cases", [])) < 100
        or any(c.get("passed") is not True for c in quality.get("cases", []))
    ):
        errors.append("quality: complete passing real-provider corpus required")
    review = evidence(base, refs.get("quality_review"), "quality_review", errors)
    for key in (
        "held_out_corpus_passed",
        "local_reference_model_passed",
        "content_review_passed",
        "safety_review_passed",
        "ocr_asr_review_passed",
    ):
        if review.get(key) is not True:
            errors.append(f"quality_review: {key} not verified")
    if review.get("quality_sha256") != refs.get("quality", {}).get("sha256") or not review.get("reviewers"):
        errors.append("quality_review: reviewers and exact quality report binding required")
    devices = evidence(base, refs.get("devices"), "devices", errors)
    for platform in ("macos-arm64", "windows-x86_64", "linux-x86_64"):
        row = devices.get("platforms", {}).get(platform, {})
        if row.get("passed") is not True or not row.get("artifact_sha256") or not row.get("measurement_reference"):
            errors.append(f"devices: packaged measurements missing for {platform}")
        if any(row.get("checks", {}).get(f"D{i:02}") is not True for i in range(1, 9)):
            errors.append(f"devices: D01-D08 not all measured for {platform}")
    for coverage in (
        "windows-10-22h2",
        "windows-11",
        "windows-non-avx2",
        "macos-13-plus",
        "ubuntu-22.04-plus",
        "debian-12",
    ):
        if devices.get("os_coverage", {}).get(coverage) is not True:
            errors.append(f"devices: required OS/CPU coverage missing: {coverage}")
    for hardware in ("content-only", "low", "mid", "high"):
        if devices.get("hardware_classes", {}).get(hardware) is not True:
            errors.append(f"devices: required hardware/model coverage missing: {hardware}")
    for at in ("voiceover", "nvda"):
        if devices.get("assistive_technology", {}).get(at, {}).get("passed") is not True:
            errors.append(f"devices: native {at} checks missing")
    return {
        "manifest_sha256": sha(manifest_path),
        "checked_at": moment.isoformat(),
        "ready": not errors,
        "errors": errors,
        "meaning": "Evidence consistency; not a fabricated measurement or signature.",
    }


def prepare_signing(records_path: Path, documents: Path, out: Path, created_at: str) -> dict[str, Any]:
    moment = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise ValueError("created_at must be an actual UTC timestamp")
    records = read(records_path)
    problems = [p for r in records for p in record_errors(r, documents)]
    if not any("study_materials" in r.get("features", []) for r in records):
        problems.append("PRV-08: missing actual study_materials DPIA record")
    if problems:
        raise ValueError("; ".join(problems))
    payload = build_list(records, created_at=created_at)
    request = {
        "artefact": "dpia_list",
        "purpose": "content",
        "environment": "production",
        "payload_sha256": hashlib.sha256(unsigned_bytes(payload)).hexdigest(),
        "records_sha256": sha(records_path),
        "assessment_sha256": {r["assessment_ref"]: r["assessment_sha256"] for r in records},
        "status": "unsigned; use existing production_signer with the content HSM key",
    }
    out.mkdir(parents=True, exist_ok=False)
    write_new(out / "dpia-list.unsigned.json", payload)
    (out / "dpia-list.canonical.json").write_bytes(canonical_bytes(payload))
    write_new(out / "signing-request.json", request)
    return request


def verify_return(request_path: Path, unsigned_path: Path, signed_path: Path, anchors_path: Path) -> None:
    request, unsigned, signed = read(request_path), read(unsigned_path), read(signed_path)
    if (
        request.get("artefact") != "dpia_list"
        or request.get("purpose") != "content"
        or request.get("environment") != "production"
    ):
        raise ValueError("unexpected signing purpose")
    expected = request.get("payload_sha256")
    if any(hashlib.sha256(unsigned_bytes(d)).hexdigest() != expected for d in (unsigned, signed)):
        raise ValueError("returned payload differs from reviewed signing request")
    trust = TrustStore.from_document(read(anchors_path))
    verified = verify(signed, Environment.PRODUCTION, trust)
    if verified.problem or "study_materials" not in verified.features:
        raise ValueError("production signature refused: " + str(verified.problem or "missing study_materials"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--report", type=Path, required=True)
    prep = commands.add_parser("prepare-signing")
    prep.add_argument("--records", type=Path, required=True)
    prep.add_argument("--documents", type=Path, required=True)
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--created-at", required=True)
    returned = commands.add_parser("verify-return")
    for name in ("request", "unsigned", "signed", "anchors"):
        returned.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            report = preflight(args.manifest)
            write_new(args.report, report)
            print(
                f"M42 production preflight: {'PASS' if report['ready'] else 'BLOCKED'} ({len(report['errors'])} gaps)"
            )
            return 0 if report["ready"] else 1
        if args.command == "prepare-signing":
            prepare_signing(args.records, args.documents, args.out, args.created_at)
        else:
            verify_return(args.request, args.unsigned, args.signed, args.anchors)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"M42 release preparation refused: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
