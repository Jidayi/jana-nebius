"""VER-30: `stats_distribution`, the A level statistics checker, through the real fn.call boundary: every golden case
with its pinned fingerprint, conventions from the call, then the pack, then the tool default, undetermined input as
`unknown` and contradictory input refused as a domain error with no number."""

from __future__ import annotations

import io
import json
from typing import Any

from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.protocol import Code
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000001"
TOOL = "stats_distribution"
TASKS = {"binomial", "poisson", "normal", "hypothesis_test", "correlation", "regression"}
TESTS = {"binomial", "poisson", "normal_mean", "pmcc", "spearman"}


def call(args: dict[str, Any], conventions: dict[str, Any] | None = None) -> dict[str, Any]:
    """One fn.call through the worker's server code, in process: the reply frame."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params: dict[str, Any] = {"call_id": "c", "name": TOOL, "version": FUNCTIONS[TOOL].version, "args": args,
                              "check_id": CHECK, "deadline_ms": 15000}  # fmt: skip
    if conventions:
        params["conventions"] = conventions
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    return next(r for r in map(json.loads, out.getvalue().splitlines()) if r.get("id") == "1")


def result(args: dict[str, Any], conventions: dict[str, Any] | None = None) -> dict[str, Any]:
    reply = call(args, conventions)
    assert "result" in reply, reply
    found: dict[str, Any] = reply["result"]
    assert found["check"]["check_id"] == CHECK and found["check"]["function"] == TOOL
    return found


def refused(args: dict[str, Any], code: int = Code.DOMAIN_ERROR) -> str:
    reply = call(args)
    assert "result" not in reply and reply["error"]["code"] == code, reply
    return str(reply["error"]["message"])


def outcome(reply: dict[str, Any]) -> Any:
    """The value, or the refusal as golden.run records it."""
    if "result" in reply:
        return reply["result"]["value"]
    return {"error": reply["error"]["code"], "message": reply["error"]["message"]}


def test_ver30_statistics_golden_cases_through_fn_call() -> None:
    data = golden.load()[TOOL]
    assert data["tool"] == TOOL and data["stage"] == "S3" and len(data["cases"]) >= 100
    pinned = json.loads(golden.FINGERPRINTS.read_text())
    failures, drifted, tasks, tests = [], [], set(), set()
    for case in data["cases"]:
        reply = call(case["args"])
        value = outcome(reply)
        if not golden.matches(value, case["expect"]):
            failures.append(case["id"])
        if golden.result_sha256(value) != pinned[case["id"]]:
            drifted.append(case["id"])
        if "result" in reply:
            assert reply["result"]["check"]["result_sha256"] == golden.result_sha256(value), case["id"]
            assert all(line["check_id"] == CHECK for line in reply["result"].get("working", [])), case["id"]
        tasks.add(case["args"]["task"])
        if case["args"]["task"] == "hypothesis_test":
            tests.add(case["args"]["test"])
    assert failures == []
    assert drifted == []
    assert tasks == TASKS and tests == TESTS  # every topic of VER-30's statistics is in the set
    kinds = {"error" if "error" in c["expect"] else c["expect"].get("status", "answer") for c in data["cases"]}
    assert kinds == {"answer", "unknown", "error"}
    errors = [c for c in data["cases"] if "error" in c["expect"]]
    assert data["cases"][-len(errors) :] == errors  # refusals sorted last


def test_ver30_binomial_is_an_exact_fraction() -> None:
    found = result({"task": "binomial", "n": 10, "p": "0.5", "relation": "between", "k": 4, "k2": 6, "sf": 4})
    value = found["value"]
    # C(10,4) + C(10,5) + C(10,6) = 210 + 252 + 210 = 672 of 1024.
    assert value["probability"]["text"] == "21/32" and value["probability"]["decimal"] == "0.6563"
    assert value["interval"] == [4, 6] and value["mean"]["text"] == "5" and value["sd"]["text"] == "sqrt(10)/2"
    assert (found["check"]["method"], found["check"]["confidence"]) == ("exact", "proved")
    assert "warnings" not in found


def test_ver30_rounding_conventions_call_then_pack_then_default() -> None:
    args = {"task": "poisson", "lambda": 3, "relation": "le", "k": 2}
    default = result(args)
    assert default["value"]["conventions"]["sf"] == {"value": 4, "source": "default"}
    assert [w["code"] for w in default["warnings"]] == ["convention_default_used"]
    assert default["value"]["probability"]["decimal"] == "0.4232"
    pack = result(args, {"numeric.sf": {"value": 3, "source": "pack"}})
    assert pack["value"]["conventions"]["sf"] == {"value": 3, "source": "pack"} and "warnings" not in pack
    assert pack["value"]["probability"]["decimal"] == "0.423"
    stated = result(args | {"sf": 5}, {"numeric.sf": {"value": 3, "source": "pack"}})
    assert stated["value"]["probability"]["decimal"] == "0.42319"
    # Rounding never changes the exact value.
    assert {default["value"]["probability"]["text"], pack["value"]["probability"]["text"]} == {"17*exp(-3)/2"}


def test_ver30_normal_tables_and_calculator() -> None:
    args = {"task": "normal", "mean": 50, "sd": 4, "relation": "gt", "x": "54.5", "sf": 4}
    calculator = result(args)
    assert calculator["check"]["method"] == "symbolic"
    assert calculator["value"]["probability"]["decimal"] == "0.1303"  # 1 - Phi(1.125)
    assert calculator["value"]["conventions"]["normal_values"]["source"] == "default"
    tables = result(args, {"stats.normal_values": {"value": "tables", "source": "pack"}})
    assert tables["check"]["method"] == "table_lookup" and "warnings" not in tables
    # The table reads z = 1.13 (2 d.p.) and Phi(1.13) = 0.8708.
    assert tables["value"]["z"]["text"] == "113/100" and tables["value"]["probability"]["text"] == "323/2500"
    inverse = result({"task": "normal", "find": "value", "mean": 0, "sd": 1, "probability": "0.01", "tail": "above",
                      "normal_values": "tables"})  # fmt: skip
    assert inverse["value"]["x"]["text"] == "23263/10000"  # the percentage point 2.3263


def test_ver30_unknown_mean_and_sd_from_two_probabilities() -> None:
    # P(X < 40) = 0.1 and P(X > 70) = 0.05 with the table's z = -1.2816 and 1.6449.
    found = result(
        {
            "task": "normal",
            "find": "mean_and_sd",
            "normal_values": "tables",
            "sf": 4,
            "conditions": [
                {"x": 40, "probability": "0.1", "tail": "below"},
                {"x": 70, "probability": "0.05", "tail": "above"},
            ],
        }
    )
    value = found["value"]
    assert [z["text"] for z in value["z"]] == ["-801/625", "16449/10000"]
    assert (value["mean"]["decimal"], value["sd"]["decimal"]) == ("53.14", "10.25")


def test_ver30_two_tailed_test_halves_the_level() -> None:
    args = {"task": "hypothesis_test", "test": "binomial", "n": 20, "p": "0.3", "significance_level": "0.05",
            "observed": 2, "sf": 4}  # fmt: skip
    one = result(args | {"alternative": "less"})["value"]
    two = result(args | {"alternative": "two_sided"})["value"]
    # P(X <= 2) = 0.03548: below 0.05 one-tailed, above 0.025 two-tailed.
    assert (one["tail_probability"]["decimal"], one["compare_with"], one["conclusion"]) == ("0.03548", "1/20",
                                                                                            "reject_h0")  # fmt: skip
    assert (two["compare_with"], two["conclusion"]) == ("1/40", "do_not_reject_h0")
    assert two["critical_region"]["lower"]["x_max"] == 1 and two["critical_region"]["upper"]["x_min"] == 11
    assert two["h1"] == "p != 3/10"


def test_ver30_pmcc_critical_value_from_the_call_or_computed() -> None:
    args = {"task": "hypothesis_test", "test": "pmcc", "r": "0.6", "n": 10, "alternative": "greater",
            "significance_level": "5%", "sf": 4}  # fmt: skip
    computed = result(args)
    critical = computed["value"]["critical_value"]
    assert critical["decimal"] == "0.5494" and "text" not in critical  # a computed decimal has no exact form
    assert [w["code"] for w in computed["warnings"]] == ["numeric_only"]
    given = result(args | {"critical_value": "0.6319"})
    assert given["check"]["method"] == "table_lookup" and given["value"]["conclusion"] == "do_not_reject_h0"
    # From data: r is exact.
    data = result({"task": "hypothesis_test", "test": "pmcc", "x_values": [1, 2, 3, 4, 5], "y_values": [2, 4, 5, 4, 5],
                   "alternative": "greater", "significance_level": "0.05"})  # fmt: skip
    assert data["value"]["r"]["text"] == "sqrt(15)/5" and data["value"]["n"] == 5


def test_ver30_regression_flags_extrapolation() -> None:
    found = result({"task": "regression", "x_values": [1, 2, 3, 4, 5], "y_values": [2, 4, 5, 4, 5],
                    "predict": [3, 10]})  # fmt: skip
    value = found["value"]
    assert value["equation"] == "y = 3*x/5 + 11/5"
    assert [p["reliability"] for p in value["predictions"]] == ["interpolation", "extrapolation"]
    assert any(w["code"] == "domain_restricted" and "extrapolation" in w["message"] for w in found["warnings"])
    x_on_y = result({"task": "regression", "line": "x_on_y", "x_values": [1, 2, 3, 4, 5],
                     "y_values": [2, 4, 5, 4, 5]})["value"]  # fmt: skip
    assert x_on_y["equation"] == "x = y - 1"  # Sxy / Syy = 6 / 6


def test_ver30_spearman_ties_are_stated() -> None:
    args = {"task": "correlation", "measure": "spearman", "x_values": [1, 2, 2, 4, 5], "y_values": [1, 2, 3, 4, 5]}
    default = result(args)
    spearman = default["value"]["spearman"]
    assert spearman["ties"] is True and spearman["tie_method"] == "pmcc_of_ranks"
    assert any(w["code"] == "convention_default_used" and "spearman_ties" in w["message"] for w in default["warnings"])
    formula = result(args, {"stats.spearman_ties": {"value": "formula", "source": "pack"}})["value"]["spearman"]
    assert formula["rs"]["text"] == "39/40" and formula["sum_d2"] == "1/2"  # 1 - 6 x 0.5 / 120


def test_ver30_unknown_is_undecided_never_a_number() -> None:
    found = result({"task": "hypothesis_test", "test": "spearman", "r": "0.6", "n": 10, "alternative": "greater",
                    "significance_level": "0.05"})  # fmt: skip
    assert found["value"]["status"] == "unknown" and found["value"]["reason"] == "critical_value_needed"
    assert (found["check"]["method"], found["check"]["confidence"]) == ("rule_based", "undecided")
    assert [w["code"] for w in found["warnings"]] == ["convention_missing"]
    assert "critical_value" not in found["value"]


def test_ver30_contradictions_are_refused() -> None:
    assert "probability" in refused({"task": "binomial", "n": 5, "p": "1.5", "relation": "eq", "k": 1})
    assert "|r| > 1" in refused({"task": "correlation", "sums": {"n": 5, "sum_x": 15, "sum_y": 15, "sum_x2": 55,
                                                                 "sum_y2": 46, "sum_xy": 60}})  # fmt: skip
    assert "negative" in refused({"task": "normal", "find": "sd", "mean": 50, "x": 60, "probability": "0.7",
                                  "tail": "above"})  # fmt: skip
    assert "percentage" in refused({"task": "hypothesis_test", "test": "poisson", "lambda": 3, "alternative": "less",
                                    "significance_level": 5})  # fmt: skip


def test_ver30_schema_requires_each_tasks_inputs() -> None:
    invalid = int(Code.INVALID_PARAMS)
    refused({"task": "binomial", "n": 10, "relation": "le", "k": 3}, invalid)  # no p
    refused({"task": "binomial", "n": 10, "p": "0.3", "relation": "le"}, invalid)  # no k
    refused({"task": "normal", "mean": 5, "sd": 1, "variance": 1, "relation": "lt", "x": 6}, invalid)
    sd_given = {"task": "normal", "find": "sd", "mean": 5, "sd": 1, "x": 6, "probability": "0.2", "tail": "above"}
    refused(sd_given, invalid)
    refused({"task": "hypothesis_test", "test": "binomial", "n": 10, "p": "0.3", "alternative": "less"}, invalid)
    refused({"task": "correlation", "x_values": [1, 2, 3]}, invalid)
    refused({"task": "poisson", "lambda": 2, "relation": "eq", "k": 1, "x": 3}, invalid)


def test_ver30_deterministic_bytes() -> None:
    args = {"task": "hypothesis_test", "test": "normal_mean", "mean": 50, "sd": 4, "n": 16, "sample_mean": "51.8",
            "alternative": "two_sided", "significance_level": "0.05"}  # fmt: skip
    first, second = result(args), result(args)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["value"]["z"]["text"] == "9/5" and first["value"]["conclusion"] == "do_not_reject_h0"
