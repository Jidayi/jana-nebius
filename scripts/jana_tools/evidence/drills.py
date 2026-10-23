"""M24 device tests and drills as checklists: steps to follow, questions to answer, and how the answers become the
probe-record `data` each JANA_M24_EVIDENCE check reads (jana_tools.release.field_evidence.field_errors).

The builders only place what a person answered; they never supply an observation. Derived numbers (hours between
two recorded times, a section list) are computed from recorded answers, and an unanswered value stays a FILL-IN
placeholder that every gate refuses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from agent_core.config import Settings
from agent_core.config.support import GUIDES, settings_sections

from .. import REPO_ROOT
from ..m23.gates import RELEASE_GATES
from ..release import incidents as inc
from ..release import operations as ops
from ..release.field_evidence import OPS11_EXPECTED
from .placeholders import FILL_IN, MARKERS
from .records import tabletop_file

Kind = Literal[
    "text", "note", "int", "number", "yes", "time", "date", "numbers", "list", "dates", "proof", "sha", "choice",
    "zone", "steps",
]  # fmt: skip
Answers = dict[str, Any]


@dataclass(frozen=True)
class Ask:
    key: str
    question: str
    kind: Kind
    example: Any = None  # --dry-run only; never written into a record that a gate accepts
    choices: tuple[str, ...] = ()
    later: bool = False  # "later" is accepted and written as a FILL-IN placeholder the gate refuses


@dataclass(frozen=True)
class Repeat:
    """A group of questions asked once per entry: fixed entries (a test matrix) or as many as the person adds."""

    key: str
    title: str
    asks: tuple[Ask, ...]
    presets: Callable[[Answers, Settings], list[dict[str, Any]]] | None = None
    template: dict[str, Any] = field(default_factory=dict)  # one entry's fixed fields, for the fill-in template


@dataclass(frozen=True)
class Drill:
    id: str
    title: str
    requirements: str
    tests: tuple[str, ...]
    who: str
    steps: tuple[str | Callable[[Settings], str], ...]  # a callable step is worded for the build being tested
    asks: tuple[Ask | Repeat, ...]
    build: Callable[[Answers, Settings, dict[str, Any]], dict[str, Any]]
    append: bool = False  # the record accumulates entries across runs (the OPS-34 drill log)
    targets: tuple[str, ...] = ()  # the named config keys the gate judges this drill against


def unanswered(value: Any) -> bool:
    return isinstance(value, str) and any(marker in value for marker in MARKERS)


def when(flag: Any, yes: Any, no: Any) -> Any:
    """`yes` if the person answered yes, `no` if they answered no. An unanswered flag (a template) stays a
    placeholder that names the value each answer stores."""
    if unanswered(flag):
        question = str(flag).rsplit(": ", 1)[-1]
        return f"{FILL_IN}: {json.dumps(yes)} if yes, {json.dumps(no)} if no: {question}"
    return yes if flag is True else no


def _moment(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def hours_between(start: Any, end: Any) -> Any:
    if unanswered(start) or unanswered(end):
        return f"{FILL_IN}: hours between two times that are not yet recorded"
    return round((_moment(end) - _moment(start)).total_seconds() / 3600, 4)


def seconds_between(start: Any, end: Any) -> Any:
    if unanswered(start) or unanswered(end):
        return f"{FILL_IN}: seconds between two times that are not yet recorded"
    return round((_moment(end) - _moment(start)).total_seconds(), 3)


def working_days_between(start: Any, end: Any) -> Any:
    """Monday-to-Friday days after `start` up to and including `end` (both dates or date-times)."""
    if unanswered(start) or unanswered(end):
        return f"{FILL_IN}: working days until a review that is not yet written"
    first, last = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    days, total = first, 0
    while days < last:
        days += timedelta(days=1)
        total += days.weekday() < 5
    return total


def _calendar(a: Answers) -> dict[str, Any]:
    return {"timezone": a["timezone"], "holidays": a["holidays"]}


ZONE = Ask("timezone", "Time zone of the pilot schools (IANA name, e.g. Africa/Lagos)", "zone", "Africa/Lagos")
HOLIDAYS = Ask(
    "holidays", "School holidays in the drill window (YYYY-MM-DD, comma-separated; Enter for none)", "dates", ""
)
DEVICE = Ask(
    "device",
    "Device or environment used: hardware class, model and asset label, OS version (or the staging environment name)",
    "text",
    "low-class reference laptop, label RL-1",
)


# ---------------------------------------------------------------------------------------------------- OPS-07
def _lifecycle_presets(a: Answers, cfg: Settings) -> list[dict[str, Any]]:
    matrix = ops.lifecycle_matrix(tuple(a["supported_apps"]), tuple(a["platforms"]), a["candidate_version"])
    return [{"hardware": h, "platform": p, "previous": v, "route": r} for h, p, v, r in matrix]


def _ops07(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    runs = [
        {
            "hardware": run["hardware"],
            "platform": run["platform"],
            "previous": run["previous"],
            "route": run["route"],
            "replay_before": run["replay_before"],
            "replay_after": run["replay_after"],
            "zero_egress": run["zero_egress"],
            "passed": run["passed"],
            "steps": run["steps"],
            "evidence_id": run["evidence"],
        }
        for run in a["runs"]
    ]
    data = {
        "os_network_blocked": a["os_network_blocked"],
        "candidate_version": a["candidate_version"],
        "supported_apps": a["supported_apps"],
        "platforms": a["platforms"],
        "runs": runs,
    }
    return {"ops07_offline_lifecycle_script": data, "ops07_skip_version_upgrades": data}


OPS07 = Drill(
    id="ops07",
    title="Offline lifecycle and direct-upgrade script on every reference laptop",
    requirements="OPS-07 (with EVL-14, PLT-12..15, OPS-10, OPS-11, OBS-18/19)",
    tests=("ops07_offline_lifecycle_script", "ops07_skip_version_upgrades"),
    who="You plus the low, mid and high reference laptops for each platform; no one else needed.",
    steps=(
        "Turn networking off at the operating-system level and start an outbound-connection monitor; keep its log.",
        "Fresh run (route kit): install from the candidate USB kit, complete first run, one guided turn, one practice "
        "item and one mock item, cross a pack boundary, apply the test safety configuration from a USB folder (every "
        "target kind), inject a first-launch failure and confirm rollback, export a support bundle and run the "
        "redaction scanner.",
        "For each supported older version: restore its fixture image with seeded synthetic learner data, note the "
        "mastery replay hash, upgrade directly to the candidate by offline update pack (usb_update), repeat the same "
        "steps and note the replay hash again. Then do the same from a fresh copy of the image with the online "
        "updater (online_update) in a separate online run.",
        "Save the connection-monitor log or screen recording of each run; the checklist copies it in as that run's "
        "proof.",
    ),
    asks=(
        Ask("platforms", "Platforms in the release (comma-separated, e.g. windows,macos)", "list", "windows"),
        Ask("candidate_version", "App version of this release candidate (X.Y.Z)", "text", "1.1.0"),
        Ask(
            "supported_apps",
            "App versions still supported (comma-separated, e.g. 1.2.0,1.3.1); for the very first release, only its "
            "own version",
            "list",
            "1.0.0",
        ),
        Ask("os_network_blocked", "Was networking disabled at the OS level for every offline run?", "yes", True),
        Repeat(
            "runs",
            "Run {hardware} / {platform} / from {previous} / via {route}",
            (
                Ask("passed", "Did every step of the script pass on this run?", "yes", True),
                Ask("zero_egress", "Did the monitor record zero outbound connections?", "yes", True),
                Ask(
                    "replay_before", "Mastery replay hash before upgrade (64 hex; fresh runs: hash after replay)", "sha"
                ),
                Ask("replay_after", "Mastery replay hash after upgrade (64 hex)", "sha"),
                Ask(
                    "steps",
                    "Steps completed: 'all' or a comma list of " + ", ".join(sorted(ops.LIFECYCLE_STEPS)),
                    "steps",
                    "all",
                    tuple(sorted(ops.LIFECYCLE_STEPS)),
                ),
                Ask("evidence", "Path to this run's monitor log or recording", "proof"),
            ),
            presets=_lifecycle_presets,
            template={
                "hardware": f"{FILL_IN}: low, mid or high",
                "platform": f"{FILL_IN}: one platform",
                "previous": f"{FILL_IN}: fresh or a supported version",
                "route": f"{FILL_IN}: kit (fresh) or usb_update / online_update",
            },
        ),
    ),
    build=_ops07,
)


# ---------------------------------------------------------------------------------------------------- OPS-11
def _ops11(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    observed = {
        row["target"]: when(row["as_expected"], OPS11_EXPECTED.get(row["target"]), "not_as_expected")
        for row in a["targets"]
    }
    notes = {row["target"]: row["note"] for row in a["targets"] if row["note"]}
    return {
        "ops11_each_target_kind": {
            "observed": observed,
            "notes": notes,
            "unverified_numbers_shown": a["unverified_numbers_shown"],
        }
    }


OPS11 = Drill(
    id="ops11",
    title="Each safety-configuration target kind on a test device",
    requirements="OPS-11 (with OPS-10, PRV-21)",
    tests=("ops11_each_target_kind",),
    who="You with one reference laptop; no one else needed.",
    steps=(
        "Build a signed test safety configuration with one entry of every target kind (the release ops tooling).",
        "Apply it to the candidate on a test device by USB folder; start a new turn so it takes effect.",
        "For each target kind, open the affected item, lesson, visual, skill, model, tool or feature and compare what "
        "the device does with the expected behaviour the checklist shows.",
        "Look for any number shown to the student that the tools did not verify; count them.",
        "Keep a screen recording of the whole session as the proof.",
    ),
    asks=(
        Repeat(
            "targets",
            "Target kind {target}: expected behaviour '{expected}'",
            (
                Ask("as_expected", "Did the device show exactly the expected behaviour?", "yes", True),
                Ask("note", "Note (what you saw; Enter for none)", "note", ""),
            ),
            presets=lambda a, cfg: [{"target": t, "expected": e} for t, e in OPS11_EXPECTED.items()],
            template={"target": f"{FILL_IN}: one target kind"},
        ),
        Ask("unverified_numbers_shown", "How many unverified numbers were shown to the student?", "int", 0),
        Ask("recording", "Path to the screen recording", "proof"),
    ),
    build=_ops11,
)


# ---------------------------------------------------------------------------------------------------- OPS-12
def _ops12(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    return {
        "ops12_global_cloud_off": {
            "turns": a["turns"],
            "failed_turns": a["failed_turns"],
            "local_turns": a["local_turns"],
            "time_to_local_s": seconds_between(a["switched_at"], a["all_local_at"]),
            "max_refusal_s": a["max_refusal_s"],
        }
    }


OPS12 = Drill(
    id="ops12",
    title="Global cloud switch-off during a staging load test",
    requirements="OPS-12 (with ARC-12, OPS-18)",
    tests=("ops12_global_cloud_off",),
    who="You (or the cloud on-call) with the staging gateway and a load generator; needs the cloud tier built.",
    steps=(
        "Start a staging load test with synthetic students only.",
        "Throw the audited global cloud switch (kind global) and note the exact time.",
        "Watch the gateway report: note when every new turn is served by a local candidate.",
        "Stop the load test; read total turns, failed turns, turns served locally and the longest refusal time.",
        "Export the load-test report and the switch audit entry as proof.",
    ),
    asks=(
        Ask("switched_at", "Time the switch was thrown (Enter = now)", "time", 0),
        Ask("all_local_at", "Time all new turns were local (Enter = now)", "time", 3),
        Ask("turns", "Turns in the test window", "int", 100),
        Ask("failed_turns", "Failed turns", "int", 0),
        Ask("local_turns", "Turns served by local candidates after the switch", "int", 100),
        Ask("max_refusal_s", "Longest cloud refusal response, seconds", "number", 0.2),
        Ask("report", "Path to the load-test report", "proof"),
    ),
    targets=("ops_switch_max_age_s", "ops_switch_response_s"),
    build=_ops12,
)


# ---------------------------------------------------------------------------------------------------- OPS-15
def _ops15(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "media_id": c["media_id"],
            "sha256": c["sha256"],
            "hardware": c["hardware"],
            "offline_install": c["offline_install"],
            "hash_verified": c["hash_verified"],
            "operator": c["operator"],
            "at": c["at"],
            "evidence_sha256": c["evidence"],
        }
        for c in a["checks"]
    ]
    return {
        "ops15_physical_kit_verified": {"batch_size": a["batch_size"], "kit_sha256": a["kit_sha256"], "checks": checks}
    }


def _usb_presets(a: Answers, cfg: Settings) -> list[dict[str, Any]]:
    return [{"sample": n + 1} for n in range(ops.required_usb_samples(a["batch_size"], cfg))]


OPS15 = Drill(
    id="ops15",
    title="Sampled physical USB kits install and verify offline",
    requirements="OPS-15 (with PLT-12, OPS-07)",
    tests=("ops15_physical_kit_verified",),
    who="You with the low-class reference laptop and the written batch of USB sticks.",
    steps=(
        "Write the batch of USB kits from the stable kit image; count the batch.",
        "Pick the number of sticks the checklist asks for at random from the batch.",
        "For each: networking off, install from the stick on the low-class reference laptop, run the kit verifier, "
        "and photograph or save the verifier output.",
    ),
    asks=(
        Ask("batch_size", "Number of USB sticks in the batch", "int", 50),
        Ask("kit_sha256", "SHA-256 of the kit image written to the batch (64 hex)", "sha"),
        Repeat(
            "checks",
            "Sample {sample}",
            (
                Ask("media_id", "Label on this stick", "text", "stick-1"),
                Ask("sha256", "SHA-256 the verifier printed for this stick", "sha"),
                Ask("hardware", "Hardware class of the laptop used", "choice", "low", ("low", "mid", "high")),
                Ask("offline_install", "Did it install with networking off?", "yes", True),
                Ask("hash_verified", "Did the verifier report the hash as verified?", "yes", True),
                Ask("operator", "Who did the check (name or role)", "text", "release operations"),
                Ask("at", "Time of the check (Enter = now)", "time", 0),
                Ask("evidence", "Path to the photo or verifier output", "proof"),
            ),
            presets=_usb_presets,
            template={"sample": f"{FILL_IN}: one entry per sampled stick"},
        ),
    ),
    targets=("ops_usb_sample_every", "ops_usb_min_samples"),
    build=_ops15,
)


# ---------------------------------------------------------------------------------------------------- OPS-17
def _ops17_slo(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    samples = [
        {
            "service": s["service"],
            "requests": s["requests"],
            "failures": s["failures"],
            "latencies_s": s["latencies_s"],
            "alert_delay_s": s["alert_delay_s"],
        }
        for s in a["services"]
    ]
    services = [
        s["service"] if not unanswered(s["injected"]) else s["injected"]
        for s in a["services"]
        if s["injected"] is not False
    ]
    return {"ops17_slo_alerting": {"services": services, "samples": samples}}


OPS17_SLO = Drill(
    id="ops17-slo",
    title="Synthetic outage alerts for every service objective",
    requirements="OPS-17 (with OPS-21)",
    tests=("ops17_slo_alerting",),
    who="You (or the on-call) with staging for every service; the cloud gateway row needs the cloud tier built.",
    steps=(
        "For each service, inject a synthetic outage in staging (failing requests or slow responses) and note when.",
        "Note when the alert fired; read requests, failures and response times for the window from the dashboard.",
        "Export each dashboard window's raw response times to a text file (one number per line) and keep the alert "
        "receipts.",
    ),
    asks=(
        Repeat(
            "services",
            "Service {service}",
            (
                Ask("injected", "Did you inject an outage for this service?", "yes", True),
                Ask("requests", "Requests in the window", "int", 1000),
                Ask("failures", "Failed requests in the window", "int", 100),
                Ask(
                    "latencies_s",
                    "Response times in seconds: '@file' or comma list (Enter if none)",
                    "numbers",
                    "0.1,0.2",
                ),
                Ask("alert_delay_s", "Seconds from the outage start to the alert", "number", 60),
            ),
            presets=lambda a, cfg: [{"service": name} for name in ops.slo_objectives(cfg)],
            template={"service": f"{FILL_IN}: one service"},
        ),
        Ask("receipts", "Path to the alert receipts (export or screenshot bundle)", "proof"),
    ),
    targets=("ops_alert_delay_s", "ops_error_budget_pause_share", "ops_percentile"),
    build=_ops17_slo,
)


def _ops17_words(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    samples = {"reference_low": a["reference_low"]}
    if a["s4_web"]:
        samples["s4_web"] = a["s4_web"]
    return {
        "ops17_cloud_first_words_budget": {
            "measurement": when(a["accepted_text"], "accepted_text_after_api10", "other"),
            "all_gates_enabled": a["all_gates_enabled"],
            "samples": samples,
        }
    }


OPS17_WORDS = Drill(
    id="ops17-words",
    title="Cloud-tier first accepted text against the budget",
    requirements="OPS-17 (with PLT-26, API-10)",
    tests=("ops17_cloud_first_words_budget",),
    who="You with the low-class reference laptop on a normal connection and the staging gateway; needs the cloud tier.",
    steps=(
        "Run the synthetic probe from the low-class reference laptop with every API-10 gate on.",
        "Export the time from sending each turn to the first accepted tutor text, one number per line.",
        "From S4 also run it from the web client.",
    ),
    asks=(
        Ask("accepted_text", "Did the probe time the first accepted text after every API-10 gate?", "yes", True),
        Ask("all_gates_enabled", "Were all gates enabled?", "yes", True),
        Ask("reference_low", "Low-class laptop times in seconds: '@file' or comma list", "numbers", "1.0,1.5,2.5"),
        Ask("s4_web", "Web client times from S4: '@file' or comma list (Enter before S4)", "numbers", ""),
        Ask("probe_log", "Path to the probe log", "proof"),
    ),
    targets=("ops_first_words_median_s", "ops_first_words_p95_s", "ops_percentile"),
    build=_ops17_words,
)


# ---------------------------------------------------------------------------------------------------- OPS-18
def _ops18(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "active_students",
        "tested_concurrency",
        "contracted_concurrency",
        "objectives_passed",
        "school_quotas_enforced",
    )
    return {"ops18_load_test_at_twice_peak": {k: a[k] for k in keys}}


OPS18 = Drill(
    id="ops18",
    title="Gateway load test at twice the forecast peak",
    requirements="OPS-18",
    tests=("ops18_load_test_at_twice_peak",),
    who="You (or the SRE lead) with an authorised staging load run; needs the cloud tier and provider contracts.",
    steps=(
        "Take the forecast of active cloud students; `evidence targets` prints the concurrency multiples.",
        "Run the authorised staging load at the tested concurrency with per-school quotas switched on.",
        "Read whether every gateway objective held and whether quotas refused over-quota schools.",
        "Export the load-test report as proof.",
    ),
    asks=(
        Ask("active_students", "Forecast active cloud students", "int", 1000),
        Ask("tested_concurrency", "Concurrent turns the load test reached", "number", 300),
        Ask("contracted_concurrency", "Concurrent turns the provider contracts allow", "number", 300),
        Ask("objectives_passed", "Did every gateway objective hold?", "yes", True),
        Ask("school_quotas_enforced", "Were per-school quotas enforced?", "yes", True),
        Ask("report", "Path to the load-test report", "proof"),
    ),
    targets=("ops_peak_share", "ops_load_multiple", "ops_capacity_multiple"),
    build=_ops18,
)


# ---------------------------------------------------------------------------------------------------- OPS-20
def _ops20(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "outage_at",
        "fallback_at",
        "primary_healthy_since",
        "primary_restored_at",
        "failed_turns",
        "fallback_turns",
    )
    return {"ops20_failover_drill": {k: a[k] for k in keys}}


OPS20 = Drill(
    id="ops20",
    title="Primary provider failover and failback in staging",
    requirements="OPS-20 (with OPS-34 cloud_failover)",
    tests=("ops20_failover_drill",),
    who="You (or the cloud on-call) with staging traffic; needs a qualified fallback provider.",
    steps=(
        "With synthetic staging traffic flowing, fail the primary provider and note the time.",
        "Note when traffic is on the fallback.",
        "Restore the primary; note when it became healthy and when traffic returned to it.",
        "Read failed turns and turns served by the fallback; export the gateway log as proof.",
    ),
    asks=(
        Ask("outage_at", "Time the primary was failed (Enter = now)", "time", 0),
        Ask("fallback_at", "Time traffic was on the fallback (Enter = now)", "time", 2),
        Ask("primary_healthy_since", "Time the primary was healthy again (Enter = now)", "time", 10),
        Ask("primary_restored_at", "Time traffic returned to the primary (Enter = now)", "time", 30),
        Ask("failed_turns", "Failed turns", "int", 0),
        Ask("fallback_turns", "Turns served by the fallback", "int", 50),
        Ask("log", "Path to the gateway log", "proof"),
    ),
    targets=("ops_switch_max_age_s", "ops_failback_healthy_s"),
    build=_ops20,
)


# ---------------------------------------------------------------------------------------------------- OPS-21
def _ops21(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    page = {
        "signal": when(a["sev1"], "SEV1", "other"),
        "sent_at": a["sent_at"],
        "acknowledged_at": a["acknowledged_at"],
        "operator": a["operator"],
        "evidence_sha256": a["receipt"],
    }
    return {"ops21_after_hours_page_drill": {"calendar": _calendar(a), "page": page}}


OPS21 = Drill(
    id="ops21",
    title="After-hours SEV1 page drill",
    requirements="OPS-21 (with OPS-30)",
    tests=("ops21_after_hours_page_drill",),
    who="You plus the person on call (unwarned); outside school hours in the pilot time zone.",
    steps=(
        "Pick a time outside school hours or on a school holiday in the pilot time zone.",
        "Send a synthetic SEV1 page through the real pager to whoever is on call, without warning them.",
        "Note when it was sent and when they acknowledged; keep the pager's delivery and acknowledgement receipt.",
    ),
    asks=(
        ZONE,
        HOLIDAYS,
        Ask("sev1", "Was the page sent as a SEV1 signal?", "yes", True),
        Ask("sent_at", "Time the page was sent (Enter = now)", "time", 0),
        Ask("acknowledged_at", "Time it was acknowledged (Enter = now)", "time", 0.5),
        Ask("operator", "Who acknowledged (name or rota role)", "text", "on-call engineer"),
        Ask("receipt", "Path to the pager receipt", "proof"),
    ),
    targets=("ops_sev1_ack_hours", "ops_support_open_hour", "ops_support_close_hour"),
    build=_ops21,
)


# ---------------------------------------------------------------------------------------------------- OPS-25
def _ops25(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    files = {g["guide"]: {"sha256": g["pdf"], "reader_checked": g["reader_checked"]} for g in a["guides"]}
    return {
        "ops25_docs_match_version": {
            "app_version": a["app_version"],
            "manifest": {"app_major_minor": a["docs_version"], "files": files},
        }
    }


OPS25 = Drill(
    id="ops25",
    title="Version-matched offline PDF guides on the kit",
    requirements="OPS-25 (with OPS-15, OPS-23)",
    tests=("ops25_docs_match_version",),
    who="You with the candidate kit; a reader for each guide (can be you).",
    steps=(
        "Copy each offline PDF guide off the candidate kit.",
        "Open each one and read it through against the candidate app; note the app version printed on it.",
    ),
    asks=(
        Ask("app_version", "Candidate app version (X.Y.Z)", "text", "1.0.0"),
        Ask("docs_version", "App version printed on the guides (major.minor, e.g. 1.0)", "text", "1.0"),
        Repeat(
            "guides",
            "Guide {guide}",
            (
                Ask("pdf", "Path to this guide's PDF from the kit", "proof"),
                Ask("reader_checked", "Did a reader check it against the candidate app?", "yes", True),
            ),
            presets=lambda a, cfg: [{"guide": g} for g in sorted(GUIDES)],
            template={"guide": f"{FILL_IN}: one guide"},
        ),
    ),
    build=_ops25,
)


# ---------------------------------------------------------------------------------------------------- UXS-46
def _uxs46(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    expected = [s["id"] for s in settings_sections(cfg.build_stage)]
    data = {
        "sections": when(a["order_matches"], expected, ["not_as_expected"]),
        "pin_prompts": a["pin_prompts"],
        "removed_keys": a["removed_keys"],
        "os_network_blocked": a["os_network_blocked"],
        "nonloopback_attempts": a["nonloopback_attempts"],
        "rendered_sections": [s["section"] for s in a["sections"] if s["renders"] is True or unanswered(s["renders"])],
    }
    return {
        name: data for name in ("uxs46_sections_complete", "uxs46_no_answers_or_pin_sections", "uxs46_sections_offline")
    }


def settings_section_names(stage: str) -> list[str]:
    """The Settings sections of a build stage by the names the page shows them (the English catalogue, as
    packages/ui/src/settings/Settings.tsx titles them), in the core's order: what the owner compares the screen with."""
    words = json.loads((REPO_ROOT / "packages" / "i18n" / "locales" / "en.json").read_text())
    named = {"egress": "ledger.title", "accessibility_language": "settings.section.accessibility"}
    return [words[named.get(s["id"], f"settings.section.{s['id']}")] for s in settings_sections(stage)]


