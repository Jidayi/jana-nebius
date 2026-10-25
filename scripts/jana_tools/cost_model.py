"""The cloud cost model (BIZ-08, LIST BIZ-08a): cloud inference per active student per month from measured inputs.

Inputs come from measurement, never from guesses: the per-role calls per turn, input and output tokens and
prompt-cache hit share are read from the evaluation harness's turn traces (each model call records its role,
provider kind and token counts), and provider prices come from the price table the device meters with
(`agent_core/router/cloud_models.json`, D7). Usage variables (share routed to the cloud `A`, turns per student per
month `T`, photos `V`) come from pilot data and default to the proposals of TABLE BIZ-08b until measured.

The price and the gross margin are the gateway's: the price is the lowest a covered student's month brings in across
TABLE BIZ-18a's regional plans (`cloud_gateway.tier.allowance_basis_usd`, D121, superseding D10's single price; a term
is three months prepaid, D33) and the margin is `cloud_gateway.config.Tier`'s BIZ-08 key, so the allowance this review
computes is the one the gateway enforces and the checkout signs: one source of truth, and a plan below the floor fails
the review.

`workbook` returns every figure the finance review reads, and `errors` lists inputs that are older than the
current model release, and a decided price below the formula-4 floor: the review fails while any remain (recompute
whenever a price, model or prompt budget changes)."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloud_gateway.config import Tier, load_config
from cloud_gateway.tier import allowance_basis_usd

from . import REPO_ROOT

PRICES = REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "cloud_models.json"


@dataclass(frozen=True)
class RoleInputs:
    calls_per_turn: float  # k_r
    input_tokens: float  # i_r
    cache_hit: float  # h_r
    output_tokens: float  # o_r


@dataclass(frozen=True)
class Usage:
    """TABLE BIZ-08b's usage variables (proposals until pilot data replaces them)."""

    cloud_share: float = 1.0  # A
    turns_per_month: float = 200.0  # T
    photos_per_month: float = 0.0  # V


# TABLE BIZ-08b's per-role proposals for the first estimate (BIZ-08), used until pilot traces replace them; `DECLARED`
# names each proposal for the proposals check, as configuration keys are named. The gross margin is not one of them:
# it is the gateway's `Tier.gross_margin` key, read with the decided price by `tier()`.
PROPOSED_ROLE_INPUTS = RoleInputs(calls_per_turn=3.0, input_tokens=3000.0, cache_hit=0.6, output_tokens=250.0)
DECLARED: dict[str, str] = {
    "usage.turns_per_month": "BIZ-08",
    "usage.cloud_share": "BIZ-08",
    "role.calls_per_turn": "BIZ-08",
    "role.input_tokens": "BIZ-08",
    "role.cache_hit": "BIZ-08",
    "role.output_tokens": "BIZ-08",
}


def tier(deployment: Path | None = None) -> Tier:
    """The online tier's gross margin and usage mix, from the gateway's configuration (its packaged defaults, or a
    deployment file over them): the one place they are set."""
    return load_config(deployment).tier


def decided_price(deployment: Path | None = None) -> float:
    """US$ the lowest-priced covered student's month brings in across TABLE BIZ-18a (D121): the price every plan's
    allowance must be kept at."""
    return allowance_basis_usd(load_config(deployment))


def measure(traces: Iterable[Mapping[str, Any]]) -> dict[str, RoleInputs]:
    """Per role, from turn traces: calls per turn, mean input and output tokens, and the cached share of input."""
    turns = 0
    calls: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trace in traces:
        turns += 1
        for call in trace.get("model_calls", []):
            calls[str(call["role"])].append(call)
    measured = {}
    for role, made in calls.items():
        inputs = sum(int(c["tokens"]["input"]) for c in made)
        cached = sum(int(c["tokens"].get("cache_read", 0)) for c in made)
        measured[role] = RoleInputs(
            calls_per_turn=len(made) / max(turns, 1),
            input_tokens=inputs / len(made),
            cache_hit=cached / inputs if inputs else 0.0,
            output_tokens=sum(int(c["tokens"]["output"]) for c in made) / len(made),
        )
    return measured


