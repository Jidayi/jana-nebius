"""Release preparation refuses stale evidence, invented approvals and untrusted signing returns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from agent_core.config.trust import Purpose
from jana_tools.release.m42 import preflight, prepare_signing, verify_return
from signing_service.hierarchy import anchors_document, dev_signer, dev_trust
from test_m25b_gates import dpia_record

ROOT = Path(__file__).resolve().parents[2]


def test_incomplete_production_template_fails_with_actionable_items():
    report = preflight(ROOT / "services/cloud-gateway/deploy/m42-release-manifest.example.json")
    assert not report["ready"]
    assert any("gateway_config" in p for p in report["errors"])
    assert any("backup SPKI" in p for p in report["errors"])
    assert any("provider_retention" in p for p in report["errors"])
    assert any("windows-x86_64" in p for p in report["errors"])
    assert any("native voiceover" in p for p in report["errors"])


def prep(tmp_path):
    record = dpia_record("s3_launch", ["study_materials"], tmp_path)
    records = tmp_path / "records.json"
    records.write_text(json.dumps([record]))
    out = tmp_path / "handoff"
    prepare_signing(records, tmp_path, out, "2026-10-18T00:00:00.000Z")
    return record, records, out


def test_signing_handoff_binds_canonical_bytes_and_preserves_real_assessment(tmp_path):
    record, records, out = prep(tmp_path)
    request = json.loads((out / "signing-request.json").read_text())
    assert request["payload_sha256"] == hashlib.sha256((out / "dpia-list.canonical.json").read_bytes()).hexdigest()
    assert request["records_sha256"] == hashlib.sha256(records.read_bytes()).hexdigest()
    assert request["assessment_sha256"] == {record["assessment_ref"]: record["assessment_sha256"]}
    assert "signature" not in json.loads((out / "dpia-list.unsigned.json").read_text())
    with pytest.raises(FileExistsError):
        prepare_signing(records, tmp_path, out, "2026-10-18T00:00:00.000Z")


def test_signing_preparation_refuses_changed_assessment(tmp_path):
    record, records, _out = prep(tmp_path)
    (tmp_path / record["assessment_ref"]).write_text("changed after approval")
    with pytest.raises(ValueError, match="differs from the signed record"):
        prepare_signing(records, tmp_path, tmp_path / "changed", "2026-10-18T00:00:00.000Z")


def test_owner_attestation_is_not_an_assessment_record(tmp_path):
    records = tmp_path / "records.json"
    records.write_text(json.dumps([json.loads((ROOT / "scripts/governance/m42-owner-approval.json").read_text())]))
    with pytest.raises(ValueError):
        prepare_signing(records, tmp_path, tmp_path / "handoff", "2026-10-18T00:00:00.000Z")


def test_signing_return_refuses_test_root_and_changed_payload(tmp_path):
    _, _, out = prep(tmp_path)
    unsigned = out / "dpia-list.unsigned.json"
    payload = json.loads(unsigned.read_text())
    signed = out / "signed.json"
    signed.write_text(json.dumps(dev_signer(Purpose.CONTENT).sign("dpia_list", payload)))
    anchors = out / "anchors.json"
    anchors.write_text(json.dumps(anchors_document([dev_trust()])))
    args = (out / "signing-request.json", unsigned, signed, anchors)
    with pytest.raises(ValueError, match="production signature refused"):
        verify_return(*args)
    payload["approved"][0]["dpia_id"] = "changed"
    signed.write_text(json.dumps(dev_signer(Purpose.CONTENT).sign("dpia_list", payload)))
    with pytest.raises(ValueError, match="differs from reviewed"):
        verify_return(*args)


def complete_manifest(folder):
    """Throwaway synthetic release hierarchy and records, never written outside pytest's temporary folder."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from signing_service.hierarchy import Signer, anchors_document, issue_certificate, public_b64, root_record

    root_key, content_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    root = root_record(
        "synthetic-release-root", public_b64(root_key), "release", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"
    )
    cert = issue_certificate(
        root,
        root_key.sign,
        "synthetic-content",
        Purpose.CONTENT,
        public_b64(content_key),
        root.not_before,
        root.not_after,
    )
    from agent_core.config.trust import TrustStore
    from cloud_gateway.config import load_config
    from jana_tools.release.dpia import build_list

    trust = TrustStore({root.key_id: root}, {cert.key_id: cert})
    manifest = {
        "version": 1,
        "gateway_origin": "https://gateway.example.com",
        "hosting_environment": "synthetic-test",
        "region": "synthetic-region",
        "image_digest": "sha256:" + "a" * 64,
        "signing_key_reference": "synthetic-content",
        "evidence": {},
    }

    def put(name, value):
        file = folder / (name + ".json")
        file.write_text(json.dumps(value))
        manifest["evidence"][name] = {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}

    config = folder / "gateway.toml"
    config.write_text(
        'environment="production"\naudience_host="gateway.example.com"\n'
        'secrets_dir="/run/credentials/test"\n[entitlement_keys]\n'
        'synthetic="' + public_b64(content_key) + '"\n'
    )
    manifest["evidence"]["gateway_config"] = {
        "path": config.name,
        "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    }
    put(
        "network_policy",
        {
            "services": {"production": {"gateway": "gateway.example.com"}},
            "pins": {"production": [base64.b64encode(bytes([n]) * 32).decode() for n in (1, 2)]},
        },
    )
    put("trust_anchors", anchors_document([trust]))
    put(
        "dpia_list",
        Signer(cert, content_key.sign).sign(
            "dpia_list",
            build_list([dpia_record("s3_launch", ["study_materials"], folder)], created_at="2026-10-18T00:00:00Z"),
            now="2026-10-18T00:00:00Z",
        ),
    )
    put(
        "provider_retention",
        {
            "provider_endpoint": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-3.8-flash",
            "project_reference": "synthetic",
            "paid_service": True,
            "zero_data_retention_verified": True,
            "request_logging_disabled": True,
            "verified_by": "synthetic",
            "provider_confirmation_reference": "synthetic",
            "valid_until": "2026-12-31T00:00:00Z",
        },
    )
    cfg = load_config(config)
    put(
        "measured_costs",
        {
            "configured": {
                "page_usd": cfg.study_extract_page_usd,
                "minute_usd": cfg.study_extract_minute_usd,
                "prices": cfg.prices["gemini-3.8-flash"].model_dump(),
            },
            "measurement_reference": "synthetic",
            "reviewer": "synthetic",
            "valid_until": "2026-12-31T00:00:00Z",
        },
    )
    checks = {
        k: True
        for k in (
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
        )
    }
    put("deployment_checks", {**checks, "image_digest": manifest["image_digest"]})
    put(
        "native_distribution",
        {
            "image_digest": manifest["image_digest"],
            "sbom_sha256": "b" * 64,
            "source_build_offer_reference": "synthetic",
            "licence_review_passed": True,
        },
    )
    put("quality_corpus", {"cases": [{"id": str(i)} for i in range(110)]})
    put(
        "quality",
        {
            "complete": True,
            "passed": True,
            "provider": "real",
            "model": "gemini-3.8-flash",
            "corpus_sha256": manifest["evidence"]["quality_corpus"]["sha256"],
            "cases": [{"id": str(i), "passed": True} for i in range(110)],
        },
    )
    put(
        "quality_review",
        {
            "quality_sha256": manifest["evidence"]["quality"]["sha256"],
            "reviewers": ["synthetic"],
            **{
                k: True
                for k in (
                    "held_out_corpus_passed",
                    "local_reference_model_passed",
                    "content_review_passed",
                    "safety_review_passed",
                    "ocr_asr_review_passed",
                )
            },
        },
    )
    devices = json.loads((ROOT / "scripts/packaging/m42-device-report.example.json").read_text())
    for platform in devices["platforms"].values():
        platform.update(passed=True, artifact_sha256="c" * 64, measurement_reference="synthetic")
        platform["checks"] = {k: True for k in platform["checks"]}
    for row in devices["assistive_technology"].values():
        row.update(passed=True, measurement_reference="synthetic")
    for field in ("os_coverage", "hardware_classes"):
        devices[field] = {k: True for k in devices[field]}
    put("devices", devices)
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest, put


def test_production_preflight_accepts_complete_synthetic_evidence_then_detects_tampering(tmp_path):
    path, manifest, _ = complete_manifest(tmp_path)
    report = preflight(path)
    assert report["ready"], report["errors"]
    (tmp_path / manifest["evidence"]["quality"]["path"]).write_text("{}")
    assert not preflight(path)["ready"]
    assert any("SHA-256 mismatch" in p for p in preflight(path)["errors"])


def test_production_preflight_refuses_expired_retention_and_introductory_price_overrun(tmp_path):
    path, manifest, put = complete_manifest(tmp_path)
    row = json.loads((tmp_path / "provider_retention.json").read_text())
    row["valid_until"] = "2020-01-01T00:00:00Z"
    put("provider_retention", row)
    row = json.loads((tmp_path / "measured_costs.json").read_text())
    row["valid_until"] = "2030-01-01T00:00:00Z"
    put("measured_costs", row)
    path.write_text(json.dumps(manifest))
    problems = preflight(path)["errors"]
    assert any("verification expired" in p for p in problems)
    assert any("introductory prices" in p for p in problems)


def vertex_manifest(tmp_path):
    path, manifest, put = complete_manifest(tmp_path)
    config = tmp_path / "gateway.toml"
    endpoint = "https://aiplatform.eu.rep.googleapis.com/v1/projects/jana-prod-512005/locations/eu/publishers/google"
    with config.open("a") as stream:
        stream.write(
            '\n[slots]\nprimary="vertex"\n[providers.vertex]\nadapter="vertex"\n'
            f'base_url="{endpoint}"\nsecret="unused_attached_identity"\n'
            '[providers.vertex.models.fast-model]\nid="gemini-3.8-flash"\n'
            "[tier]\ncalls_per_turn={fast-model=3.0}\n"
            '[prices."gemini-3.8-flash"]\ninput=0.825\ncached_input=0.0825\noutput=4.125\n'
        )
    manifest["evidence"]["gateway_config"]["sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    row = json.loads((tmp_path / "provider_retention.json").read_text())
    row.update(provider_endpoint=endpoint, adapter="vertex", project_reference="jana-prod-512005", location="eu")
    put("provider_retention", row)
    row = json.loads((tmp_path / "measured_costs.json").read_text())
    row["configured"]["prices"] = {"input": 0.825, "cached_input": 0.0825, "output": 4.125}
    put("measured_costs", row)
    row = json.loads((tmp_path / "quality.json").read_text())
    row.update(provider="Vertex AI EU attached identity", provider_endpoint=endpoint)
    put("quality", row)
    row = json.loads((tmp_path / "quality_review.json").read_text())
    row["quality_sha256"] = manifest["evidence"]["quality"]["sha256"]
    put("quality_review", row)
    path.write_text(json.dumps(manifest))
    return path, manifest, put


def test_vertex_preflight_binds_retention_to_exact_production_project_and_region(tmp_path):
    path, manifest, put = vertex_manifest(tmp_path)
    assert preflight(path)["ready"], preflight(path)["errors"]
    row = json.loads((tmp_path / "provider_retention.json").read_text())
    for key, value in [("project_reference", "jana-staging-512005"), ("location", "global"), ("adapter", "gemini")]:
        put("provider_retention", {**row, key: value})
        path.write_text(json.dumps(manifest))
        assert any("exact Vertex" in p for p in preflight(path)["errors"])
    put("provider_retention", {**row, "provider_endpoint": row["provider_endpoint"].replace("/eu/", "/us/")})
    path.write_text(json.dumps(manifest))
    assert any("verified paid project" in p for p in preflight(path)["errors"])


def test_vertex_eu_introductory_prices_also_expire_at_year_end(tmp_path):
    path, manifest, put = vertex_manifest(tmp_path)
    row = json.loads((tmp_path / "measured_costs.json").read_text())
    put("measured_costs", {**row, "valid_until": "2027-02-01T00:00:00Z"})
    path.write_text(json.dumps(manifest))
    assert any("introductory prices" in p for p in preflight(path)["errors"])


def test_vertex_production_preflight_refuses_staging_quality_provenance(tmp_path):
    path, manifest, put = vertex_manifest(tmp_path)
    row = json.loads((tmp_path / "quality.json").read_text())
    row["provider_endpoint"] = row["provider_endpoint"].replace("jana-prod-512005", "jana-staging-512005")
    put("quality", row)
    path.write_text(json.dumps(manifest))
    assert any("exact configured Vertex" in p for p in preflight(path)["errors"])


def test_all_41_canonical_acceptance_names_have_real_check_targets():
    import ast
    import re

    inventory = json.loads((ROOT / "evals/study/m42-acceptance.json").read_text())
    requirements = {row["requirement"] for row in inventory["cases"]}
    canonical = set()
    for path in (ROOT / "docs/specification").glob("*.md"):
        for section in re.split(r"(?=^### )", path.read_text(), flags=re.M):
            header = re.match(r"### ([A-Z]+-\d+)", section)
            if header and header[1] in requirements:
                canonical.update(re.findall(r"\(test:\s*`([^`]+)`", section))
    assert len(canonical) == inventory["required_count"] == 41
    assert {row["acceptance"] for row in inventory["cases"]} == canonical
    for row in inventory["cases"]:
        assert row["remaining"] and not row["acceptance_complete"]
        for selector in row["automated_checks"]:
            file, _, function = selector.partition("::")
            path = ROOT / file
            assert path.is_file(), selector
            if function:
                assert any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function
                    for n in ast.walk(ast.parse(path.read_text()))
                ), selector


def test_oracle_amendment_preserves_model_observations_and_cannot_erase_a_refusal():
    import copy

    from jana_tools.release.m42 import sha
    from jana_tools.release.m42_quality import reassess

    evidence = ROOT / "scripts/governance/evidence/m42-qualification-2026-10-18"
    original_path = evidence / "quality-repeat-raw.json"
    before_path = evidence / "corpus-v1.json"
    after_path = ROOT / "evals/study/history/m42-quality-v2.json"
    original, before, after = [json.loads(p.read_text()) for p in (original_path, before_path, after_path)]
    bindings = dict(before_sha=sha(before_path), after_sha=sha(after_path), report_sha=sha(original_path))
    result = reassess(original, before, after, **bindings)
    assert result["passed"] and all(c["passed"] for c in result["cases"])
    assert result["cases"] != original["cases"] and not original["passed"]
    changed = copy.deepcopy(original)
    row = next(c for c in changed["cases"] if c["id"] == "bio-osmosis-chat")
    row.update(http_status=422, failure="AssertionError: insufficient_evidence")
    with pytest.raises(ValueError, match="model refusals cannot be rescored"):
        reassess(changed, before, after, **bindings)
    forbidden = copy.deepcopy(after)
    forbidden["cases"][0]["sources"] = ["different source"]
    with pytest.raises(ValueError, match="concepts-only"):
        reassess(original, before, forbidden, **bindings)
