"""Resolution tools per visual kind (VSL-13): a valid request becomes `computed` data from its kind's tools in the
sandboxed worker, and every check id those results carry joins the resolved spec's `numbers_from`.

A resolver gets the request (already through validator stages 1 to 6), `call`, which runs one worker tool and returns
its `fn` result (value and check record), and the pack conventions in force. A kind with no resolver here resolves to
nothing; a tool that fails, answers `unknown` or returns no check record raises, and the validator reports
`visual_resolution_failed`. Every number a renderer shows from a resolution is formatted here, once, into
`computed.labels` (part id -> display text), so the client never formats or computes a claim number itself.

Tools by kind (registers/visual-catalogue.json): function_graph and motion_graph -> math_plot_points (VER-14);
geometry_figure, bearing_diagram and transformation_grid -> geom_figure (VER-15); unit_circle, free_body components,
probability_tree and motion_diagram -> math_evaluate; circuit and circuit_sim -> phys_circuit and ray_diagram ->
phys_optics (VER-16); projectile_sim -> phys_projectile (VER-17); balanced_equation and particle_diagram ->
chem_balance (VER-19); titration_curve and titration_sim -> chem_acid_base (VER-21); gas_laws_sim -> math_evaluate
(VSL-46: ideal gas, p = nRT/V, with the model's R and the pack's kelvin offset); function_transform_sim ->
math_plot_points and math_evaluate (the tracked point); electrolysis_sim -> chem_balance (each half-equation) and
math_evaluate (Q = It and the amounts, with the pack's Faraday constant and molar volume); rates_sim -> math_evaluate
(k = A exp(-Ea/RT), a simplified first-order model); equilibrium_sim -> math_evaluate (Kc at the temperature, van't
Hoff) and math_solve (the equilibrium extent: chem_equilibrium is A level, VER-32, and not built); journal_entry,
t_account,
trial_balance and bank_reconciliation -> acc_double_entry, financial_statements -> acc_statements and break_even_chart
-> acc_break_even (VER-22)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from agent_core.assets.generated.sim_presets import SIM_PRESETS
from agent_core.assets.visual_kinds import surface_kind, tree_paths

Call = Callable[[str, dict[str, Any]], dict[str, Any]]
Computed = dict[str, Any]
PLAIN = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
FRACTION = re.compile(r"^-?[0-9]+/[0-9]+$")
QUANTITY = re.compile(r"^\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)\s*(.*)$")
OPTICS_CONVENTION = "phy.optics_sign_convention"


class ResolutionError(Exception):
    """A resolution tool gave no traceable result."""


class Session:
    """One resolution: the tool calls it made, their check ids and the labels it formatted."""

    def __init__(self, call: Call, conventions: Mapping[str, str]) -> None:
        self._call = call
        self.conventions = conventions
        self.check_ids: list[str] = []
        self.labels: dict[str, str] = {}

    def run(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        result = self._call(tool, args)
        check = result.get("check") or {}
        if check.get("function") != tool or not str(check.get("check_id", "")).startswith("chk_"):
            raise ResolutionError(f"{tool} returned no check record")
        value = result.get("value")
        if not isinstance(value, dict) or value.get("status") == "unknown":
            raise ResolutionError(f"{tool} could not decide ({(value or {}).get('reason', 'no value')})")
        if check["check_id"] not in self.check_ids:
            self.check_ids.append(str(check["check_id"]))
        return value

    def done(self, computed: Computed) -> Computed:
        out = {**computed, "check_ids": list(self.check_ids)}
        if self.labels:
            out["labels"] = dict(sorted(self.labels.items()))
        return out


def shown(value: Any, sf: int = 3) -> str:
    """How a tool's figure is displayed: its rounding when it states one, its exact text when that is a plain number or
    a simple fraction, else its decimal to `sf` significant figures."""
    if isinstance(value, dict):
        for key in ("rounded", "shown"):
            if isinstance(value.get(key), str):
                return str(value[key])
        if isinstance(value.get("exact"), dict):  # math_evaluate: {status, exact: {text, decimal}}
            return shown(value["exact"], sf)
        text = str(value.get("text", ""))
        if PLAIN.match(text) or FRACTION.match(text):
            return text
        return significant(str(value.get("decimal", text)), sf)
    return str(value)


def significant(decimal: str, sf: int = 3) -> str:
    number = float(decimal)
    if number == 0:
        return "0"
    text = f"{number:.{sf}g}"
    if "e" in text:
        text = f"{number:.{max(sf - 1, 0)}e}"
    return text


def magnitude(text: str) -> tuple[str, str]:
    """A quantity string split into its number and unit ("49 N" -> ("49", "N"))."""
    match = QUANTITY.match(str(text))
    if not match:
        raise ResolutionError(f"not a quantity: {text!r}")
    return match.group(1), match.group(2).strip()


# --- graphs ------------------------------------------------------------------------------------------------------


def _feature_label(x: dict[str, Any], y: dict[str, Any]) -> str:
    return f"({shown(x)}, {shown(y)})"


def function_graph(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    marks = [
        m
        for m in params.get("marks", [])
        if m in ("roots", "turning_points", "y_intercept", "asymptotes", "intersections")
    ]
    curves = [
        {
            "id": c["id"],
            "expr": re.sub(r"^\s*y\s*=\s*", "", c["expr"]),
            **({"domain": c["domain"]} if "domain" in c else {}),
        }
        for c in params["curves"]
    ]
    args: dict[str, Any] = {"curves": curves, "x_range": params["x_range"], "max_points": 200}
    if marks:
        args["marks"] = marks
    value = s.run("math_plot_points", args)
    out_curves, features = {}, {}
    for curve in value["curves"]:
        cid = curve["id"]
        out_curves[cid] = curve["segments"]
        found = []
        for n, root in enumerate(curve.get("roots", []), 1):
            found.append(
                {
                    "id": f"root{n}",
                    "x": float(root["x"]["decimal"]),
                    "y": 0.0,
                    "label": _feature_label(root["x"], root["y"]),
                    "say": f"It crosses the x-axis at x = {shown(root['x'])}.",
                }
            )
        for n, tp in enumerate(curve.get("turning_points", []), 1):
            nature = tp.get("nature", "turning_point")
            fid = {"minimum": "min", "maximum": "max"}.get(nature, "tp") + ("" if n == 1 else str(n))
            found.append(
                {
                    "id": fid,
                    "x": float(tp["x"]["decimal"]),
                    "y": float(tp["y"]["decimal"]),
                    "label": _feature_label(tp["x"], tp["y"]),
                    "say": f"It has a {nature} at {_feature_label(tp['x'], tp['y'])}.",
                }
            )
        if curve.get("y_intercept"):
            yi = curve["y_intercept"]
            found.append(
                {
                    "id": "yint",
                    "x": 0.0,
                    "y": float(yi["y"]["decimal"]),
                    "label": _feature_label(yi["x"], yi["y"]),
                    "say": f"It meets the y-axis at y = {shown(yi['y'])}.",
                }
            )
        for f in found:
            s.labels[f"{cid}.{f['id']}"] = str(f["label"])
        if found:
            features[cid] = found
    out: Computed = {"curves": out_curves}
    if features:
        out["features"] = features
    return s.done(out)


def motion_graph(spec: dict[str, Any], s: Session) -> Computed:
    curve = spec["params"].get("curve")
    if not curve:
        return {}
    value = s.run(
        "math_plot_points",
        {"curves": [{"id": "curve", "expr": curve["expr"]}], "x_range": curve["domain"], "max_points": 100},
    )
    return s.done({"curve": value["curves"][0]["segments"]})


def titration_curve(spec: dict[str, Any], s: Session) -> Computed:
    """The kind's params as `chem_acid_base` arguments; points, equivalence and start pH from its one result."""
    params = spec["params"]
    analyte, titrant = params["analyte"], params["titrant"]
    if analyte["kind"] == titrant["kind"]:
        raise ResolutionError("a titration needs an acid and a base")
    args: dict[str, Any] = {
        "task": "titration_curve",
        "analyte": analyte["kind"],
        f"{analyte['kind']}_volume": params["analyte_volume"],
    }
    for solution in (analyte, titrant):
        kind = solution["kind"]
        args[kind] = solution["formula"]
        args[f"{kind}_concentration"] = solution["concentration"]
        args[f"{kind}_strength"] = solution["strength"]
        if "basicity" in solution:
            args["basicity" if kind == "acid" else "acidity"] = solution["basicity"]
    if "volume_max" in params:
        args["volume_max"] = params["volume_max"]
    value = s.run("chem_acid_base", args)
    s.labels["equivalence"] = shown(value["equivalence"]["ph"])
    s.labels["equivalence_volume"] = (
        f"{shown(value['equivalence']['volume'])} {value['equivalence']['volume'].get('unit', '')}".strip()
    )
    s.labels["start_ph"] = shown(value["start_ph"])
    half = value.get("half_equivalence")
    if half:
        s.labels["half_equivalence"] = shown(half["ph"])
    return s.done(
        {
            **({"half_equivalence": half} if half else {}),
            "points": value["points"],
            "equivalence": value["equivalence"],
            "equivalence_index": value["equivalence_index"],
            "start_ph": value["start_ph"],
            "axes": value["axes"],
        }
    )


