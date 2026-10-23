"""EVL-22, BIZ-12..16, PRD-08, PRD-18..19, PRD-22: pilot evidence and reports."""

from __future__ import annotations

import hashlib
import math
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_core.config import Settings
from agent_core.config.pilot import COUNTRY_FIELDS as COUNTRY_FIELDS
from agent_core.config.pilot import missing as missing_country
from agent_core.config.telemetry_schema import schema
from agent_core.trace.research import project, statistic
from jsonschema import Draft202012Validator

PILOT_FIELDS = (
    "schools",
    "classes",
    "duration",
    "measures",
    "consent",
    "data",
    "support",
    "commercial_terms",
    "launch_criteria",
    "outcome",
    "power_analysis",
    "analysis_model",
    "dosage",
    "stopping_rules",
    "parallel_forms",
    "report_effects_and_intervals",
    "term_topics",
    "retention",
)
BUSINESS_METRICS = {
    "subscription_start_rate": "billing",
    "weekly_active_students": "research_export",
    "active_days_per_week": "research_export",
    "items_per_active_student": "research_export",
    "mastered_kcs_per_active_student": "research_export",
    "free_to_paid_conversion": "billing_and_telemetry",
    "family_subscription_renewal": "billing",
    "school_seat_renewal": "licence_contracts",
    "cloud_gross_margin": "billing_and_invoices",
    "family_acquisition_cost": "finance",
    "school_acquisition_cost": "finance",
    "support_load": "support",
}


def country_errors(record: dict[str, Any]) -> list[str]:
    from jana_tools.evidence.placeholders import placeholder_errors

    return [f"PRD-22: missing or invalid {item}" for item in missing_country(record)] + placeholder_errors(
        "PRD-22", record
    )


