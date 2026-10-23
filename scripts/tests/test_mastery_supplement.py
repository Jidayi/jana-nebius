"""Independent arithmetic references for the 2026-10-18 development question supplement.

These checks verify authored keys, not independent curriculum approval. The pack build also checks the
worked steps, hints, rendering, references and licences with the tool-worker implementation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/governance/evidence/mastery-bank-completion-2026-10-18/question-review.json"
QUESTIONS = json.loads(MANIFEST.read_text())["questions"]

# Standard-library arithmetic is separate from the SymPy-backed build and runtime checker.
REFERENCE = {
    9001: 28000 + 300 + (5100 - 4200),
    9002: 36000 - (3100 - 2500) - 200,
    9003: (34000 - 9000 + 3500 - 2000) - (25000 - 7000),
    9004: 95 - 10,
    9005: next(n for n in range(20) if 3 * n - 2 == 10),
    9006: next(n for n in range(1, 100) if 12 + (n - 1) * 4 == 60),
    9007: next(n for n in range(1, 100) if n * n + 3 * n == 40),
    9008: 3 / 12,
    9009: 3 - 0.5 * 6,
    9010: 1,  # Both points satisfy y=3x+1.
    9011: -7,  # (5 + (-7))/2 = -1.
    9012: 3,  # 2y-6x=8 => y=3x+4.
    9013: 1.5,  # (-2/3)*(3/2) = -1.
    9014: next(k for k in range(3, 20) if 6**2 + (k - 2) ** 2 == 10**2),
    9015: (65 + 180) % 360,
    9016: min(abs(315 - 270), 360 - abs(315 - 270)),
    9017: 110,  # Exterior angle of a cyclic quadrilateral equals its opposite interior angle.
    9018: 3000 / 0.06,
    9019: 80 * (6 / 4) ** 2,
    9020: 480 / 24,
    9021: 12 * (1.5 / 2),
    9022: 360 * 12 / 36,
    9023: 2 * 12 + 2 * 8,  # Top and bottom strips include corners; side strips exclude them.
    9024: 6400 / 0.64,
    9025: round(198, -2) * round(4.12),
    9026: round(593, -2) / round(19.6, -1),
    9027: math.lcm(12, 18),
    9029: next(k for k in range(1, 100) if math.isqrt(360 * k) ** 2 == 360 * k),
    9030: (3 * 60) * (10 / 45),
    9031: 68 * 100 / 85,
    9032: (84 - 0.5) / 10,
    9033: 360 * 100 / (4 * 3),
    9034: 600_000_000 / 2000,
    9035: math.floor(math.log10(0.000072)),
    9036: 15 + 80,
    9037: sum([0] * 4 + [1] * 7 + [2] * 5) / 16,
    9038: 31 - 12,
    9039: sum([5] * 6 + [15] * 10 + [25] * 4) / 20,
    9040: 4 * 5,
    9041: 180 / 5,
    9042: -4 - 4,
    9043: next(k for k in range(1, 14) if k * k + 12**2 == 13**2),
    9044: math.dist((7, 0), (8 * math.cos(math.pi / 3), 8 * math.sin(math.pi / 3))),
    9045: 30 * math.cos(math.radians(25)) / math.sin(math.radians(25)),
    9046: 8 * math.sqrt(2),
    9047: math.degrees(math.atan2(10, math.hypot(6, 8))),
    9048: 15 / (0.5 * 5 * 0.5),
    9049: 10 * (10 * 0.5),
    9050: math.degrees(math.atan2(4, 3)),
}


@pytest.mark.parametrize("record", QUESTIONS, ids=lambda r: r["item_id"])
def test_supplement_key_against_reference(record: dict) -> None:
    item = yaml.safe_load((ROOT / record["source"]).read_text())
    key = item["parts"][0]["answer"]
    number = int(item["id"].split(".")[-1])
    assert item["id"] == record["item_id"]
    assert item["kc_ids"] == [record["kc_id"]]
    assert item["review"]["reviewers"] == []
    assert record["independent_curriculum_review"] == "awaiting_approval"
    if key["kind"] == "numeric":
        expected = REFERENCE[number]
        actual = float(key["value"])
        if key["tolerance"]["mode"] == "sig_figs":
            assert f"{actual:.3g}" == f"{expected:.3g}"
        else:
            assert actual == pytest.approx(expected, abs=1e-6, rel=0)
    elif key["kind"] == "ordering":
        lengths_cm = {"e1": 0.48 * 100, "e2": 47, "e3": 0.5 * 100, "e4": 490 / 10}
        assert key["correct_order"] == sorted(lengths_cm, key=lengths_cm.get)
    else:
        # Explicit intended conceptual answers; pedagogical approval remains a separate review.
        correct = [o["id"] for o in key["options"] if o["correct"]]
        assert correct == [{9051: "B", 9052: "C", 9053: "A"}[number]]
        assert key["diagnostic"] is False
        assert len({o["text"] for o in key["options"]}) == 4


def test_supplement_fills_every_reported_slot_without_human_approval_claim() -> None:
    baseline = json.loads(
        (
            ROOT / "scripts/governance/evidence/mastery-all-subjects-2026-10-18/content-bank-requirements.json"
        ).read_text()
    )
    from collections import Counter

    assert len(QUESTIONS) == 53
    assert len({r["item_id"] for r in QUESTIONS}) == 53
    assert Counter(r["kc_id"] for r in QUESTIONS) == {
        b["kc_id"]: b["minimum_additional_unreserved_surfaces"] for b in baseline["banks"]
    }
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["independent_curriculum_review"] == "awaiting_approval"
    assert manifest["release_approval"] == "not_granted"