def break_even_chart(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    args = {
        k: params[k]
        for k in ("fixed_costs", "variable_cost_per_unit", "selling_price", "output_units", "chart_max_units")
        if k in params
    }
    value = s.run("acc_break_even", args)
    chart = value["chart"]
    s.labels["fixed_cost"] = chart["fixed_cost"][0][1]
    s.labels["break_even_units"] = shown(value["break_even_units"]["exact"]["exact"])
    s.labels["break_even_revenue"] = value["break_even_revenue"]["value"]
    s.labels["break_even"] = f"{s.labels['break_even_units']}, {s.labels['break_even_revenue']}"
    if value.get("margin_of_safety"):
        s.labels["margin_units"] = shown(value["margin_of_safety"]["units"]["exact"])
        s.labels["margin_of_safety"] = s.labels["margin_units"]
    lines = {k: [[float(x), float(y)] for x, y in chart[k]] for k in ("fixed_cost", "total_cost", "revenue")}
    bep = chart["break_even_point"]
    return s.done(
        {
            "lines": lines,
            "max_units": chart["max_units"],
            "break_even": [float(bep[0]["value"]), float(bep[1]["value"])],
        }
    )


# --- geometry ----------------------------------------------------------------------------------------------------


def geometry_figure(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    figure = params["figure"]
    givens = dict(params.get("givens") or {})
    if figure == "parallel_lines":
        return {}
    if figure == "triangle":
        if params.get("right_angle"):
            givens["right_angle"] = params["right_angle"]
        value = s.run("geom_figure", {"template": "triangle", "givens": givens})
        solution = value["solutions"][0]
        for side in "abc":
            s.labels[f"side_{side}"] = shown(solution["sides"][side])
        for angle in "ABC":
            s.labels[f"angle_{angle}"] = shown(solution["angles"][angle])
        return s.done({"figure": solution["figure"], "ambiguous": value["ambiguous"]})
    if figure == "circle":
        value = s.run("geom_figure", {"template": "circle", "givens": givens})
        s.labels["radius"] = shown(value["radius"])
        for key in ("chord", "arc"):
            if key in value:
                s.labels[key] = shown(value[key])
        if "angle" in value:
            s.labels["sector"] = shown(value["angle"])
        return s.done({"figure": value.get("figure", {})})
    value = s.run("geom_figure", {"template": "circle_theorem", "givens": {"theorem": params["theorem"], **givens}})
    s.labels["angle_given"] = shown(value["given"])
    s.labels["angle_derived"] = shown(value["derived"])
    return s.done(
        {
            "meaning": value["meaning"],
            "given": float(value["given"]["decimal"]),
            "derived": float(value["derived"]["decimal"]),
        }
    )


def bearing_diagram(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    distance, unit = magnitude(params["distance"])
    value = s.run(
        "geom_figure", {"template": "bearing", "givens": {"bearing": params["bearing"], "distance": distance}}
    )
    s.labels["bearing"] = value["bearing"]["three_figure"]
    s.labels["back_bearing"] = value["back_bearing"]["three_figure"]
    s.labels["east"] = f"{shown(value['east'])} {unit}".strip()
    s.labels["north"] = f"{shown(value['north'])} {unit}".strip()
    return s.done({"figure": value["figure"]})


def transformation_grid(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    points = [[p["x"], p["y"]] for p in params["object"]]
    value = s.run(
        "geom_figure",
        {"template": "transformation", "givens": {"points": points, "transformation": params["transformation"]}},
    )
    return s.done({"image": value["figure"]["image"]})


def unit_circle(spec: dict[str, Any], s: Session) -> Computed:
    angle = spec["params"]["angle_deg"]
    show = spec["params"].get("show") or ["sin", "cos"]
    values = {}
    for ratio in ("sin", "cos", "tan"):
        if ratio not in show and ratio != "tan":
            continue
        if ratio == "tan" and ("tan" not in show or (float(angle) - 90) % 180 == 0):
            continue
        value = s.run("math_evaluate", {"expression": f"{ratio}({angle})", "angle_unit": "degrees", "sf": 3})
        s.labels[f"leg_{ratio}"] = shown(value)
        values[ratio] = float(value["exact"]["decimal"])
    return s.done({"values": values})


def probability_tree(spec: dict[str, Any], s: Session) -> Computed:
    branches = spec["params"]["branches"]
    leaves = {}
    chain: dict[tuple[str, ...], str] = {}
    for path, branch in tree_paths(branches):
        chain[path] = f"({branch['p']})" if len(path) == 1 else f"{chain[path[:-1]]}*({branch['p']})"
        if not branch.get("then"):
            value = s.run("math_evaluate", {"expression": chain[path]})
            leaves["_".join(path)] = shown(value)
            s.labels["o_" + "_".join(path)] = shown(value)
    return s.done({"outcomes": leaves})


def motion_diagram(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    u, _ = magnitude(params["initial_velocity"])
    a, _ = magnitude(params["acceleration"])
    dt, _ = magnitude(params["interval"])
    positions, velocities = [], []
    for i in range(int(params["marks"])):
        t = f"{i}*({dt})"
        position = s.run("math_evaluate", {"expression": f"({u})*{t} + ({a})*({t})^2/2"})
        velocity = s.run("math_evaluate", {"expression": f"({u}) + ({a})*{t}"})
        positions.append(float(position["exact"]["decimal"]))
        velocities.append(float(velocity["exact"]["decimal"]))
    return s.done({"positions": positions, "velocities": velocities})


# --- physics -----------------------------------------------------------------------------------------------------


def _acute(delta: float) -> float:
    """The angle between a line and a direction, folded into 0 to 90 degrees (presentation arithmetic on the given
    angle; the component magnitudes themselves come from the tool)."""
    delta %= 180
    return delta if delta <= 90 else 180 - delta


def free_body(spec: dict[str, Any], s: Session) -> Computed:
    """Components of forces asked for by an `add: components_of` step, each magnitude computed by math_evaluate."""
    params = spec["params"]
    forces = {f["id"]: f for f in params["forces"]}
    surface = params.get("surface") or {}
    incline = surface_kind(params) == "incline"
    theta = float(surface.get("incline_deg", 0) or 0) if incline else 0.0
    first, second = ("parallel", "perpendicular") if incline else ("x", "y")
    components = {}
    for step in spec.get("steps", []):
        for add in step.get("add", []):
            if add.get("element") != "components_of" or add.get("of") not in forces:
                continue
            force = forces[add["of"]]
            amount, unit = magnitude(force["magnitude"])
            along = _acute(float(force["direction_deg"]) - theta)
            for part, trig in ((first, "cos"), (second, "sin")):
                value = s.run(
                    "math_evaluate", {"expression": f"{amount}*{trig}({along:g})", "angle_unit": "degrees", "sf": 3}
                )
                label = f"{shown(value)} {unit}".strip()
                s.labels[f"{force['id']}.{part}"] = label
                components[f"{force['id']}.{part}"] = label
    return s.done({"components": components}) if components else {}


TOOL_KINDS = {
    "cell": "cell",
    "battery": "battery",
    "resistor": "resistor",
    "lamp": "lamp",
    "ammeter": "ammeter",
    "voltmeter": "voltmeter",
    "switch": "switch",
}


def circuit(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    components = []
    for c in params["components"]:
        if c["type"] not in TOOL_KINDS:
            return {}  # phys_circuit cannot solve it: the circuit is drawn with no computed readings
        entry: dict[str, Any] = {"id": c["id"], "kind": TOOL_KINDS[c["type"]]}
        if c.get("value") is not None:
            number, _ = magnitude(c["value"])
            entry["emf" if c["type"] in ("cell", "battery") else "resistance"] = number
        if c["type"] == "switch":
            entry["state"] = c.get("state", "closed")
        components.append(entry)
    if any(c["to"].endswith(".wiper") or c["from"].endswith(".wiper") for c in params["connections"]):
        return {}
    if any(c["kind"] in ("cell", "battery") and "emf" not in c for c in components):
        return {}  # no source value: a drawing of the circuit with nothing to compute
    value = s.run("phys_circuit", {"components": components, "connections": params["connections"]})
    units = value["units"]
    readings = {}
    wanted = params.get("show") or ["meter_readings"]
    meters = any(k in wanted for k in ("meter_readings", "currents", "voltages"))
    for c in params["components"] if meters else []:
        result = value["components"].get(c["id"], {})
        if c["type"] == "ammeter" and "current" in result:
            readings[f"{c['id']}.reading"] = f"{shown(result['current'])} {units['current']}"
        if c["type"] == "voltmeter" and "pd" in result:
            readings[f"{c['id']}.reading"] = f"{shown(result['pd'])} {units['pd']}"
    s.labels.update(readings)
    if "equivalent_resistance" in (params.get("show") or []) and value.get("equivalent_resistance"):
        s.labels["equivalent_resistance"] = f"{shown(value['equivalent_resistance'])} {units['resistance']}"
    currents = {cid: float(r["current"]["decimal"]) for cid, r in value["components"].items() if "current" in r}
    return s.done({"currents": currents, "open_circuit": value.get("open_circuit", False)})


def ray_diagram(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    convention = s.conventions.get(OPTICS_CONVENTION)
    if convention is None:
        raise ResolutionError("the pack states no optics sign convention")
    args: dict[str, Any] = {
        "task": "image",
        "optic": params["optic"],
        "sign_convention": convention,
        "sign_convention_source": "pack",
    }
    for key in ("focal_length", "object_distance", "object_height"):
        if params.get(key) is not None:
            args[key], unit = magnitude(params[key])
            if unit and key == "object_distance":
                args["distance_unit"] = unit
    value = s.run("phys_optics", args)
    unit = magnitude(params["object_distance"])[1]
    wanted = params.get("rays") or ["parallel", "focal", "centre"]
    rays = {r["ray"]: r["path"] for r in value.get("rays", []) if r["ray"] in wanted}
    frame = value.get("frame", {})
    nature = value.get("nature") or {}
    if value.get("image") == "formed" and value.get("image_distance"):
        s.labels["image_distance"] = f"{shown(value['image_distance']).lstrip('-')} {unit}".strip()
        s.labels["magnification"] = shown(value["magnification"]).lstrip("-")
    return s.done(
        {
            "rays": [r for r in ("parallel", "focal", "centre") if r in rays],
            "paths": rays,
            "object_top": frame.get("object_top"),
            "image_top": frame.get("image_top") if value.get("image") == "formed" else None,
            "focal_points": frame.get("focal_points", []),
            "nature": nature,
            "nature_text": " ".join(str(nature.get(k, "")) for k in ("type", "orientation", "size")).strip(),
        }
    )


def projectile_sim(spec: dict[str, Any], s: Session) -> Computed:
    """The readouts at the starting values, from phys_projectile; the client model takes over as the sliders move."""
    params = spec["params"]
    g = s.conventions.get("phy.g")
    if g is None:
        raise ResolutionError("the pack states no value of g")
    args: dict[str, Any] = {
        "motion": params["mode"],
        "speed": params["speed"],
        "g": g,
        "g_source": "pack",
        "points": 41,
    }
    if params["mode"] == "vertical":
        args["direction"] = "up"
    if params.get("height") is not None:
        args["height"] = params["height"]
    value = s.run("phys_projectile", args)
    readouts = {
        "out.time": shown(value["time_of_flight"]),
        "out.range": shown(value["range"]),
        "out.max_height": shown(value["max_height"]),
    }
    s.labels.update(readouts)
    parts = [{"id": f"ctrl.{p}", "role": "control", "label": p} for p in ("mode", "speed", "height")]
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1].replace("_", " ")} for k in readouts]
    alt = {
        "mode": params["mode"],
        "speed": params["speed"],
        "height": params.get("height", 0),
        "range": readouts["out.range"],
        "time": readouts["out.time"],
    }
    return s.done({"g": float(g), "path": [[p["x"], p["y"]] for p in value["points"]], "parts": parts, "alt": alt})


def circuit_sim(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    resistors = params["resistors"]
    components = [
        {"id": "B", "kind": "battery", "emf": params["emf"]},
        {"id": "A1", "kind": "ammeter"},
        {"id": "S", "kind": "switch", "state": "closed" if params.get("switch_closed", True) else "open"},
    ]
    components += [{"id": r["id"], "kind": "resistor", "resistance": r["resistance"]} for r in resistors]
    group = [r["id"] for r in resistors]
    network = {
        "series": [
            "B",
            "A1",
            "S",
            {"parallel": group} if params["arrangement"] == "parallel" and len(group) > 1 else {"series": group},
        ]
    }
    value = s.run("phys_circuit", {"components": components, "network": network})
    units = value["units"]
    readouts = {
        "out.current": f"{shown(value['components']['A1']['current'])}",
        "out.resistance": shown(value["equivalent_resistance"]) if value.get("equivalent_resistance") else "∞",
    }
    for r in resistors:
        readouts[f"out.pd_{r['id']}"] = shown(value["components"][r["id"]]["pd"])
    s.labels.update(readouts)
    parts = [
        {"id": "ctrl.emf", "role": "control", "label": "emf"},
        {"id": "ctrl.arrangement", "role": "control", "label": "arrangement"},
        {"id": "ctrl.switch", "role": "control", "label": "switch"},
    ]
    parts += [{"id": f"ctrl.{r['id']}", "role": "control", "label": r["id"]} for r in resistors]
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1]} for k in readouts]
    alt = {
        "emf": params["emf"],
        "count": len(resistors),
        "arrangement": params["arrangement"],
        "current": readouts["out.current"],
    }
    return s.done({"units": units, "parts": parts, "alt": alt})


def titration_sim(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    acid, base = params["acid"], params["base"]
    volume = params["acid_volume"]
    end = volume * acid["concentration"] / base["concentration"]
    at = [0, end / 2, end, end * 1.5]
    args = {
        "task": "titration_curve",
        "analyte": "acid",
        "acid": acid["formula"],
        "acid_strength": "strong",
        "acid_concentration": f"{acid['concentration']} mol dm^-3",
        "acid_volume": f"{volume} cm^3",
        "base": base["formula"],
        "base_strength": "strong",
        "base_concentration": f"{base['concentration']} mol dm^-3",
        "at_volumes": [f"{v:g} cm^3" for v in at],
        "volume_max": f"{2 * end:g} cm^3",
    }
    value = s.run("chem_acid_base", args)
    readouts = {
        "out.ph": shown(value["start_ph"]),
        "out.volume": "0",
        "out.end_point": shown(value["equivalence"]["volume"]),
    }
    s.labels.update(readouts)
    parts = [
        {"id": "ctrl.volume", "role": "control", "label": "volume added"},
        {"id": "ctrl.tap", "role": "control", "label": "tap"},
        {"id": "ctrl.indicator", "role": "control", "label": "indicator"},
    ]
    parts += [
        {"id": k, "role": "readout", "label": k.split(".")[1].replace("_", " ")}
        for k in ("out.volume", "out.ph", "out.end_point")
    ]
    alt = {"acid": acid["formula"], "base": base["formula"], "volume": volume, "end": readouts["out.end_point"]}
    samples = [{"volume": float(a["volume"]["decimal"]), "ph": float(a["ph"]["decimal"])} for a in value.get("at", [])]
    return s.done({"points": value["points"], "samples": samples, "parts": parts, "alt": alt})


# The molar gas constant of the simplified S3 simulation models (J/(mol K)); the client models use the same figure.
GAS_CONSTANT = "8.314"
KELVIN_OFFSET = "phy.kelvin_offset"
# The client models' bounded slider ranges (VSL-30): a starting value outside them is refused, never clamped.
GAS_TEMPERATURE_K = (100, 600)
GAS_VOLUME_CM3 = (20, 500)


def _sim_preset(kind: str, preset_id: str) -> dict[str, Any]:
    preset: dict[str, Any] | None = SIM_PRESETS.get(preset_id)
    if preset is None or preset["kind"] != kind:
        ours = ", ".join(sorted(i for i, p in SIM_PRESETS.items() if p["kind"] == kind))
        raise ResolutionError(f"no {kind} preset {preset_id} (the presets are {ours})")
    return preset


def _within(name: str, value: float, bounds: tuple[float, float]) -> None:
    if not bounds[0] <= value <= bounds[1]:
        raise ResolutionError(f"{name} {value:g} is outside the simulation's range {bounds[0]:g} to {bounds[1]:g}")


def gas_laws_sim(spec: dict[str, Any], s: Session) -> Computed:
    """The starting pressure from math_evaluate (p = nRT/V); the client model takes over as the slider moves."""
    params = spec["params"]
    preset = _sim_preset("gas_laws_sim", params["preset_id"])
    if params["control"] not in preset["controls"]:
        raise ResolutionError(f"{preset['id']} holds the {params['control']} fixed; it cannot be the control")
    volume_cm3 = params["volume_m3"] * 1e6
    _within("temperature", params["temperature_k"], GAS_TEMPERATURE_K)
    _within("volume", volume_cm3, GAS_VOLUME_CM3)
    expression = f"{params['amount_mol']}*{GAS_CONSTANT}*{params['temperature_k']}/({params['volume_m3']})/1000"
    value = s.run("math_evaluate", {"expression": expression, "sf": 3})
    readouts = {"out.pressure": shown(value), "out.temperature": f"{params['temperature_k']:g}"}
    out: Computed = {"container": preset["container"]}
    offset = s.conventions.get(KELVIN_OFFSET)
    if offset is not None:
        out["kelvin_offset"] = float(offset)
        readouts["out.celsius"] = f"{params['temperature_k'] - float(offset):g}"
    s.labels.update(readouts)
    parts = [{"id": f"ctrl.{c}", "role": "control", "label": c} for c in ("temperature", "volume")]
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1]} for k in readouts]
    alt = {
        "container": preset["container"],
        "control": params["control"],
        "temperature": readouts["out.temperature"],
        "volume": f"{volume_cm3:g}",
        "pressure": readouts["out.pressure"],
    }
    return s.done({**out, "parts": parts, "alt": alt})