UXS46 = Drill(
    id="uxs46",
    title="Settings sections offline",
    requirements="UXS-46 (with TCH-13)",
    tests=("uxs46_sections_complete", "uxs46_no_answers_or_pin_sections", "uxs46_sections_offline"),
    who="You with one reference laptop and the candidate app.",
    steps=(
        "Networking off at the OS level; start the outbound-connection monitor.",
        lambda cfg: (
            f"Open Settings. The section list down the side should read, in this order ({cfg.build_stage} build): "
            + "; ".join(settings_section_names(cfg.build_stage))
            + "."
        ),
        "Open every section and confirm it shows its normal state; note any PIN prompt or removed setting.",
        "Keep the screen recording and the monitor log.",
    ),
    asks=(
        Ask(
            "order_matches",
            "Does Settings list exactly the sections the checklist's step 2 names, in that order, and no other?",
            "yes",
            True,
        ),
        Repeat(
            "sections",
            "Section {section}",
            (Ask("renders", "Did it open and render its normal state offline?", "yes", True),),
            presets=lambda a, cfg: [{"section": s["id"]} for s in settings_sections(cfg.build_stage)],
            template={"section": f"{FILL_IN}: one section"},
        ),
        Ask("pin_prompts", "How many PIN prompts appeared?", "int", 0),
        Ask("removed_keys", "Removed settings that appeared anywhere (comma list; Enter for none)", "list", ""),
        Ask("os_network_blocked", "Was networking disabled at the OS level?", "yes", True),
        Ask("nonloopback_attempts", "Outbound (non-loopback) connection attempts the monitor recorded", "int", 0),
        Ask("recording", "Path to the screen recording", "proof"),
    ),
    build=_uxs46,
)