def moment(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("timestamp needs timezone")
    return result


def protocol_errors(record: dict[str, Any], settings: Settings | None = None) -> list[str]:
    settings = settings or Settings()
    from .records import errors as record_errors

    malformed = record_errors("protocol", record)
    if malformed:
        return ["EVL-22 BIZ-15: " + error for error in malformed]
    errors: list[str] = []
    for name in PILOT_FIELDS:
        if not isinstance(record.get("design", {}).get(name), str) or not record["design"][name].strip():
            errors.append(f"BIZ-15: missing {name}")
    try:
        if not moment(record["registered_at"]) < moment(record["baseline_at"]) <= moment(record["starts_at"]):
            errors.append("EVL-22: registration must precede baseline")
        script = record["analysis_script"]
        if hashlib.sha256(Path(script["path"]).read_bytes()).hexdigest() != script["sha256"]:
            errors.append("EVL-22: analysis script differs from registration")
    except (KeyError, TypeError, ValueError, OSError):
        errors.append("EVL-22: missing registration or frozen analysis script")
    if not record.get("id") or not re.fullmatch(r"[A-Z]{2}", str(record.get("country", ""))):
        errors.append("EVL-22: missing study identity or country")
    weeks = record.get("weeks")
    if type(weeks) is not int or not settings.pilot_min_weeks <= weeks <= settings.pilot_max_weeks:
        errors.append("BIZ-15: duration outside pilot policy")
    effect = record.get("minimum_effect_sd")
    if (
        not isinstance(effect, (int, float))
        or isinstance(effect, bool)
        or not math.isfinite(effect)
        or effect < settings.pilot_min_effect_sd
    ):
        errors.append("EVL-22: invalid minimum effect")
    if type(record.get("classes")) is not int or record["classes"] <= 0 or record.get("cluster") != "class":
        errors.append("EVL-22: missing clustered power design")
    for name in ("comparison_access_after", "school_approval", "guardian_research_consent", "student_assent"):
        if record.get(name) is not True:
            errors.append(f"EVL-22: missing {name}")
    return errors


def study_dataset(students: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for student in students:
        if (
            not all(
                student.get(flag) is True
                for flag in ("guardian_consent", "student_assent", "school_approval", "research_use")
            )
            or student.get("withdrawn") is not False
        ):
            continue
        result.append({"study_id": str(uuid4()), **project(student)})
    return result


def wtp_errors(record: dict[str, Any], settings: Settings | None = None) -> list[str]:
    from .records import errors as record_errors

    malformed = record_errors("wtp", record)
    if malformed:
        return ["BIZ-13: " + error for error in malformed]
    settings = settings or Settings()
    errors: list[str] = []
    if record.get("decision") != "D10" or not record.get("report_ref") or not record.get("country"):
        errors.append("BIZ-13: missing D10 research link")
    for name, minimum in (("parents", settings.wtp_parent_min), ("school_owners", settings.wtp_school_owner_min)):
        if type(record.get(name)) is not int or record[name] < minimum:
            errors.append(f"BIZ-13: insufficient {name}")
    if not {"van_westendorp", "gabor_granger"} <= set(record.get("methods", [])):
        errors.append("BIZ-13: missing research methods")
    if not {"lesson_teachers", "exam_books", "elearning"} <= set(record.get("comparisons", [])):
        errors.append("BIZ-13: missing spending comparisons")
    return errors


def experiment_errors(register: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for experiment in register:
        from .records import errors as record_errors

        malformed = record_errors("experiment", experiment)
        if malformed:
            errors.extend("BIZ-14: " + error for error in malformed)
            continue
        if experiment.get("audience") != "adults" or experiment.get("uses_student_data") is not False:
            errors.append("BIZ-14: invalid audience or pricing data")
        if experiment.get("tax_inclusive") is not True or experiment.get("auto_renew_opt_in") is not True:
            errors.append("BIZ-14: tax/renewal evidence missing")
        if not re.fullmatch(r"[A-Z]{3}", str(experiment.get("currency_code", ""))) or not all(
            experiment.get(k) for k in ("country", "currency_symbol", "results_ref")
        ):
            errors.append("BIZ-14: currency, country or results missing")
        try:
            if date.fromisoformat(experiment["starts_at"]) >= date.fromisoformat(experiment["ends_at"]):
                errors.append("BIZ-14: invalid dates")
        except (KeyError, ValueError, TypeError):
            errors.append("BIZ-14: missing dates")
        arms = experiment.get("arms", [])
        builds = {arm.get("learning_build") for arm in arms}
        if len(arms) < 2 or len(builds) != 1 or not re.fullmatch(r"[a-f0-9]{40}", str(next(iter(builds), ""))):
            errors.append("BIZ-14: learning build must be identical across arms")
        for arm in arms:
            price = arm.get("price")
            if not arm.get("id") or type(price) not in (int, float) or not math.isfinite(price) or price < 0:
                errors.append("BIZ-14: invalid arm")
    return errors


def _window(window: dict[str, str]) -> dict[str, str]:
    if set(window) != {"from", "to"} or date.fromisoformat(window["from"]) >= date.fromisoformat(window["to"]):
        raise ValueError("invalid reporting window")
    return dict(window)


def product_report(raw: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    if raw.get("source") not in ("research_export", "evaluation", "on_device"):
        raise ValueError("PRD-18: invalid source for learning statistics")
    settings = settings or Settings()
    window = _window(raw["window"])
    if not re.fullmatch(r"[a-f0-9]{40}", str(raw.get("build", ""))):
        raise ValueError("PRD-18: candidate build missing")
    count_keys = (
        "participants",
        "active_students",
        "newly_mastered_kcs",
        "guided_items",
        "answer_leaks",
        "unchecked_numbers",
        "critical_safety_failures",
        "completed_items",
        "bottom_out_hints",
        "activities_blocked",
    )
    if any(type(raw.get(key)) is not int or raw[key] < 0 for key in count_keys):
        raise ValueError("PRD-18: missing or invalid evidence counts")
    if (
        raw["active_students"] > raw["participants"]
        or raw["answer_leaks"] > raw["guided_items"]
        or (raw["bottom_out_hints"] > raw["completed_items"])
    ):
        raise ValueError("PRD-18: inconsistent counts")

    def measure(name: str, numerator: int, denominator: int) -> dict[str, Any]:
        summary = statistic(raw["participants"], numerator, settings)
        if not summary["suppressed"]:
            summary["value"] = numerator / denominator if denominator else None
        return {**summary, "name": name, "window": window, "source": raw["source"], "build": raw["build"]}

    north = measure("mastered_kcs_per_active_student", raw["newly_mastered_kcs"], raw["active_students"])
    guards = [
        measure(name, raw[name], denominator)
        for name, denominator in (
            ("answer_leaks", raw["guided_items"]),
            ("unchecked_numbers", 1),
            ("critical_safety_failures", 1),
            ("bottom_out_hints", raw["completed_items"]),
            ("activities_blocked", 1),
        )
    ]
    permitted = (
        all(
            raw[key] == 0
            for key in ("answer_leaks", "unchecked_numbers", "critical_safety_failures", "activities_blocked")
        )
        and raw.get("activity_scenarios_passed") is True
    )
    blockers = []
    if (
        raw["participants"] < settings.research_min_participants
        or not raw["active_students"]
        or not raw["guided_items"]
        or not raw["completed_items"]
    ):
        blockers.append("PRD-18: insufficient evidence")
    if settings.product_bottom_out_share_max < 0:
        blockers.append("PRD-18: bottom-out guardrail policy missing")
    elif (
        raw["completed_items"]
        and raw["bottom_out_hints"] / raw["completed_items"] > settings.product_bottom_out_share_max
    ):
        blockers.append("PRD-18: bottom-out guardrail breached")
    permitted = permitted and not blockers
    return {
        "window": window,
        "north_star": north,
        "guardrails": guards,
        "release_allowed": permitted,
        "blocking": blockers,
        "bottom_out_review_required": True,
    }


def business_report(
    values: dict[str, Any], *, window: dict[str, str], settings: Settings | None = None
) -> dict[str, Any]:
    window = _window(window)
    settings = settings or Settings()
    metrics = {}
    for name, source in BUSINESS_METRICS.items():
        raw = values.get(name, {})
        sample = raw.get("sample_size", 0)
        valid = type(sample) is int and sample >= 0
        value = None
        status = "missing"
        if valid and sample:
            numerator, denominator = raw.get("numerator"), raw.get("denominator")
            if name == "weekly_active_students" and type(numerator) is int and numerator >= 0:
                value = numerator
            elif name == "active_days_per_week" and raw.get("days"):
                days = raw["days"]
                if all(type(n) is int and 0 <= n <= 7 for n in days) and len(days) == sample:
                    value = statistics.median(days)
            elif (
                type(numerator) in (int, float)
                and type(denominator) in (int, float)
                and (math.isfinite(numerator) and math.isfinite(denominator) and denominator > 0)
            ):
                value = numerator / denominator
                if name == "support_load":
                    value *= 100
            if value is not None:
                status = "measured"
            if source == "research_export" and sample < settings.research_min_participants:
                value, status = None, "suppressed"
        metrics[name] = {
            "value": value,
            "sample_size": sample if valid else 0,
            "window": window,
            "source": source,
            "status": status,
        }
    Draft202012Validator.check_schema(schema())
    return {"window": window, "metrics": metrics, "telemetry_schema_valid": True}