# The client's deterministic parser (packages/renderers/src/expr.ts): numbers, x, + - * / ^, brackets and these names.
FUNCTION_NAMES = frozenset({"sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "abs", "exp", "ln", "log", "pi", "e"})
EXPRESSION = re.compile(r"^[0-9x.+\-*/^() a-z]+$")


def _transformed(expression: str, p: dict[str, float]) -> str:
    inner = f"(({p['b']})*(x+({p['c']})))"
    return f"({p['a']})*({re.sub(r'(?<![a-z])x(?![a-z])', inner, expression)})+({p['d']})"


def function_transform_sim(spec: dict[str, Any], s: Session) -> Computed:
    """y = a f(b(x + c)) + d: the starting curve from math_plot_points and the tracked point, where the parent graph's
    point at x0 goes, from math_evaluate. Slider ranges, steps and values are checked; an expression the client's
    parser cannot read fails closed."""
    params = spec["params"]
    expression = params["expression"].replace("**", "^")
    names = set(re.findall(r"[a-z]+", expression)) - {"x"}
    if not EXPRESSION.match(expression) or not names <= FUNCTION_NAMES:
        raise ResolutionError(f"the expression {expression!r} is not one the simulation can draw")
    lo, hi = params["x_range"]
    if not lo < hi:
        raise ResolutionError("x_range runs the wrong way")
    values: dict[str, float] = {}
    for name in ("a", "b", "c", "d"):
        slider = params["parameters"][name]
        if not slider["min"] < slider["max"] or not slider["min"] <= slider["value"] <= slider["max"]:
            raise ResolutionError(f"the {name} slider's range or value is invalid")
        steps = (slider["value"] - slider["min"]) / slider["step"]
        if abs(steps - round(steps)) > 1e-9:
            raise ResolutionError(f"{name} = {slider['value']:g} is not on its slider's steps")
        values[name] = slider["value"]
    if values["b"] == 0:
        raise ResolutionError("b = 0 flattens the graph; the tracked point is undefined")
    # The tracked point: the parent's point at x0 = 0, or at x0 = 1 where f(0) is undefined (ln x, 1/x).
    parent: dict[str, Any] | None = None
    for x0 in (0, 1):
        try:
            parent = s.run("math_evaluate", {"expression": re.sub(r"(?<![a-z])x(?![a-z])", f"({x0})", expression)})
            break
        except Exception:  # undefined there (a domain error or `unknown`): the next point is tried
            parent = None
    if parent is None:
        raise ResolutionError("the parent graph has no point at x = 0 or x = 1 to track")
    curve = _transformed(expression, values)
    s.run("math_plot_points", {"curves": [{"id": "f", "expr": curve}], "x_range": [lo, hi], "max_points": 121})
    point_x = s.run("math_evaluate", {"expression": f"{x0}/({values['b']})-({values['c']})"})
    point_y = s.run("math_evaluate", {"expression": f"({values['a']})*({parent['exact']['text']})+({values['d']})"})
    readouts = {"out.point_x": shown(point_x), "out.point_y": shown(point_y)}
    s.labels.update(readouts)
    parts = [{"id": f"ctrl.{k}", "role": "control", "label": k} for k in ("a", "b", "c", "d")]
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1].replace("_", " ")} for k in readouts]
    alt = {
        "expression": params["expression"],
        "a": f"{values['a']:g}",
        "b": f"{values['b']:g}",
        "c": f"{values['c']:g}",
        "d": f"{values['d']:g}",
        "x": readouts["out.point_x"],
        "y": readouts["out.point_y"],
    }
    return s.done({"x0": x0, "parts": parts, "alt": alt})


