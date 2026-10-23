"""Every gate of the decisions register, checked before it is passed (PRD-11 (c), and each gate's own evidence).

A gate passes only when no decision blocking it is undecided and the evidence the specification names for it is
present and valid; every failure is listed with its reason. The stage gates (`s1_foundation` to `s5_launch`) are
checked by the stage release rule (`release stage`), which uses the same decision check; the other gates are checked
here (`python -m jana_tools release gate <gate> --evidence FILE`):

- `pilot_start`: the M23 release record for the gate (counsel pass 1, tabletop, red team, security and penetration
  test; PRV-07, PRV-21, PRV-23, SEC-25), the signed pilot-country record (PRD-22), the registered protocol (EVL-22),
  the DPIAs of the gate's features (PRV-08), verified helplines (PRV-14), the release root (SEC-12), the pilot
  environment's hosts and pins (SEC-31), content safety reviewers (CUR-27) and the on-call drill (OPS-21).
- `cloud_tier`: the M23 release record for the gate, counsel pass 2 with cross-border transfer and each provider
  (D13, PRV-07a, PRV-25), the cloud DPIA (PRV-08), the gateway's hosts and pins (SEC-31) and the load test at twice
  the forecast peak (OPS-18).
- `paid_launch`: the payment partner (BIZ-10, D70), release-signed installers (PLT-05, PLT-07, SEC-15), the owner's
  release pins, the willingness-to-pay research (BIZ-13) and the S2 exit metrics met in the pilot (PRD-17).
- `voice_launch`: the voice gates (VOC-21) for the candidate, after M25 is accepted (D97).
- `web_launch`, `mobile_launch`: the client's DPIA where TABLE PRV-08a has one, and the S2 journeys that apply to the
  client (TABLE PRD-17a, S4).
- `fine_tune`: the tuned model passes every gate and the contamination check (EVL-27).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from ..spec import DOCS
from . import dpia
from .stage import STAGE_GATE, register_gates, undecided_for_gate

STAGE_GATES = frozenset(STAGE_GATE.values())
OTHER_GATES = ("pilot_start", "cloud_tier", "paid_launch", "voice_launch", "web_launch", "mobile_launch", "fine_tune")
# Online services each gate's features reach (TABLE ARC-07a), whose real hosts and pins must be set (SEC-31, OPS-35).
GATE_SERVICES = {
    "pilot_start": ("downloads", "updates", "telemetry", "crash"),
    "cloud_tier": ("gateway",),
}
# Candidate-bound field evidence (M24) a gate needs, by the acceptance test that records it.
GATE_FIELD_EVIDENCE = {
    "pilot_start": ("ops21_after_hours_page_drill",),  # OPS-21: on-call from pilot_start
    "cloud_tier": ("ops18_load_test_at_twice_peak",),  # OPS-18: before the cloud_tier gate
}
RESOURCES = REPO_ROOT / "content" / "agent" / "safety" / "resources.yaml"
REVIEWERS = REPO_ROOT / "services" / "signing-service" / "signing_service" / "safety_reviewers.json"


def gate_errors(
    gate: str,
    evidence: dict[str, Any] | None,
    *,
    candidate: str,
    today: date | None = None,
    docs: Path = DOCS,
    field_index: Path | None = None,
    environment: Any = None,
    trust: Any = None,
    settings: Any = None,
) -> list[str]:
    """Every reason `gate` cannot pass for `candidate`: undecided blocking decisions first, then its own evidence."""
    from agent_core.config import Settings
    from agent_core.config.environments import Environment

    settings = settings or Settings()
    today = today or date.today()
    errors = [f"decision {d}" for d in undecided_for_gate(gate, docs)]
    if gate not in register_gates(docs):
        return errors
    if gate in STAGE_GATES:
        stage = next(s for s, g in STAGE_GATE.items() if g == gate)
        return [*errors, f"{gate} is a stage gate: the stage release rule checks it (release stage {stage})"]
    if environment is None:
        environment = Environment.PILOT if gate == "pilot_start" else Environment.PRODUCTION
    evidence = evidence or {}
    if not evidence:
        return [*errors, f"{gate}: no gate evidence"]
    from ..m23.records import errors as record_errors

    malformed = record_errors("gate_evidence", evidence)
    if malformed:
        return [*errors, *malformed]
    if evidence["gate"] != gate or evidence["candidate"] != candidate:
        errors.append(f"{gate}: the evidence belongs to another gate or candidate")
    check = {
        "pilot_start": _pilot_start,
        "cloud_tier": _cloud_tier,
        "paid_launch": _paid_launch,
        "voice_launch": _voice_launch,
        "web_launch": _web_launch,
        "mobile_launch": _mobile_launch,
        "fine_tune": _fine_tune,
    }[gate]
    errors += check(evidence, candidate=candidate, today=today, docs=docs, environment=environment, trust=trust,
                    settings=settings)  # fmt: skip
    errors += _field_evidence(gate, field_index, candidate)
    return errors


def _dpias(gate: str, evidence: dict[str, Any], environment: Any, trust: Any) -> list[str]:
    return dpia.gate_errors(gate, evidence.get("dpia_list"), evidence.get("dpias", []), environment=environment,
                            trust=trust)  # fmt: skip


def _m23(gate: str, evidence: dict[str, Any], candidate: str, today: date, settings: Any) -> list[str]:
    from ..m23.gates import release_errors

    return release_errors(evidence.get("release", {}), candidate=candidate, stage="S2", gate=gate, today=today,
                          settings=settings)  # fmt: skip


def _pilot_start(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                 settings: Any) -> list[str]:  # fmt: skip
    from ..m23.programme import protocol_errors

    errors = _m23("pilot_start", evidence, candidate, today, settings)
    country = evidence.get("country", {})
    errors += country_record_errors(country, environment, trust)
    errors += protocol_errors(evidence.get("protocol", {}), settings)
    code = country.get("country")
    if evidence.get("protocol", {}).get("country") != code:
        errors.append("EVL-22: the protocol's country differs from the pilot country")
    if evidence.get("release", {}).get("counsel", {}).get("country") != code:
        errors.append("PRV-07: counsel's country differs from the pilot country")
    errors += _dpias("pilot_start", evidence, environment, trust)
    errors += helpline_errors(code)
    errors += service_errors("pilot", GATE_SERVICES["pilot_start"])
    errors += trust_root_errors()
    errors += reviewer_errors()
    return errors


def _cloud_tier(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                settings: Any) -> list[str]:  # fmt: skip
    errors = _m23("cloud_tier", evidence, candidate, today, settings)
    counsel = evidence.get("counsel_pass")
    if not isinstance(counsel, dict) or counsel.get("pass") != 2 or counsel.get("gate") != "cloud_tier":
        errors.append("D13: counsel's second pass (the cloud tier) is missing")
    else:
        from ..m23.gates import counsel_errors

        errors += [f"D13 pass 2: {e}" for e in counsel_errors(counsel["counsel"], today=today)]
        transfer = counsel["counsel"].get("topics", {}).get("international_transfer", {})
        if transfer.get("reviewed") is not True:
            errors.append("PRV-07a: counsel has not reviewed cross-border transfer for the cloud tier")
        if not counsel.get("providers"):
            errors.append("PRV-25: counsel's second pass names no assessed provider and region")
    errors += _dpias("cloud_tier", evidence, environment, trust)
    for env in ("pilot", "production"):
        errors += service_errors(env, GATE_SERVICES["cloud_tier"])
    return errors


def _paid_launch(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                 settings: Any) -> list[str]:  # fmt: skip
    from ..m23.programme import wtp_errors
    from .package_cli import owner_pins
    from .stage import s2_pilot_rows

    errors = []
    payment = evidence.get("payment")
    if not payment:
        errors.append("BIZ-10: no payment partner record for the market")
    installers = evidence.get("installers")
    if not installers:
        errors.append("PLT-05: no release-signed installer record")
    elif installers["candidate"] != candidate:
        errors.append("PLT-05: the signed installers belong to another candidate")
    errors += owner_pins(release=True)
    errors += wtp_errors(evidence.get("wtp", {}), settings)
    if payment and evidence.get("wtp", {}).get("country") not in (None, payment["country"]):
        errors.append("BIZ-13: the price research is for another market than the payment partner")
    rows = s2_pilot_rows(evidence.get("pilot_exit"), settings)
    errors += [f"PRD-17: {r['metric']}: {r['status']} ({r['measured']}; target {r['target']})" for r in rows
               if r["status"] != "met"]  # fmt: skip
    return errors


def _voice_launch(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                  settings: Any) -> list[str]:  # fmt: skip
    errors = []
    if not (docs / "implementation" / "m25-acceptance.md").is_file():
        errors.append("D97: voice is accepted only after M25 (no M25 acceptance record)")
    voice = evidence.get("voice")
    if not voice:
        return [*errors, "VOC-21: no voice gate results"]
    if voice["candidate"] != candidate:
        errors.append("VOC-21: the voice gate results belong to another candidate")
    for language, wer in voice["wer_subject_vocabulary"].items():
        rate = wer["errors"] / wer["words"]
        if rate > settings.voice_gate_wer_max:
            errors.append(
                f"VOC-21: word error rate {rate:.1%} in {language} (gate ≤ {settings.voice_gate_wer_max:.0%})"
            )
    missing = set(voice["languages"]) - set(voice["wer_subject_vocabulary"])
    if missing:
        errors.append(f"VOC-21: no word error rate for {', '.join(sorted(missing))}")
    cutoffs = voice["false_cutoffs"]
    if (
        cutoffs["passed"] > cutoffs["total"]
        or cutoffs["passed"] / cutoffs["total"] > settings.voice_gate_false_cutoff_max
    ):
        errors.append(f"VOC-21: false cut-offs {cutoffs['passed']}/{cutoffs['total']} "
                      f"(gate ≤ {settings.voice_gate_false_cutoff_max:.0%})")  # fmt: skip
    for name in ("raw_latex_spoken", "spoken_number_mismatches"):
        if voice[name] != 0:
            errors.append(f"VOC-21: {name.replace('_', ' ')} {voice[name]} (gate 0)")
    for name, (p50, p90) in (
        ("turn_latency", settings.voice_gate_turn_latency_s),
        ("read_aloud_latency", settings.voice_gate_read_aloud_latency_s),
    ):
        measured = voice[name]
        if not (math.isfinite(measured["p50_s"]) and math.isfinite(measured["p90_s"])) or (
            measured["p50_s"] > p50 or measured["p90_s"] > p90
        ):
            errors.append(f"VOC-21: {name.replace('_', ' ')} p50 {measured['p50_s']} s, p90 {measured['p90_s']} s "
                          f"(gate p50 ≤ {p50} s, p90 ≤ {p90} s)")  # fmt: skip
    for voice_id, score in voice["intelligibility"].items():
        if score < settings.voice_gate_intelligibility_min:
            errors.append(
                f"VOC-21: {voice_id} intelligibility {score} (gate ≥ {settings.voice_gate_intelligibility_min})"
            )
    return errors


def _client(client: str, evidence: dict[str, Any], candidate: str) -> list[str]:
    journeys = evidence.get("client_journeys")
    if not journeys or journeys.get("client") != client:
        return [f"PRD-17: no {client} journey results (TABLE PRD-17a, S4)"]
    errors = [] if journeys["candidate"] == candidate else [f"PRD-17: the {client} results belong to another candidate"]
    failed = sorted(j for j, status in journeys["journeys"].items() if status == "failed")
    if failed:
        errors.append(f"PRD-17: {client} fails {', '.join(failed)}")
    return errors


def _web_launch(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                settings: Any) -> list[str]:  # fmt: skip
    return _dpias("web_launch", evidence, environment, trust) + _client("web", evidence, candidate)


def _mobile_launch(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
                   settings: Any) -> list[str]:  # fmt: skip
    return _client("android", evidence, candidate)


def _fine_tune(evidence: dict[str, Any], *, candidate: str, today: date, docs: Path, environment: Any, trust: Any,
               settings: Any) -> list[str]:  # fmt: skip
    tuned = evidence.get("tuned_model")
    if not tuned:
        return ["EVL-27: no tuned-model evaluation"]
    errors = [] if tuned["candidate"] == candidate else ["EVL-27: the evaluation belongs to another candidate"]
    if tuned["gates_failed"]:
        errors.append(f"EVL-27: the tuned model fails {', '.join(tuned['gates_failed'])}")
    if tuned["regressions_against_base"]:
        errors.append(f"TRN-26: regresses against the base on {', '.join(tuned['regressions_against_base'])}")
    if tuned["contamination_check"]["status"] != "pass":
        errors.append("EVL-27: the contamination check did not pass (TRN-17)")
    return errors


def country_record_errors(record: Any, environment: Any, trust: Any = None) -> list[str]:
    """PRD-22: the signed pilot-country record as the pilot build reads it: complete, signed under a root the
    environment trusts, and cleared by a protocol registered before its baseline."""
    from agent_core.config.pilot import country_record_errors as core_errors

    return core_errors(record, environment, trust)


def helpline_errors(country: Any) -> list[str]:
    """PRV-14, TABLE PRD-22a: the safety-resources pack names the pilot country and has a verified entry."""
    import yaml

    pack = yaml.safe_load(RESOURCES.read_text()) or {}
    errors = []
    if not country or pack.get("country") != country:
        errors.append(f"PRV-14: the safety resources are for {pack.get('country')!r}, not the pilot country")
    if not any(isinstance(e, dict) and e.get("verified") is True for e in pack.get("entries") or []):
        errors.append("PRV-14: no verified emergency number or child helpline (content/agent/safety/resources.yaml)")
    if not pack.get("verified_by"):
        errors.append("PRV-14: the safety resources name no verifying child-protection partner")
    return errors


def service_errors(environment: str, services: tuple[str, ...]) -> list[str]:
    """SEC-31, OPS-35: each service a gate's features reach has a real host and at least a primary and backup pin."""
    from agent_core.net.policy import load_policy

    policy = load_policy()
    errors = []
    for service in services:
        host = policy.services.get(environment, {}).get(service, "")
        if not host or host.endswith(".invalid"):
            errors.append(f"SEC-31: the {environment} {service} host is a placeholder ({host or 'none'})")
    if len(policy.pins.get(environment, ())) < 2:
        errors.append(f"SEC-31: the {environment} environment has no primary and backup TLS pins")
    return errors


def trust_root_errors() -> list[str]:
    from signing_service.hierarchy import production_anchors

    if not production_anchors().roots:
        return ["SEC-12: the build trusts no release root yet (the key ceremony)"]
    return []


def reviewer_errors() -> list[str]:
    import json

    if not json.loads(REVIEWERS.read_text()).get("reviewers"):
        return ["CUR-27: no content safety reviewer key for the pilot and stable channels"]
    return []


def _field_evidence(gate: str, index: Path | None, candidate: str) -> list[str]:
    names = GATE_FIELD_EVIDENCE.get(gate, ())
    if not names:
        return []
    if index is None:
        return [f"{name}: needs candidate-bound field evidence (--field-evidence)" for name in names]
    from .field_evidence import field_errors, read_evidence

    errors = []
    revision = (REPO_ROOT / "spec.lock").read_text().strip()
    now = datetime.now(UTC)
    for name in names:
        try:
            errors += [f"{name}: {e}" for e in field_errors(name, read_evidence(index, name, candidate, revision, now),
                                                            now)]  # fmt: skip
        except (OSError, ValueError, KeyError) as error:
            errors.append(f"{name}: {error}")
    return errors