# ---------------------------------------------------------------------------------------------- OPS-27, CUR-36
def _wrong_key(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "confirmed_at", "withdrawn_at", "corrected_at", "old_item_id", "new_item_id", "old_item_served",
        "affected_attempts", "remarked_attempts", "original_attempts_sha256", "retained_attempts_sha256",
        "projections_equal_full_replay",
    )  # fmt: skip
    replay = {k: a[k] for k in keys}
    hotfix = {
        **replay,
        "reported_at": a["reported_at"],
        "triaged_at": a["triaged_at"],
        "notified_at": a["notified_at"],
        "calendar": _calendar(a),
        "affected_licences": a["affected_licences"],
        "notified_licences": a["notified_licences"],
    }
    return {"ops27_wrong_key_hotfix_flow": hotfix, "cur36_withdraw_and_remark": replay}


WRONG_KEY = Drill(
    id="wrong-key",
    title="Seeded wrong answer key: withdraw, notify, correct and re-mark",
    requirements="OPS-27, CUR-36 (with OPS-10, OPS-28, DAT-05)",
    tests=("ops27_wrong_key_hotfix_flow", "cur36_withdraw_and_remark"),
    who="You plus the Curriculum lead (corrects the item); needs staging and a test device.",
    steps=(
        "In staging, seed an item with a wrong key and attempts on it from synthetic learners; file a report.",
        "Triage it, confirm the wrong key, publish the withdrawal entry and notify the affected test licences.",
        "Author the corrected item under a new id, ship the patch pack and install it on the test device.",
        "Close the app on the test device and run the learner replay on its data folder: uv run python -m "
        "jana_tools evidence remark --data <app data folder> --old <withdrawn id> --new <corrected id> --out "
        "<file>. It refuses until the withdrawal is applied there, and prints the numbers asked for below.",
        "Check the old item is no longer served, every affected attempt was re-marked, the original attempts are "
        "retained unchanged (same hash) and the mastery projections equal a full replay. Give the --out file as "
        "the log, with the staging log.",
    ),
    asks=(
        ZONE,
        HOLIDAYS,
        Ask("reported_at", "Time the report was filed (Enter = now)", "time", 0),
        Ask("triaged_at", "Time it was triaged (Enter = now)", "time", 1),
        Ask("confirmed_at", "Time the wrong key was confirmed (Enter = now)", "time", 2),
        Ask("withdrawn_at", "Time the withdrawal entry was published (Enter = now)", "time", 3),
        Ask("notified_at", "Time the affected licences were notified (Enter = now)", "time", 4),
        Ask("corrected_at", "Time the corrected pack was installed (Enter = now)", "time", 30),
        Ask("old_item_id", "Withdrawn item id", "text", "item-old"),
        Ask("new_item_id", "Corrected item id", "text", "item-new"),
        Ask("old_item_served", "Was the old item served after withdrawal?", "yes", False),
        Ask("affected_attempts", "Attempts on the withdrawn item", "int", 5),
        Ask("remarked_attempts", "Attempts re-marked", "int", 5),
        Ask("original_attempts_sha256", "Hash of the original attempts before correction (64 hex)", "sha"),
        Ask("retained_attempts_sha256", "Hash of the retained attempts after correction (64 hex)", "sha"),
        Ask("projections_equal_full_replay", "Did the projections equal a full replay?", "yes", True),
        Ask("affected_licences", "Affected test licence ids (comma list)", "list", "lic-test-1"),
        Ask("notified_licences", "Licence ids that were notified (comma list)", "list", "lic-test-1"),
        Ask("log", "Path to the staging log or recording", "proof"),
    ),
    targets=("ops_triage_school_days", "ops_withdraw_hours", "ops_correction_days", "ops_school_notice_hours"),
    build=_wrong_key,
)