ELECTROLYSIS_CURRENT_A = (0.1, 5)
ELECTROLYSIS_DURATION_S = (1, 7200)
FORMULA_PART = re.compile(r"([A-Z][a-z]?)(\d*)")


def _molar_mass(formula: str, conventions: Mapping[str, str]) -> str:
    """A product's molar mass as an expression of the pack's relative atomic masses (chem.ar_<element>)."""
    terms = []
    for element, count in FORMULA_PART.findall(formula):
        ar = conventions.get(f"chem.ar_{element.lower()}")
        if ar is None:
            raise ResolutionError(f"the pack states no relative atomic mass for {element}")
        terms.append(f"{count or 1}*{ar}")
    return "(" + "+".join(terms) + ")"


def _half_equation(product: dict[str, Any], s: Session) -> None:
    """chem_balance checks the preset's half-equation is balanced in atoms and charge, with the stated electrons."""
    value = s.run("chem_balance", {"equation": product["half_equation"]})
    if not value.get("student", {}).get("balanced"):
        raise ResolutionError(f"{product['half_equation']} is not balanced")
    by_formula = {sp["formula"]: sp["coefficient"] for sp in value["species"]}
    if by_formula.get("e-", 0) != product["electrons"] * by_formula.get(product["formula"], 0):
        raise ResolutionError(
            f"{product['half_equation']} does not move {product['electrons']} electrons per {product['formula']}"
        )


