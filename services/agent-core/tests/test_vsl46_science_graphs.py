"""The A level science and statistics graphs in the engine (VSL-07, VSL-46): exponential_curve, distribution_curve and
data_plot resolve through their contract schemas with every drawn figure from a tool, refuse a request their rules
forbid (a reversed range, a mark off the axes, a fractional or impossible outcome, a constant x), and the A level kinds
stay out of O level sessions."""

from fractions import Fraction

import pytest
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, validate
from agent_core.contracts import errors as contract_errors
from jana_tools.visual_fixtures import _call


def _resolve(kind: str, params: dict, subject: str = "mathematics", level: str = "A", **extra) -> dict:
    ctx = VisualContext(subject, level, "S3", knowns=extra.pop("knowns", {}))
    request = {"spec_version": 1, "type": kind, "params": params, **extra}
    resolved, _ = validate(request, ctx, Resolver(resolver(_call("vsl46g"), ctx.conventions)))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    return resolved


def _refused(kind: str, params: dict, code: str = "visual_resolution_failed", **extra) -> None:
    with pytest.raises(VisualError) as error:
        _resolve(kind, params, **extra)
    assert error.value.code == code, params


DECAY = {
    "initial": 800,
    "constant": 0.2,
    "mode": "decay",
    "time_range": [0, 20],
    "time_unit": "s",
    "quantity_unit": "Bq",
    "mark": "half_life",
}


def test_vsl46_exponential_curve_resolution():
    resolved = _resolve("exponential_curve", DECAY, "physics")
    computed = resolved["computed"]
    # t½ = ln 2 / 0.2 = 3.47 s, where 800 Bq has fallen to 400 Bq (math_evaluate); the curve from math_plot_points.
    assert computed["labels"] == {"half_life": "3.47", "half_life.value": "400"}
    assert computed["mark"] == {"t": 3.46574, "value": 400.0}
    assert computed["curve"][0] == [0.0, 800.0] and computed["curve"][-1][0] == 20.0
    assert len(resolved["numbers_from"]) == 3
    assert [p["id"] for p in resolved["parts"]] == ["curve", "half_life"]
    assert "The half-life is 3.47 s, where the value is 400 Bq." in resolved["alt"]["summary"]
    # Charging: the time constant 1/k = 2 s, where 6 V has risen to 6(1 - 1/e) = 3.79 V.
    charge = {**DECAY, "initial": 6, "constant": 0.5, "mode": "charge", "quantity_unit": "V", "mark": "time_constant"}
    labels = _resolve("exponential_curve", charge, "physics")["computed"]["labels"]
    assert labels == {"time_constant": "2.00", "time_constant.value": "3.79"}
    # No mark: the curve alone.
    plain = _resolve("exponential_curve", {**DECAY, "mark": "none"}, "physics")
    assert "labels" not in plain["computed"] and [p["id"] for p in plain["parts"]] == ["curve"]
    for change in ({"time_range": [20, 0]}, {"time_range": [5, 20]}, {"initial": 0}):
        _refused("exponential_curve", {**DECAY, **change}, subject="physics")
    _refused("exponential_curve", {**DECAY, "constant": 0}, "visual_param_invalid", subject="physics")


def test_vsl46_exponential_and_distribution_are_a_level():
    _refused("exponential_curve", DECAY, "visual_kind_not_enabled", subject="physics", level="O")
    normal = {"distribution": "normal", "parameters": {"mean": 50, "sd": 10}, "interval": [40, 65], "tail": "between"}
    _refused("distribution_curve", normal, "visual_kind_not_enabled", level="O")


def test_vsl46_distribution_curve_resolution():
    normal = {"distribution": "normal", "parameters": {"mean": 50, "sd": 10}, "interval": [40, 65], "tail": "between"}
    resolved = _resolve("distribution_curve", normal)
    computed = resolved["computed"]
    # P(40 <= X <= 65) = Phi(1.5) - Phi(-1) = 0.7745, the density's integral (math_integrate) over the interval.
    assert (computed["labels"]["shade"], computed["event"]) == ("0.7745", "P(40 ≤ X ≤ 65)")
    assert (computed["window"], computed["shade"]) == ([10.0, 90.0], [40.0, 65.0])
    assert max(y for _, y in computed["points"]) == pytest.approx(0.0398942, rel=1e-5)  # 1 / (10 sqrt(2 pi))
    assert [p["id"] for p in resolved["parts"]] == ["curve", "shade", "mean"]
    assert resolved["alt"]["summary"].endswith("with P(40 ≤ X ≤ 65) shaded: the probability is 0.7745.")
    # Open tails: P(X <= 65) = 0.9332 and P(X >= 40) = 0.8413.
    for tail, expected in (("less_than", "0.9332"), ("greater_than", "0.8413")):
        assert _resolve("distribution_curve", {**normal, "tail": tail})["computed"]["labels"]["shade"] == expected
    # B(20, 0.3): P(X <= 4) = 0.2375 and P(X >= 8) = 0.2277; Po(3.5): P(2 <= X <= 5) = 0.7217 and P(X >= 6) = 0.1424.
    binomial = {"distribution": "binomial", "parameters": {"n": 20, "p": 0.3}, "interval": [0, 4], "tail": "less_than"}
    poisson = {"distribution": "poisson", "parameters": {"lambda": 3.5}, "interval": [2, 5], "tail": "between"}
    for params, expected, shaded in (
        (binomial, "0.2375", [0, 4]),
        ({**binomial, "interval": [8, 8], "tail": "greater_than"}, "0.2277", [8, 15]),
        (poisson, "0.7217", [2, 5]),
        ({**poisson, "interval": [6, 6], "tail": "greater_than"}, "0.1424", [6, 11]),
    ):
        computed = _resolve("distribution_curve", params)["computed"]
        assert (computed["labels"]["shade"], computed["shade"]) == (expected, shaded), params
    # Each bar is P(X = k) from the tool: B(20, 0.3) at 4 is 0.130421.
    bars = dict(_resolve("distribution_curve", binomial)["computed"]["bars"])
    assert bars[4] == pytest.approx(0.130421) and bars[0] == pytest.approx(0.7**20, rel=1e-5)