# ---------------------------------------------------------------------------------------------- OPS-31, PRV-21
def _tabletop(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    incident = {
        "incident_id": a["incident_id"],
        "severity": a["severity"],
        "commander": a["commander"],
        "communications_lead": a["communications_lead"],
        "declared_at": a["declared_at"],
        "category": "child_safety",
        "state": "contained",
        "acknowledged_at": a["acknowledged_at"],
        "contained_at": a["contained_at"],
        "timeline": [
            [a["acknowledged_at"], a["commander"], "acknowledged"],
            [a["contained_at"], a["commander"], "contained"],
        ],
    }
    tabletop = {
        "incident_id": a["incident_id"],
        "safety_lead": a["safety_lead"],
        "handed_off_at": a["handed_off_at"],
        "no_student_contact": a["no_student_contact"],
        "category_only": a["category_only"],
        "session_confirmation_checked": a["session_confirmation_checked"],
        "deletion_verified": a["deletion_verified"],
        "evidence_sha256": a["notes"],
        "hold_group": a["hold_group"],
    }
    governance = {
        "stage": a["stage"],
        "gate": a["gate"],
        "severity": a["severity"],
        "date": a["declared_at"] if unanswered(a["declared_at"]) else str(a["declared_at"])[:10],
        "owner": a["safety_lead"],
        "timings": {
            "triage_hours": hours_between(a["declared_at"], a["triaged_at"]),
            "notify_hours": hours_between(a["declared_at"], a["notified_at"]),
            "mitigate_hours": hours_between(a["declared_at"], a["mitigated_at"]),
            "review_workdays": working_days_between(a["declared_at"], a["review_date"]),
        },
        "notification_deadline_hours": a["notification_deadline_hours"],
        "regression_ref": a["regression_ref"],
        "channels": a["channels"],
        "review_ref": a["review_ref"],
    }
    record = f"@{tabletop_file(a['gate'])}.json"  # PRV-21: one exercise per stage gate, each kept
    return {"ops31_child_safety_tabletop": {"incident": incident, "tabletop": tabletop}, record: governance}


TABLETOP = Drill(
    id="tabletop",
    title="Child-safety SEV1 tabletop (one exercise, two records)",
    requirements="OPS-31 and PRV-21 (with OPS-30, OPS-32, PRV-07, PRV-14)",
    tests=("ops31_child_safety_tabletop",),
    who="The roles the spec names: Safety lead, incident commander, communications lead and the Safety lead's hold "
    "group; counsel's notification limit from counsel.json. Roles may be doubled up in a small team, but run it with "
    "at least one other person so the hand-off is real.",
    steps=(
        "Read out a made-up child-safety report arriving through a problem report; declare the incident and note the "
        "time.",
        "Commander acknowledges; the team decides severity and hands it to the Safety lead.",
        "Safety lead decides containment (a safety configuration through online and USB channels, or the cloud "
        "switch), notification to schools, families and the regulator within counsel's limit, and whether the "
        "child-protection partner is told. No student is contacted; records stay category-only.",
        "Walk through checking a shared support bundle's per-session confirmation and deleting the held evidence.",
        "Record containment time; agree the regression test and who writes the review. Keep the exercise notes.",
    ),
    asks=(
        Ask("stage", "Stage this exercise is for", "choice", "S2", ("S1", "S2", "S3", "S4", "S5")),
        Ask("gate", "Stage gate it is for (each gate needs its own)", "choice", "pilot_start", RELEASE_GATES),
        Ask("incident_id", "Exercise incident id (e.g. tabletop-2026-11-03)", "text", "tabletop-dry"),
        Ask("commander", "Incident commander (name or role)", "text", "incident commander"),
        Ask("communications_lead", "Communications lead (name or role)", "text", "communications lead"),
        Ask("safety_lead", "Safety lead (name or role)", "text", "Safety lead"),
        Ask("hold_group", "Safety lead's hold group, including the Safety lead (comma list)", "list", "Safety lead"),
        Ask("declared_at", "Time the scenario report was declared an incident (Enter = now)", "time", 0),
        Ask("severity", "Severity the team declared", "choice", "SEV1", ("SEV1", "SEV2", "SEV3")),
        Ask("acknowledged_at", "Time the commander acknowledged (Enter = now)", "time", 0.1),
        Ask("triaged_at", "Time triage was decided (Enter = now)", "time", 0.2),
        Ask("handed_off_at", "Time it was handed to the Safety lead (Enter = now)", "time", 0.3),
        Ask("contained_at", "Time containment was in place (Enter = now)", "time", 1),
        Ask("notified_at", "Time the simulated notifications went out (Enter = now)", "time", 2),
        Ask("mitigated_at", "Time the signed mitigation reached online and USB channels (Enter = now)", "time", 3),
        Ask("channels", "Channels the mitigation reached (comma list of online, usb)", "list", "online,usb"),
        Ask("no_student_contact", "Was no student contacted directly?", "yes", True),
        Ask("category_only", "Were the records category-only?", "yes", True),
        Ask("session_confirmation_checked", "Was the bundle's per-session confirmation checked?", "yes", True),
        Ask("deletion_verified", "Was deletion of the held evidence verified?", "yes", True),
        Ask(
            "notification_deadline_hours",
            "Counsel's notification limit in hours ('later' until counsel answers)",
            "number",
            72,
            later=True,
        ),
        Ask(
            "regression_ref",
            "Regression test id for the scenario's cause ('later' if not yet written)",
            "text",
            "regression-dry",
            later=True,
        ),
        Ask("review_date", "Date the written review was finished ('later' if not yet)", "date", "", later=True),
        Ask("review_ref", "Where the written review lives ('later' if not yet)", "text", "review-dry", later=True),
        Ask("notes", "Path to the exercise notes or recording", "proof"),
    ),
    targets=("ops_sev1_ack_hours", "ops_sev1_contain_hours", "incident_triage_hours", "incident_review_workdays"),
    build=_tabletop,
)


# ---------------------------------------------------------------------------------------------------- OPS-32
def _ops32(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    incident = {
        "incident_id": a["incident_id"],
        "severity": a["severity"],
        "commander": a["commander"],
        "communications_lead": a["communications_lead"],
        "declared_at": a["declared_at"],
        "category": a["category"],
        "state": "contained",
        "acknowledged_at": a["acknowledged_at"],
        "contained_at": a["contained_at"],
        "timeline": [
            [a["acknowledged_at"], a["commander"], "acknowledged"],
            [a["contained_at"], a["commander"], "contained"],
        ],
    }
    receipts = [
        {
            "licence_id": r["licence_id"],
            "recipient_kind": r["recipient_kind"],
            "route": r["route"],
            "first_contact_at": r["first_contact_at"],
            "email_at": r["email_at"],
            "kit_id": r["kit_id"],
            "instructions": r["instructions"],
            "evidence_sha256": r["receipt"],
        }
        for r in a["receipts"]
    ]
    return {
        "ops32_schools_notified": {
            "incident": incident,
            "affected_licences": a["affected_licences"],
            "offline_licences": a["offline_licences"],
            "receipts": receipts,
        }
    }


OPS32 = Drill(
    id="ops32",
    title="SEV2 drill: every affected licence holder notified, offline ones included",
    requirements="OPS-32 (with OPS-30, OPS-15)",
    tests=("ops32_schools_notified",),
    who="An incident commander and a communications lead (two people), plus the registered contacts of the drill "
    "licences, warned in advance that it is a drill (or test licences held by staff).",
    steps=(
        "Declare a made-up SEV2 (e.g. a wrong worked answer in a pack); commander acknowledges; contain it.",
        "List the affected licences from the registered-contact list, marking which are offline.",
        "Communications lead contacts each registered contact by phone or SMS, then email, with what to do and which "
        "USB kit brings the fix; keep each call log, SMS receipt and sent email.",
    ),
    asks=(
        Ask("incident_id", "Drill incident id", "text", "sev2-dry"),
        Ask("severity", "Severity declared", "choice", "SEV2", ("SEV1", "SEV2", "SEV3")),
        Ask("category", "Category (e.g. wrong_content)", "text", "wrong_content"),
        Ask("commander", "Incident commander (name or role)", "text", "incident commander"),
        Ask("communications_lead", "Communications lead (name or role)", "text", "communications lead"),
        Ask("declared_at", "Time declared (Enter = now)", "time", 0),
        Ask("acknowledged_at", "Time acknowledged (Enter = now)", "time", 0.5),
        Ask("contained_at", "Time contained (Enter = now)", "time", 2),
        Ask("affected_licences", "Affected licence ids (comma list)", "list", "lic-test-1"),
        Ask("offline_licences", "Which of those are offline (comma list)", "list", "lic-test-1"),
        Repeat(
            "receipts",
            "Licence {licence_id}",
            (
                Ask(
                    "recipient_kind",
                    "Who was contacted",
                    "choice",
                    "registered_contact",
                    ("registered_contact", "other"),
                ),
                Ask("route", "First contact route", "choice", "phone", ("phone", "sms", "email", "other")),
                Ask("first_contact_at", "Time of the first contact (Enter = now)", "time", 3),
                Ask("email_at", "Time the email was sent (Enter = now)", "time", 4),
                Ask("kit_id", "USB kit id named as bringing the fix", "text", "kit-dry"),
                Ask("instructions", "What they were told to do (short)", "text", "keep using offline; install kit"),
                Ask("receipt", "Path to the call log, SMS receipt or sent email", "proof"),
            ),
            presets=lambda a, cfg: [{"licence_id": licence} for licence in a["affected_licences"]],
            template={"licence_id": f"{FILL_IN}: one affected licence"},
        ),
    ),
    targets=("ops_school_notice_hours",),
    build=_ops32,
)


# ---------------------------------------------------------------------------------------------------- OPS-34
def _ops34(a: Answers, cfg: Settings, previous: dict[str, Any]) -> dict[str, Any]:
    drill = {
        "name": a["name"],
        "owner": a["owner"],
        "at": a["at"],
        "passed": a["passed"],
        "evidence_sha256": a["evidence"],
        "trigger": a["trigger"],
        "steps": a["steps"],
        "verification": a["verification"],
        "rollback": a["rollback"],
        "offline_copy": a["offline_copy"],
        "actions": [{"description": x["description"], "owner": x["owner"], "due": x["due"]} for x in a["actions"]],
    }
    return {
        "ops34_drills_current": {
            "term_start": a["term_start"],
            "release_at": a["release_at"],
            "drills": [*previous.get("drills", []), drill],
        }
    }


OPS34 = Drill(
    id="ops34",
    title="One runbook drill, added to the drill log",
    requirements="OPS-34 (with OPS-30, SEC-16, SEC-26)",
    tests=("ops34_drills_current",),
    who="The runbook's owner (release manager, Curriculum lead, Engine lead, Security lead, Safety lead, cloud "
    "on-call, Platform lead or Support lead) and whoever the runbook involves.",
    steps=(
        "Pick the runbook; `evidence targets` lists every runbook and how often it must be drilled.",
        "Trigger it as the runbook says, follow its steps from the offline copy, verify, and roll back.",
        "If it failed, write the follow-up actions with an owner and due date.",
        "Run this checklist once per runbook drill; it adds the drill to the log for this candidate.",
    ),
    asks=(
        Ask(
            "term_start",
            "Start of the current school term (date-time with zone, e.g. 2026-09-07T00:00:00+01:00)",
            "time",
            -2000,
        ),
        Ask("release_at", "Time this release candidate was cut (date-time with zone)", "time", -100),
        Ask(
            "name",
            "Runbook drilled",
            "choice",
            "release",
            tuple(sorted({**inc.DRILLS, "lan_restore": "", "web_rollback": ""})),
        ),
        Ask("owner", "Runbook owner (name or role)", "text", "release manager"),
        Ask("at", "Time of the drill (Enter = now)", "time", 0),
        Ask("passed", "Did the drill pass?", "yes", True),
        Ask("trigger", "What triggered it (short)", "text", "scheduled drill"),
        Ask("steps", "Steps followed (comma list of short step names)", "list", "halt,verify,resume"),
        Ask("verification", "How success was verified (short)", "text", "monitor showed halt"),
        Ask("rollback", "How it was rolled back (short)", "text", "resume offers"),
        Ask("offline_copy", "Where the offline copy of the runbook is kept", "text", "on-call USB"),
        Ask("evidence", "Path to the drill record (log, notes or recording)", "proof"),
        Repeat(
            "actions",
            "Follow-up action",
            (
                Ask("description", "Action", "text", "fix the runbook step"),
                Ask("owner", "Owner", "text", "release manager"),
                Ask("due", "Due (date-time with zone)", "time", 1000),
            ),
        ),
    ),
    targets=("ops_drill_quarter_days", "ops_drill_halfyear_days", "ops_drill_year_days"),
    build=_ops34,
    append=True,
)


DRILLS: dict[str, Drill] = {
    d.id: d
    for d in (OPS07, OPS11, OPS12, OPS15, OPS17_SLO, OPS17_WORDS, OPS18, OPS20, OPS21, OPS25, UXS46, WRONG_KEY,
              TABLETOP, OPS32, OPS34)
}  # fmt: skip


def drill_for(test_name: str) -> Drill:
    for drill in DRILLS.values():
        if test_name in drill.tests:
            return drill
    raise KeyError(test_name)