def electrolysis_sim(spec: dict[str, Any], s: Session) -> Computed:
    """The cell from its preset (each half-equation checked by chem_balance), and the amounts at the end of the run from
    math_evaluate: Q = It, n = Q / (zF), a gas's volume from the pack's molar volume, a metal's mass from its Ar."""
    params = spec["params"]
    preset = _sim_preset("electrolysis_sim", params["preset_id"])
    for field in ("phase", "electrodes"):
        if params[field] != preset[field]:
            raise ResolutionError(f"{preset['id']} is {field} {preset[field]}, not {params[field]}")
    if params["electrolyte"].strip().lower() != preset["electrolyte"].lower():
        raise ResolutionError(f"{preset['id']} is {preset['electrolyte']}, not {params['electrolyte']}")
    _within("current", params["current_a"], ELECTROLYSIS_CURRENT_A)
    _within("duration", params["duration_s"], ELECTROLYSIS_DURATION_S)
    faraday, vm = s.conventions.get("chem.faraday"), s.conventions.get("chem.vm")
    if faraday is None or vm is None:
        raise ResolutionError("the pack states no Faraday constant or molar gas volume")
    current, duration = params["current_a"], params["duration_s"]
    molar_mass: dict[str, float] = {}
    readouts = {"out.charge": shown(s.run("math_evaluate", {"expression": f"{current}*{duration}", "sf": 3}))}
    for side in ("cathode", "anode"):
        product = preset[side]
        _half_equation(product, s)
        moles = f"{current}*{duration}/({product['electrons']}*{faraday})"
        if product["measure"] == "gas":
            gas = s.run("math_evaluate", {"expression": f"{moles}*{vm}*1000", "sf": 3})
            readouts[f"out.{side}_gas"], readouts[f"out.{side}_mass"] = shown(gas), "0"
            continue
        mass_expr = _molar_mass(product["formula"], s.conventions)
        molar_mass[product["formula"]] = float(s.run("math_evaluate", {"expression": mass_expr})["exact"]["decimal"])
        sign = "-" if product["measure"] == "dissolves" else ""
        mass = s.run("math_evaluate", {"expression": f"{sign}{moles}*{mass_expr}", "sf": 3})
        readouts[f"out.{side}_mass"], readouts[f"out.{side}_gas"] = shown(mass), "0"
    s.labels.update(readouts)
    constants = {"faraday": float(faraday), "vm_cm3": float(vm) * 1000, "molar_mass": molar_mass}
    parts = [
        {"id": "ctrl.current", "role": "control", "label": "current"},
        {"id": "ctrl.ions", "role": "control", "label": "ions"},
    ]
    order = ("out.charge", "out.cathode_mass", "out.cathode_gas", "out.anode_mass", "out.anode_gas")  # the model's
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1].replace("_", " ")} for k in order]
    alt = {
        "electrolyte": preset["electrolyte"],
        "phase": preset["phase"],
        "electrodes": preset["electrodes"],
        "current": f"{current:g}",
        "duration": f"{duration:g}",
        "cathode": preset["cathode"]["id"],
        "anode": preset["anode"]["id"],
    }
    return s.done({"constants": constants, "parts": parts, "alt": alt})