def test_vsl46_distribution_curve_refusals():
    normal = {"distribution": "normal", "parameters": {"mean": 50, "sd": 10}, "interval": [65, 40], "tail": "between"}
    binomial = {"distribution": "binomial", "parameters": {"n": 20, "p": 0.3}, "interval": [0, 4], "tail": "less_than"}
    for params in (
        normal,  # reversed
        {**binomial, "interval": [0, 4.5]},  # not a whole number of outcomes
        {**binomial, "interval": [0, 21]},  # beyond n
        {**binomial, "parameters": {"n": 20, "p": 1}},  # one outcome only
        {**binomial, "parameters": {"n": 10000, "p": 0.5}},  # more bars than one chart draws
        {"distribution": "poisson", "parameters": {"lambda": 2}, "interval": [-1, 3], "tail": "between"},
    ):
        _refused("distribution_curve", params)
    # Parameters of another distribution fail the schema.
    _refused("distribution_curve", {**binomial, "parameters": {"mean": 1, "sd": 1}}, "visual_param_invalid")


POINTS = [(0, 0), (1, 2.1), (2, 3.9), (3, 6.2), (4, 8.0), (5, 9.9)]
PLOT = {
    "points": [{"id": f"p{i}", "x": x, "y": y} for i, (x, y) in enumerate(POINTS)],
    "x_label": "Load",
    "y_label": "Extension",
    "x_unit": "N",
    "y_unit": "cm",
    "fit": "linear",
    "show_gradient": True,
}
KNOWNS = {f"kn_v{i}": Fraction(str(v)) for i, v in enumerate(sorted({v for p in POINTS for v in p}))}


def _plot(params: dict) -> dict:
    return _resolve("data_plot", params, "physics", "O", numbers_from=list(KNOWNS), knowns=KNOWNS)


def test_vsl46_data_plot_resolution():
    resolved = _plot(PLOT)
    computed = resolved["computed"]
    # Least squares: Sxy = 34.75 and Sxx = 17.5, so m = 1.99 cm/N and c = 5.017 - 1.986 * 2.5 = 0.0524 cm; the triangle
    # spans the data's x range, 5.00 N, and rises 9.93 cm.
    assert computed["labels"] == {"fit.gradient": "1.99", "fit.intercept": "0.0524", "gradient.dx": "5.00",
                                  "gradient.dy": "9.93"}  # fmt: skip
    assert computed["line"] == [[0.0, 0.052381], [5.0, 9.98095]]
    assert [p["id"] for p in resolved["parts"]] == ["p0", "p1", "p2", "p3", "p4", "p5", "fit", "gradient", "intercept"]
    assert "gradient 1.99 cm per N and intercept 0.0524 cm" in resolved["alt"]["summary"]
    # No fit: the points alone, and no tool runs.
    bare = _plot({**PLOT, "fit": "none"})
    assert bare["computed"] == {} and [p["id"] for p in bare["parts"]] == [f"p{i}" for i in range(6)]
    # A point id with a hyphen or a dot is a part id with `_` in its place.
    renamed = _plot({**PLOT, "points": [{**p, "id": f"run-{p['id']}.a"} for p in PLOT["points"]]})
    assert [p["id"] for p in renamed["parts"]][:2] == ["run_p0_a", "run_p1_a"]


def test_vsl46_data_plot_refusals():
    same_x = [{"id": f"p{i}", "x": 2, "y": y} for i, y in enumerate((0, 2.1, 3.9))]
    for points in (
        same_x,  # a constant x has no fitted line
        [*PLOT["points"][:5], {**PLOT["points"][4], "id": "again"}],  # the same point twice
        [*PLOT["points"][:5], {"id": "p4", "x": 9.9, "y": 0}],  # an id twice
        [*PLOT["points"][:5], {"id": "p_4", "x": 9.9, "y": 1}, {"id": "p-4", "x": 0, "y": 9.9}],  # one part id
    ):
        with pytest.raises(VisualError) as error:
            _plot({**PLOT, "points": points})
        assert error.value.code == "visual_resolution_failed", points
    # The data are the question's figures: a value no known traces is refused (VSL-12).
    with pytest.raises(VisualError) as error:
        _plot({**PLOT, "points": [*PLOT["points"][:5], {"id": "p5", "x": 5, "y": 9.8}]})
    assert error.value.code == "visual_untraced_number"
