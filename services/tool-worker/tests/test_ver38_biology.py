"""VER-35 and VER-38: `bio_genetics` and `bio_calc` through the real fn.call boundary, results validated against the
science-compute contract, refusals as domain errors with no asserted number."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from tool_worker.contracts.tools.science_compute import BioCalcResult, GeneticsResult
from tool_worker.functions import FUNCTIONS
from tool_worker.protocol import Code
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000001"
TALL = [{"symbol": "A", "phenotype": "tall", "dominance": "dominant"},
        {"symbol": "a", "phenotype": "short", "dominance": "recessive"}]  # fmt: skip
ROUND = [{"symbol": "B", "phenotype": "round", "dominance": "dominant"},
         {"symbol": "b", "phenotype": "wrinkled", "dominance": "recessive"}]  # fmt: skip
ABO = [{"symbol": "IA", "phenotype": "A", "dominance": "codominant"},
       {"symbol": "IB", "phenotype": "B", "dominance": "codominant"},
       {"symbol": "i", "phenotype": "O", "dominance": "recessive"}]  # fmt: skip


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """One fn.call through the worker's server code, in process: the reply frame."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    return next(r for r in map(json.loads, out.getvalue().splitlines()) if r.get("id") == "1")


def value(name: str, args: dict[str, Any]) -> dict[str, Any]:
    reply = call(name, args)
    assert "result" in reply, reply
    result: dict[str, Any] = reply["result"]["value"]
    (GeneticsResult if name == "bio_genetics" else BioCalcResult).model_validate(result)
    assert reply["result"]["check"]["check_id"] == CHECK
    return result


def refused(name: str, args: dict[str, Any]) -> str:
    reply = call(name, args)
    assert "result" not in reply and reply["error"]["code"] == Code.DOMAIN_ERROR, reply
    return str(reply["error"]["message"])


def ratio(rows: list[dict[str, Any]]) -> list[float]:
    smallest = min(r["probability"] for r in rows)
    return [round(r["probability"] / smallest, 9) for r in rows]


def ver35_monohybrid_ratio() -> None:
    cross = value("bio_genetics", {"task": "cross", "parents": ["Aa", "Aa"], "alleles": TALL})
    assert [g["genotype"] for g in cross["genotypes"]] == ["AA", "Aa", "aa"]
    assert ratio(cross["genotypes"]) == [1, 2, 1]
    assert [p["phenotype"] for p in cross["phenotypes"]] == ["tall", "short"] and ratio(cross["phenotypes"]) == [3, 1]
    assert cross["gametes"] == [["A", "a"], ["A", "a"]]


def ver38_biology_contract_cases() -> None:
    # Probabilities sum to 1 within 1e-10: a dihybrid cross gives 9:3:3:1 over 9 genotypes.
    dihybrid = value("bio_genetics", {"task": "cross", "parents": ["AaBb", "AaBb"], "alleles": TALL + ROUND})
    assert len(dihybrid["genotypes"]) == 9 and ratio(dihybrid["phenotypes"]) == [9, 3, 3, 1]
    for table in ("genotypes", "phenotypes"):
        assert abs(sum(r["probability"] for r in dihybrid[table]) - 1) < 1e-10
    # Multiple alleles and codominance, from the declarations alone (IA and IB are read whole, never as I + A).
    blood = value("bio_genetics", {"task": "cross", "parents": ["IAi", "IBi"], "alleles": ABO})
    assert {p["phenotype"]: p["probability"] for p in blood["phenotypes"]} == {"A and B": 0.25, "A": 0.25,
                                                                               "B": 0.25, "O": 0.25}  # fmt: skip
    assert "symbol that is not a declared allele" in refused(
        "bio_genetics", {"task": "cross", "parents": ["Aa", "Ac"], "alleles": TALL}
    )
    assert "two alleles for every locus" in refused(
        "bio_genetics", {"task": "cross", "parents": ["Aa", "AaB"], "alleles": TALL + ROUND}
    )
    assert "declare them codominant" in refused("bio_genetics", {"task": "cross", "parents": ["AB", "AB"], "alleles": [
        {"symbol": "A", "phenotype": "red", "dominance": "dominant"},
        {"symbol": "B", "phenotype": "white", "dominance": "dominant"}]})  # fmt: skip
    # Chi-squared: equal lengths, positive expected counts, matching totals; df = categories - 1.
    chi = value("bio_genetics", {"task": "chi_squared", "observed": [290, 110], "expected": [300, 100]})
    assert chi["statistic"]["value"] == pytest.approx(4 / 3) and chi["degrees_of_freedom"] == 1
    assert "one count per category" in refused("bio_genetics", {"task": "chi_squared", "observed": [1, 2],
                                                                "expected": [1, 1, 1]})  # fmt: skip
    assert "positive" in refused("bio_genetics", {"task": "chi_squared", "observed": [3, 0], "expected": [3, 0]})
    assert "does not match" in refused("bio_genetics", {"task": "chi_squared", "observed": [5, 5],
                                                        "expected": [6, 6]})  # fmt: skip
    # Hardy-Weinberg takes q² and reports q, p, p², 2pq and q², naming its assumptions in the working.
    hw = call("bio_genetics", {"task": "hardy_weinberg", "recessive_frequency": 0.16})["result"]
    assert hw["value"]["frequencies"] == pytest.approx({"p": 0.6, "q": 0.4, "p_squared": 0.36, "two_pq": 0.48,
                                                        "q_squared": 0.16})  # fmt: skip
    assert any("random mating" in w["value"] for w in hw["working"])
    # Calculators: length units converted, zero denominators refused, conventions recorded, recapture bounded.
    magnified = value("bio_calc", {"task": "magnification", "image_length": 20, "image_unit": "mm",
                                   "actual_length": 50, "actual_unit": "um"})  # fmt: skip
    assert magnified["result"]["value"] == 400 and "micrometres" in magnified["convention"]
    assert "from zero" in refused("bio_calc", {"task": "percentage_change", "initial": 0, "final": 5})
    assert value("bio_calc", {"task": "percentage_change", "initial": 40, "final": 50})["result"]["value"] == 25
    rate = value("bio_calc", {"task": "rate", "change": 12, "duration": 4, "unit": "cm3 per minute"})
    assert rate["result"] == {"value": 3, "unit": "cm3 per minute", "check_id": CHECK}
    recapture = value("bio_calc", {"task": "recapture", "marked_first": 40, "second_catch": 30, "marked_second": 6})
    assert recapture["result"]["value"] == 200 and "Lincoln-Petersen" in recapture["convention"]
    assert "cannot exceed" in refused("bio_calc", {"task": "recapture", "marked_first": 5, "second_catch": 30,
                                                   "marked_second": 6})  # fmt: skip
    simpson = value("bio_calc", {"task": "simpson", "counts": [10, 5, 5]})
    assert simpson["result"]["value"] == pytest.approx(1 - (90 + 20 + 20) / (20 * 19))
    assert "1 - sum n(n-1) / N(N-1)" in simpson["convention"]
    assert "at least two" in refused("bio_calc", {"task": "simpson", "counts": [1, 0]})