RATES_TEMPERATURE_K = (273, 373)
RATES_CONCENTRATION = (0.1, 2)
# A run ends at kt = ln(10^6): the product is then within one part in a million of all it can become (the client's).
RATES_END_KT = "ln(1000000)"


def rates_sim(spec: dict[str, Any], s: Session) -> Computed:
    """The rate constant and the starting rate from math_evaluate (k = A e^(-Ea/RT), rate = k c0), and how long the run
    takes; the catalyst lowers the activation energy and so must give a lower one (VSL-46)."""
    params = spec["params"]
    _within("temperature", params["temperature_k"], RATES_TEMPERATURE_K)
    _within("concentration", params["concentration_mol_l"], RATES_CONCENTRATION)
    if not params["catalysed_activation_energy_j_mol"] < params["activation_energy_j_mol"]:
        raise ResolutionError("a catalyst gives a lower activation energy than the uncatalysed reaction")
    temperature, c0 = params["temperature_k"], params["concentration_mol_l"]

    def k(ea: float) -> str:
        return f"{params['pre_exponential_s']}*exp(-{ea}/({GAS_CONSTANT}*{temperature}))"

    uncatalysed = k(params["activation_energy_j_mol"])
    readouts = {
        "out.rate_constant": shown(s.run("math_evaluate", {"expression": uncatalysed, "sf": 3})),
        "out.rate": shown(s.run("math_evaluate", {"expression": f"{uncatalysed}*{c0}", "sf": 3})),
        "out.product": "0",
    }
    end = s.run("math_evaluate", {"expression": f"{RATES_END_KT}/({uncatalysed})", "sf": 3})
    s.labels.update(readouts)
    s.labels["end.time"] = shown(end)
    parts = [{"id": f"ctrl.{c}", "role": "control", "label": c} for c in ("temperature", "concentration", "catalyst")]
    parts += [{"id": k, "role": "readout", "label": k.split(".")[1].replace("_", " ")} for k in readouts]
    alt = {
        "temperature": f"{temperature:g}",
        "concentration": f"{c0:g}",
        "k": readouts["out.rate_constant"],
        "time": shown(end),
    }
    return s.done({"parts": parts, "alt": alt})