def measure_sketches(outcomes: Iterable[Mapping[str, Any]], online_turns: int) -> RoleInputs | None:
    """MDL-33: the sketch calls as their own line, from the engine's `sketch.outcome` records (each call's tokens) and
    the number of online turns they came from: the measured share of online turns with a sketch call."""
    made = [o for o in outcomes if isinstance(o.get("tokens"), Mapping)]
    if not made or online_turns <= 0:
        return None
    inputs = sum(int(o["tokens"]["input"]) for o in made)
    cached = sum(int(o["tokens"].get("cache_read", 0)) for o in made)
    return RoleInputs(calls_per_turn=len(made) / online_turns, input_tokens=inputs / len(made),
                      cache_hit=cached / inputs if inputs else 0.0,
                      output_tokens=sum(int(o["tokens"]["output"]) for o in made) / len(made))  # fmt: skip


def c_cloud(roles: Mapping[str, RoleInputs], usage: Usage, p_in: float, p_out: float, cached_multiplier: float,
            p_img: float = 0.0) -> float:  # fmt: skip
    """Formula 1: A · T · Σ_r k_r · [(i_r·(1 - h_r) + i_r·h_r·m) · p_in + o_r · p_out] + V · p_img (USD per token)."""
    per_turn = sum(
        r.calls_per_turn
        * ((r.input_tokens * (1 - r.cache_hit) + r.input_tokens * r.cache_hit * cached_multiplier) * p_in
           + r.output_tokens * p_out)
        for r in roles.values()
    )  # fmt: skip
    return usage.cloud_share * usage.turns_per_month * per_turn + usage.photos_per_month * p_img


def price_floor(c_cloud_p90: float, margin: float) -> float:
    """Formula 4: P_cloud ≥ C_cloud(p90 student) / (1 - g)."""
    return c_cloud_p90 / (1 - margin)


def allowance_tokens(price: float, margin: float, blended_per_token: float) -> float:
    """Formula 5: Allowance_tokens = P_cloud · (1 - g) / p_blend."""
    return price * (1 - margin) / blended_per_token


def load_prices(path: Path = PRICES) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def workbook(traces: list[Mapping[str, Any]], *, model: str, usage: Usage, cached_multiplier: float,
             measured_release: str, prices: Mapping[str, Any] | None = None, p90_factor: float = 1.0,
             online_tier: Tier | None = None, price_usd: float | None = None,
             sketch_outcomes: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """The cost figures for one cloud model alias at the decided price and margin (`price_usd` and `online_tier`, by
    default the gateway's), and the review's errors. Sketch calls (MDL-33), measured from the engine's
    `sketch.outcome` records over the traced turns, are their own line, `sketch`."""
    decided = online_tier if online_tier is not None else tier()
    price = price_usd if price_usd is not None else decided_price()
    margin = decided.gross_margin
    table = prices or load_prices()
    row = table["models"][model]
    p_in, p_out = float(row["price_in_per_mtok"]) / 1e6, float(row["price_out_per_mtok"]) / 1e6
    roles = measure(traces)
    sketches = measure_sketches(sketch_outcomes or [], len(traces))
    if sketches is not None:
        roles["sketch"] = sketches
    cost = c_cloud(roles, usage, p_in, p_out, cached_multiplier)
    tokens_in = sum(r.calls_per_turn * r.input_tokens for r in roles.values())
    tokens_out = sum(r.calls_per_turn * r.output_tokens for r in roles.values())
    blended = (tokens_in * p_in + tokens_out * p_out) / (tokens_in + tokens_out) if tokens_in + tokens_out else 0.0
    floor = price_floor(cost * p90_factor, margin)
    errors = []
    if not traces:
        errors.append("no measured traces: the cost model needs the evaluation harness's token counts")
    current = str(table.get("release", ""))
    if not current or measured_release < current:
        errors.append(f"inputs measured for release {measured_release!r} are older than the current model release "
                      f"{current!r}: recompute (BIZ-08)")  # fmt: skip
    if traces and price < floor:
        errors.append(f"the decided price US${price:g} is below the formula-4 floor US${floor:.2f} at this margin: the "
                      "allowance cannot be kept (BIZ-08)")  # fmt: skip
    return {
        "model": model,
        "roles": {r: vars(v) for r, v in roles.items()},
        "c_cloud_usd_per_student_month": cost,
        "c_local_usd": 0.0,
        "price_usd_per_student_month": price,
        "gross_margin": margin,
        "price_floor_usd": floor,
        "allowance_tokens": allowance_tokens(price, margin, blended) if blended else 0.0,
        "errors": errors,
    }