EQUILIBRIUM_SPAN_K = 200  # the client's temperature slider runs this far either side of the reference


def equilibrium_sim(spec: dict[str, Any], s: Session) -> Computed:
    """Kc at the starting temperature from the reference value (van't Hoff, constant enthalpy) with math_evaluate, and
    the equilibrium the starting mixture reaches with math_solve: one admissible extent keeping every species
    non-negative, or the request is refused. Pure solids and liquids take no part (activity 1)."""
    params = spec["params"]
    species = params["reaction"]["species"]
    ids = [sp["id"] for sp in species]
    if len(set(ids)) != len(ids):
        raise ResolutionError("species ids repeat")
    sides = {sp["side"] for sp in species}
    if sides != {"reactant", "product"}:
        raise ResolutionError("a reversible reaction needs a reactant and a product")
    active = [sp for sp in species if sp["state"] in ("gas", "aqueous")]
    initial = {c["species_id"]: c["value"] for c in params["initial_concentrations"]}
    unknown = sorted(set(initial) - set(ids))
    if unknown:
        raise ResolutionError(f"initial concentrations name species not in the reaction: {', '.join(unknown)}")
    reference = params["reference_temperature_k"]
    _within(
        "temperature", params["temperature_k"], (max(1, reference - EQUILIBRIUM_SPAN_K), reference + EQUILIBRIUM_SPAN_K)
    )
    kc_expr = (
        f"{params['reference_kc']}*exp(-({params['forward_enthalpy_j_mol']})/{GAS_CONSTANT}"
        f"*(1/{params['temperature_k']}-1/{reference}))"
    )
    kc = s.run("math_evaluate", {"expression": kc_expr, "sf": 3})
    # The extent x from the starting mixture: products (c + v x)^v over reactants (c - v x)^v equals Kc.
    lo, hi = float("-inf"), float("inf")
    top, bottom = [], []
    for sp in active:
        c, v = initial.get(sp["id"], 0), sp["coefficient"]
        if sp["side"] == "reactant":
            hi = min(hi, c / v)
            bottom.append(f"({c}-{v}*x)^{v}")
        else:
            lo = max(lo, -c / v)
            top.append(f"({c}+{v}*x)^{v}")
    equation = f"{'*'.join(top) or '1'} = ({kc['exact']['decimal']})*{'*'.join(bottom) or '1'}"
    solved = s.run("math_solve", {"equations": [equation], "unknowns": ["x"], "domain": "real"})
    roots = [float(r["x"]["decimal"]) for r in solved.get("solutions", []) if "x" in r]
    admissible = sorted({round(x, 12) for x in roots if lo - 1e-12 <= x <= hi + 1e-12})
    if len(admissible) != 1:
        raise ResolutionError(f"the equilibrium has {len(admissible)} admissible extents, not one")
    extent = admissible[0]
    readouts = {"out.kc": shown(kc)}
    for sp in active:
        c, v = initial.get(sp["id"], 0), sp["coefficient"]
        sign = 1 if sp["side"] == "product" else -1
        readouts[f"eq.c_{sp['id']}"] = significant(str(c + sign * v * extent))
    s.labels.update(readouts)
    order = ("temperature", "volume", "add_reactant", "add_product", "catalyst")  # the client model's control order
    controls = [c for c in order if c in params["controls"]]
    parts = [{"id": f"ctrl.{c}", "role": "control", "label": c.replace("_", " ")} for c in controls]
    parts += [{"id": f"out.c_{sp['id']}", "role": "readout", "label": sp["formula"]} for sp in active]
    parts += [{"id": "out.kc", "role": "readout", "label": "Kc"}]
    equation_text = " ⇌ ".join(
        " + ".join(
            f"{sp['coefficient'] if sp['coefficient'] > 1 else ''}{sp['formula']}"
            for sp in species
            if sp["side"] == side
        )
        for side in ("reactant", "product")
    )
    at_equilibrium = ", ".join(f"{sp['formula']} {readouts['eq.c_' + sp['id']]}" for sp in active)
    alt = {"equation": equation_text, "temperature": f"{params['temperature_k']:g}", "kc": readouts["out.kc"],
           "equilibrium": at_equilibrium}  # fmt: skip
    return s.done({"extent": extent, "parts": parts, "alt": alt})


# --- chemistry -----------------------------------------------------------------------------------------------------


def _equation(spec: dict[str, Any]) -> str:
    params = spec["params"]
    arrow = " ⇌ " if params.get("arrow") == "equilibrium" else " -> "
    return (
        " + ".join(s["formula"] for s in params["reactants"])
        + arrow
        + " + ".join(s["formula"] for s in params["products"])
    )


def balanced_equation(spec: dict[str, Any], s: Session) -> Computed:
    value = s.run("chem_balance", {"equation": _equation(spec).replace(" ⇌ ", " -> ")})
    species = value["species"]
    counter = {"reactants": 0, "products": 0}
    for sp in species:
        counter[sp["side"]] += 1
        part = f"{'r' if sp['side'] == 'reactants' else 'p'}{counter[sp['side']]}"
        s.labels[part] = f"{sp['coefficient'] if sp['coefficient'] != 1 else ''}{sp['formula']}"
    for row in value["atom_counts"]:
        s.labels[f"atoms.{row['element']}"] = f"{row['reactants']} = {row['products']}"
    return s.done(
        {
            "species": species,
            "coefficients": value["coefficients"],
            "equation": value["equation"],
            "atom_counts": value["atom_counts"],
        }
    )


def particle_diagram(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    if params["mode"] != "reaction":
        return {}
    value = s.run("chem_balance", {"equation": params["equation"]})
    for i, sp in enumerate(value["species"], 1):
        s.labels[f"sp{i}"] = f"{sp['coefficient'] if sp['coefficient'] != 1 else ''}{sp['formula']}"
    return s.done({"species": value["species"], "equation": value["equation"]})


# --- accounting ----------------------------------------------------------------------------------------------------


def journal_entry(spec: dict[str, Any], s: Session) -> Computed:
    lines = [{"account": x["account"], "side": x["side"], "amount": x["amount"]} for x in spec["params"]["lines"]]
    value = s.run("acc_double_entry", {"task": "post", "entries": [{"ref": "j1", "lines": lines}]})
    entry = value["entries"][0]
    s.labels["total_debit"] = entry["total_debit"]
    s.labels["total_credit"] = entry["total_credit"]
    return s.done({"balanced": entry["balanced"]})


def t_account(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    names = {a["id"]: a["name"] for a in params["accounts"]}
    entries = [
        {
            "ref": e["id"],
            "lines": [
                {"account": names.get(e["debit"], e["debit"]), "side": "debit", "amount": e["amount"]},
                {"account": names.get(e["credit"], e["credit"]), "side": "credit", "amount": e["amount"]},
            ],
        }
        for e in params["entries"]
    ]
    args: dict[str, Any] = {"task": "post", "entries": entries}
    opening = [
        {"account": a["name"], "side": a.get("opening_side", "debit"), "amount": a["opening_balance"]}
        for a in params["accounts"]
        if a.get("opening_balance")
    ]
    if opening:
        args["opening_balances"] = opening
    value = s.run("acc_double_entry", args)
    by_name = {acc["account"]: acc for acc in value["ledger"]}
    balances, totals = {}, {}
    for aid, name in names.items():
        ledger = by_name.get(name)
        if ledger is None:
            continue
        if ledger.get("balance_cd"):
            balances[aid] = ledger["balance_cd"]
            s.labels[f"{aid}.balance_cd"] = ledger["balance_cd"]["amount"]
        totals[aid] = ledger.get("total")
    return s.done({"balances": balances, "totals": totals})


def trial_balance(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    balances = params.get("balances") or []
    opening = [{"account": b["account"], "side": b["side"], "amount": b["amount"]} for b in balances]
    # Posting nothing on top of the balances gives the trial balance of the balances themselves.
    value = s.run("acc_double_entry", {"task": "post", "opening_balances": opening})
    tb = value["trial_balance"]
    rows = tb["rows"]
    for i, row in enumerate(rows, 1):
        s.labels[f"row_{i}"] = row["amount"]
    s.labels["total_debit"] = tb["total_debit"]
    s.labels["total_credit"] = tb["total_credit"]
    if not tb["agrees"]:
        s.labels["mismatch"] = tb["difference"]
    return s.done({"rows": rows, "agrees": tb["agrees"], "difference": tb["difference"]})


def financial_statements(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]
    args: dict[str, Any] = {"trial_balance": params["trial_balance"]}
    if params.get("adjustments"):
        args["adjustments"] = params["adjustments"]
    value = s.run("acc_statements", args)
    statement = value[params["statement"]]
    lines = []
    for line in statement["lines"]:
        lid = "line_" + re.sub(r"[^A-Za-z0-9_]", "_", str(line["id"]))
        lines.append({"id": lid, "label": line["label"], "op": line["op"]})
        s.labels[lid] = line["amount"]
    return s.done({"title": statement["title"], "lines": lines})


def bank_reconciliation(spec: dict[str, Any], s: Session) -> Computed:
    params = spec["params"]

    def items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: r[k] for k in ("direction", "amount", "details", "ref") if k in r} for r in rows]

    value = s.run(
        "acc_double_entry",
        {
            "task": "reconcile",
            "cash_book": {"balance": params["cash_book_balance"], "entries": items(params.get("cash_book", []))},
            "bank_statement": {
                "balance": params["bank_statement_balance"],
                "entries": items(params.get("bank_statement", [])),
            },
        },
    )
    lines = []
    for line in value["statement"]["lines"]:
        lid = "line_" + re.sub(r"[^A-Za-z0-9_]", "_", str(line["id"]))
        lines.append({"id": lid, "label": line["label"], "op": line["op"]})
        s.labels[lid] = line["amount"]
    return s.done(
        {"lines": lines, "updated_balance": value["cash_book"]["updated_balance"], "reconciled": value["reconciled"]}
    )


KIND_RESOLVERS: dict[str, Callable[[dict[str, Any], Session], Computed]] = {
    "function_graph": function_graph,
    "motion_graph": motion_graph,
    "titration_curve": titration_curve,
    "break_even_chart": break_even_chart,
    "geometry_figure": geometry_figure,
    "bearing_diagram": bearing_diagram,
    "transformation_grid": transformation_grid,
    "unit_circle": unit_circle,
    "probability_tree": probability_tree,
    "motion_diagram": motion_diagram,
    "free_body": free_body,
    "circuit": circuit,
    "ray_diagram": ray_diagram,
    "balanced_equation": balanced_equation,
    "particle_diagram": particle_diagram,
    "journal_entry": journal_entry,
    "t_account": t_account,
    "trial_balance": trial_balance,
    "financial_statements": financial_statements,
    "bank_reconciliation": bank_reconciliation,
    "projectile_sim": projectile_sim,
    "circuit_sim": circuit_sim,
    "titration_sim": titration_sim,
    "gas_laws_sim": gas_laws_sim,
    "function_transform_sim": function_transform_sim,
    "electrolysis_sim": electrolysis_sim,
    "rates_sim": rates_sim,
    "equilibrium_sim": equilibrium_sim,
}


def resolver(call: Call, conventions: Mapping[str, str] | None = None) -> Callable[[dict[str, Any]], Computed]:
    """The resolution step for `validate` / `Resolver`: the request's kind resolver, or nothing to compute."""

    def resolve(spec: dict[str, Any]) -> Computed:
        kind = KIND_RESOLVERS.get(spec["type"])
        if kind is None:
            return {}
        return kind(spec, Session(call, conventions or {}))

    return resolve
