"""What the engine knows about each catalogue kind (VSL-03, VSL-04, VSL-08, VSL-10, VSL-12, VSL-14, VSL-19).

For every kind the S2 client can draw: the documented part ids (VSL-19) derived from the params and the resolution's
`computed` data, the claim numbers a student could read in the params (VSL-12), the elements a step may `add` (from
the kind's schema, VSL-10) and the alternative text (VSL-14), built from the resolved spec with the string templates of
`visual_text.<locale>.json` and never written by a model. The vetted renderers derive the same part ids from the same
spec; `vsl19_parts_match_dom` holds the two to each other through the engine-resolved fixtures."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from agent_core.assets.generated.kind_schemas import KIND_SCHEMAS

TEXT_DIR = Path(__file__).parent
NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:/[0-9]+)?")
LIBRARY_KINDS = frozenset({"library_diagram", "diagram_comparison", "microscope_view", "reaction_mechanism"})
# The simulations (VSL-08): parts and alt text come from their resolution's `parts` and `alt`.
SIM_KINDS = frozenset({
    "projectile_sim", "circuit_sim", "titration_sim", "gas_laws_sim", "function_transform_sim", "electrolysis_sim",
    "rates_sim", "equilibrium_sim",
})  # fmt: skip


@cache
def text(locale: str = "en") -> dict[str, Any]:
    path = TEXT_DIR / f"visual_text.{locale}.json"
    if not path.is_file():
        path = TEXT_DIR / "visual_text.en.json"
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def say(group: str, key: str, locale: str = "en", **values: Any) -> str:
    template = str(text(locale)[group].get(key, key))
    return template.format_map({k: ("" if v is None else v) for k, v in values.items()})


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    role: str = "part"
    focusable: bool = True
    quizzable: bool = False

    def record(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name[:80], "role": self.role, "focusable": self.focusable}
        if self.quizzable:
            out["quizzable"] = True
        return out


@dataclass
class View:
    """The request (after preset merge and repairs) and its resolution, as the per-kind rules see them."""

    kind: str
    params: dict[str, Any]
    computed: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    entry: dict[str, Any] | None = None  # the library entry for library kinds
    locale: str = "en"

    def adds(self) -> list[dict[str, Any]]:
        return [a for step in self.steps for a in step.get("add", [])]

    def label(self, part_id: str, default: str = "") -> str:
        labels = self.computed.get("labels") or {}
        return str(labels.get(part_id, default))

    def name(self, key: str, **values: Any) -> str:
        return say("part", key, self.locale, **values)


def add_elements(kind: str) -> list[str]:
    """The elements a step may add on this kind (the `add` list of its params schema, VSL-10)."""
    from agent_core.contracts import document, schema_ids

    schema: dict[str, Any] | None = KIND_SCHEMAS.get(kind)
    name = f"visuals/kinds/{kind}"
    if schema is None and f"https://jana.dev/contracts/{name}" in schema_ids():
        schema = document(name)
    if schema is None:
        return []
    element = schema.get("$defs", {}).get("add", {}).get("properties", {}).get("element", {})
    return list(element.get("enum", []))


# --- claim numbers (VSL-12) ------------------------------------------------------------------------------------------


def _numbers_at(node: Any, path: str) -> Iterator[tuple[str, str]]:
    """(written number, where) for a number or quantity string, or a plain number."""
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, int | float):
        yield (repr(node) if isinstance(node, float) else str(node)), path
        return
    if isinstance(node, str):
        match = NUMBER.match(node.strip())
        if match and match.group(0) not in ("-",):
            yield match.group(0), path


def _walk(params: Any, pattern: list[str], path: str = "params") -> Iterator[tuple[str, str]]:
    if not pattern:
        yield from _numbers_at(params, path)
        return
    head, rest = pattern[0], pattern[1:]
    if head == "*":
        if isinstance(params, list):
            for i, item in enumerate(params):
                yield from _walk(item, rest, f"{path}[{i}]")
        elif isinstance(params, dict):
            for key, item in params.items():
                yield from _walk(item, rest, f"{path}.{key}")
        return
    if head == "**":  # a recursive branch list (probability trees)
        if isinstance(params, list):
            for i, item in enumerate(params):
                yield from _walk(item, rest, f"{path}[{i}]")
                yield from _walk(item.get("then", []) if isinstance(item, dict) else [], pattern, f"{path}[{i}].then")
        return
    if isinstance(params, dict) and head in params:
        yield from _walk(params[head], rest, f"{path}.{head}")


CLAIM_PATHS: dict[str, list[str]] = {
    "free_body": ["forces.*.magnitude"],
    "function_graph": ["points.*.x", "points.*.y"],
    "number_line": ["intervals.*.from", "intervals.*.to"],
    "geometry_figure": ["givens.*"],
    "unit_circle": ["angle_deg"],
    "venn_diagram": ["regions.*.value"],
    "statistics_chart": [
        "categories.*.value",
        "classes.*.lower",
        "classes.*.upper",
        "classes.*.frequency",
        "summary.*",
    ],
    "matrix_table": ["rows.*.*"],
    "bearing_diagram": ["bearing", "distance"],
    "motion_graph": ["points.*.t", "points.*.value"],
    "wave_diagram": ["wavelength", "amplitude"],
    "energy_profile": ["activation_energy", "enthalpy_change"],
    "journal_entry": ["lines.*.amount"],
    "financial_statements": ["trial_balance.*.debit", "trial_balance.*.credit", "adjustments.*.amount"],
    "bank_reconciliation": [
        "cash_book_balance",
        "bank_statement_balance",
        "cash_book.*.amount",
        "bank_statement.*.amount",
    ],
    "break_even_chart": ["fixed_costs", "variable_cost_per_unit", "selling_price"],
    "probability_tree": ["branches.**.p"],
    "motion_diagram": ["initial_velocity", "acceleration", "interval"],
    "circuit": ["components.*.value"],
    "ray_diagram": ["focal_length", "object_distance", "object_height"],
    "t_account": ["accounts.*.opening_balance", "entries.*.amount"],
    "trial_balance": ["balances.*.amount"],
}


def claim_numbers(kind: str, params: dict[str, Any]) -> list[tuple[str, str]]:
    """Every claim number a student can read in the params of this kind; presentation numbers are not listed."""
    found: list[tuple[str, str]] = []
    for pattern in CLAIM_PATHS.get(kind, []):
        found += list(_walk(params, pattern.split(".")))
    return found


# --- parts per kind (VSL-19) -----------------------------------------------------------------------------------------

Parts = list[Part]


def _free_body(v: View) -> Parts:
    params = v.params
    out = [Part("object", v.name("object", label=say("objects", str(params.get("object")), v.locale)), "object")]
    surface = surface_kind(params)
    if surface != "none":
        out.append(Part("surface", v.name("surface"), "line"))
    forces = [f for f in params.get("forces", []) if isinstance(f, dict) and "id" in f]
    for f in forces:
        out.append(
            Part(
                f["id"],
                v.name("force", label=f"{f.get('name', f['id'])} {f.get('magnitude', '')}".strip()),
                "force",
                quizzable=True,
            )
        )
    ids = {f["id"] for f in forces}
    incline = surface == "incline"
    for add in v.adds():
        target = add.get("of")
        if add.get("element") == "components_of" and target in ids:
            first, second = ("parallel", "perpendicular") if incline else ("x", "y")
            key = "component_parallel" if incline else "component_x"
            out.append(Part(f"{target}.{first}", v.name(key, label=target), "component"))
            key = "component_perpendicular" if incline else "component_y"
            out.append(Part(f"{target}.{second}", v.name(key, label=target), "component"))
        if add.get("element") == "resultant":
            out.append(Part("resultant", v.name("resultant"), "force"))
    if params.get("show_resultant") and not any(p.id == "resultant" for p in out):
        out.append(Part("resultant", v.name("resultant"), "force"))
    return _unique(out)


def surface_kind(params: dict[str, Any]) -> str:
    """none, horizontal, incline, vertical_wall or hanging: stated, else an incline when it has an angle."""
    surface = params.get("surface")
    if not isinstance(surface, dict) or not surface:
        return "none"
    if surface.get("kind"):
        return str(surface["kind"])
    return "incline" if float(surface.get("incline_deg", 0) or 0) > 0 else "horizontal"


def _function_graph(v: View) -> Parts:
    out = [
        Part(s["id"], v.name("region", label=s["id"]), "region")
        for s in v.params.get("shade", []) or []
        if isinstance(s, dict) and "id" in s
    ]
    curves = [c for c in v.params.get("curves", []) if isinstance(c, dict) and "id" in c]
    out += [Part(c["id"], v.name("curve", label=c.get("label") or c.get("expr", c["id"])), "curve") for c in curves]
    for c in curves:
        for feature in (v.computed.get("features") or {}).get(c["id"], []):
            out.append(Part(f"{c['id']}.{feature['id']}", v.name("point", label=feature["label"]), "point"))
    for p in v.params.get("points", []) or []:
        if isinstance(p, dict) and "id" in p:
            out.append(Part(p["id"], v.name("point", label=p.get("label", p["id"])), "point"))
    return _unique(out)


def _number_line(v: View) -> Parts:
    out = [Part("line", v.name("line"), "line", focusable=False)]
    for interval in v.params.get("intervals", []):
        out.append(Part(interval["id"], v.name("interval", label=interval["id"]), "region"))
        for end in ("from", "to"):
            if str(interval.get(end)) not in ("-inf", "inf"):
                out.append(Part(f"{interval['id']}.{end}", v.name("endpoint", value=interval[end]), "point"))
    return out


def _geometry(v: View) -> Parts:
    figure = v.params.get("figure")
    if figure == "triangle":
        names = v.params.get("vertices") or ["A", "B", "C"]
        out = [Part(f"side_{s}", v.name("side", label=v.label(f"side_{s}", s)), "line", quizzable=True) for s in "abc"]
        out += [
            Part(f"angle_{a}", v.name("angle", label=v.label(f"angle_{a}", n)), "angle", quizzable=True)
            for a, n in zip("ABC", names, strict=True)
        ]
        return out + [Part(n, v.name("vertex", label=n), "vertex") for n in names]
    if figure == "circle":
        return [
            Part("circle", v.name("circle"), "line"),
            Part("sector", v.name("region", label="sector"), "region"),
            Part("radius", v.name("radius"), "line", quizzable=True),
            Part("chord", v.name("chord"), "line"),
            Part("arc", v.name("arc"), "line"),
            Part("O", v.name("centre", label="O"), "vertex"),
        ]
    if figure == "circle_theorem":
        out = [Part("circle", v.name("circle"), "line", focusable=False)]
        if v.params.get("theorem") in ("tangent_radius", "alternate_segment"):
            out.append(Part("tangent", v.name("tangent"), "line"))
        out += [
            Part("angle_given", v.name("angle", label=v.label("angle_given", "x")), "angle", quizzable=True),
            Part("angle_derived", v.name("angle", label=v.label("angle_derived", "y")), "angle", quizzable=True),
        ]
        out.append(Part("O", v.name("centre", label="O"), "vertex"))
        return out + [
            Part(p, v.name("vertex", label=p), "vertex") for p in theorem_points(str(v.params.get("theorem")))
        ]
    if figure == "parallel_lines":
        out = [
            Part("line_1", v.name("line_named", label="1"), "line"),
            Part("line_2", v.name("line_named", label="2"), "line"),
            Part("transversal", v.name("transversal"), "line"),
        ]
        return out + [Part(a, v.name("angle", label=a), "angle", quizzable=True) for a in "abcdefgh"]
    return []


THEOREM_POINTS: dict[str, list[str]] = {
    "angle_at_centre": ["A", "B", "P"],
    "angle_at_circumference": ["A", "B", "P"],
    "same_segment": ["A", "B", "P", "Q"],
    "semicircle": ["A", "B", "P"],
    "cyclic_quadrilateral": ["P", "Q", "R", "S"],
    "tangent_radius": ["P", "T"],
    "alternate_segment": ["T", "A", "B"],
    "isosceles_radii": ["A", "B"],
}


def theorem_points(theorem: str) -> list[str]:
    return THEOREM_POINTS.get(theorem, ["A", "B", "P"])


def _unit_circle(v: View) -> Parts:
    show = v.params.get("show") or ["sin", "cos"]
    out = [Part("circle", v.name("circle"), "line", focusable=False)]
    if "quadrant_signs" in show:
        out += [Part(f"q{n}", v.name("quadrant", label=str(n)), "region") for n in range(1, 5)]
    for ratio in ("cos", "sin", "tan"):
        if ratio in show and (ratio != "tan" or v.label("leg_tan")):
            out.append(Part(f"leg_{ratio}", v.name(f"leg_{ratio}"), "line", quizzable=True))
    return [*out, Part("angle", v.name("angle", label="θ"), "angle"), Part("P", v.name("unit_circle_point"), "point")]


def _venn(v: View) -> Parts:
    out = [
        Part(f"set_{s['id']}", v.name("set", label=s.get("label", s["id"])), "region") for s in v.params.get("sets", [])
    ]
    for region in v.params.get("regions", []):
        rid = region["id"]
        name = v.name("outside") if rid == "none" else v.name("venn_region", label=rid)
        out.append(Part(f"region_{rid}", name, "region", quizzable=True))
    return out


def _statistics(v: View) -> Parts:
    chart = v.params.get("chart")
    if chart == "box_plot":
        return [
            Part(k, v.name("box_part", label=k.replace("_", " ")), "point")
            for k in ("min", "q1", "median", "q3", "max")
        ]
    if chart in ("bar", "pie"):
        role, key = ("region", "sector") if chart == "pie" else ("region", "bar")
        return [Part(c["id"], v.name(key, label=c["label"]), role) for c in v.params.get("categories", [])]
    role = "region" if chart == "histogram" else "point"
    return [
        Part(c["id"], v.name("class", label=f"{c['lower']} to {c['upper']}"), role) for c in v.params.get("classes", [])
    ]


def _matrix(v: View) -> Parts:
    out = []
    for r, row in enumerate(v.params.get("rows", []), 1):
        for c, _ in enumerate(row, 1):
            out.append(Part(f"r{r}c{c}", v.name("cell", row=r, col=c), "cell", quizzable=True))
    return out


def _bearing(v: View) -> Parts:
    a, b = v.params.get("from", "P"), v.params.get("to", "Q")
    out = [
        Part(f"north_{a}", v.name("north", label=a), "line", focusable=False),
        Part(a, v.name("vertex", label=a), "vertex"),
        Part(b, v.name("vertex", label=b), "vertex"),
        Part("path", v.name("bearing_path", **{"from": a, "to": b}), "line"),
        Part("bearing", v.name("bearing_angle", **{"from": a, "to": b}), "angle", quizzable=True),
    ]
    show = set(v.params.get("show") or []) | {a.get("element") for a in v.adds()}
    if "back_bearing" in show:
        out += [
            Part(f"north_{b}", v.name("north", label=b), "line", focusable=False),
            Part("back_bearing", v.name("back_bearing"), "angle", quizzable=True),
        ]
    if "components" in show:
        out += [Part("east", v.name("east"), "line"), Part("north", v.name("northc"), "line")]
    return out


def _motion_graph(v: View) -> Parts:
    points = v.params.get("points", [])
    out = [Part(s["id"], v.name("region", label=s["id"]), "region") for s in v.params.get("shade", [])]
    out += [Part(g["id"], v.name("gradient", label=g["id"]), "region") for g in v.params.get("gradient", [])]
    out += [
        Part(f"seg_{a['id']}_{b['id']}", v.name("segment", label=f"{a['id']} to {b['id']}"), "line")
        for a, b in pairwise(points)
    ]
    if v.params.get("curve") and v.computed.get("curve"):
        out.append(Part("curve", v.name("curve", label=v.params["curve"].get("expr", "")), "curve"))
    return out + [Part(p["id"], v.name("point", label=p["id"]), "point") for p in points]


def _wave(v: View) -> Parts:
    markers = v.params.get("markers") or ["wavelength"]
    out = [Part("wave", v.name("wave"), "curve")]
    return out + [Part(m, v.name(m), "label", quizzable=True) for m in markers]


def _particles(v: View) -> Parts:
    if v.params.get("mode") == "state":
        return [
            Part("container", v.name("container"), "region", focusable=False),
            Part("particles", v.name("particles"), "region"),
        ]
    out = [Part("before", v.name("before"), "region"), Part("after", v.name("after"), "region")]
    for i, species in enumerate(v.computed.get("species", [])):
        out.append(Part(f"sp{i + 1}", v.name("species", label=species["formula"]), "label", quizzable=True))
    return out


def _shells(v: View) -> Parts:
    out = [Part("nucleus", v.name("nucleus", label=v.params.get("element", "")), "point")]
    for n, _ in enumerate(v.computed.get("shells", []), 1):
        out.append(Part(f"shell_{n}", v.name("shell", label=str(n)), "line", quizzable=True))
    partner = v.computed.get("partner")
    if partner:
        out.append(Part("partner_nucleus", v.name("nucleus", label=partner["element"]), "point"))
        for n, _ in enumerate(partner.get("shells", []), 1):
            out.append(Part(f"partner_shell_{n}", v.name("shell", label=f"{partner['element']} {n}"), "line"))
    return out


def _periodic(v: View) -> Parts:
    out = [Part(f"group_{g}", v.name("group", label=g), "label") for g in GROUP_LABELS]
    out += [Part(f"period_{p}", v.name("period", label=str(p)), "label") for p in range(1, 8)]
    highlight = v.params.get("highlight") or {}
    if highlight.get("kind") == "elements":
        out += [
            Part(f"el_{s}", v.name("element", label=s), "cell", quizzable=True) for s in highlight.get("values", [])
        ]
    if v.params.get("trend"):
        out.append(Part("trend", v.name("trend"), "line"))
    return out


GROUP_LABELS = ("1", "2", "3", "4", "5", "6", "7", "0")


def _energy(v: View) -> Parts:
    out = [
        Part("reactants", v.name("reactants"), "label", quizzable=True),
        Part("products", v.name("products"), "label", quizzable=True),
        Part("path", v.name("path"), "curve"),
    ]
    if v.params.get("activation_energy") is not None:
        out.append(Part("activation_energy", v.name("activation_energy"), "label", quizzable=True))
    if v.params.get("enthalpy_change") is not None:
        out.append(Part("enthalpy_change", v.name("enthalpy_change"), "label", quizzable=True))
    if v.params.get("catalysed") or any(a.get("element") == "catalysed_path" for a in v.adds()):
        out.append(Part("catalysed_path", v.name("catalysed_path"), "curve"))
    return out


def _journal(v: View) -> Parts:
    out = [
        Part(line["id"], v.name("entry_line", label=f"{line['side']} {line['account']}"), "row")
        for line in v.params.get("lines", [])
    ]
    out += [Part("total_debit", v.name("total_debit"), "cell"), Part("total_credit", v.name("total_credit"), "cell")]
    if v.params.get("narration"):
        out.append(Part("narration", v.name("narration"), "row"))
    return out


def _statements(v: View) -> Parts:
    return [
        Part(line["id"], v.name("statement_line", label=line["label"]), "row") for line in v.computed.get("lines", [])
    ]


def _reconciliation(v: View) -> Parts:
    return [
        Part(line["id"], v.name("statement_line", label=line["label"]), "row") for line in v.computed.get("lines", [])
    ]


def _break_even(v: View) -> Parts:
    out = (
        [Part("margin_of_safety", v.name("margin_of_safety"), "region")]
        if v.params.get("output_units") is not None
        else []
    )
    out += [Part(k, v.name(k), "line") for k in ("fixed_cost", "total_cost", "revenue")]
    return [*out, Part("break_even", v.name("break_even"), "point", quizzable=True)]


def tree_paths(
    branches: list[dict[str, Any]], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    for b in branches:
        path = (*prefix, str(b["id"]))
        yield path, b
        yield from tree_paths(b.get("then", []), path)


def _probability_tree(v: View) -> Parts:
    out = []
    leaves = []
    for path, branch in tree_paths(v.params.get("branches", [])):
        out.append(
            Part(
                "b_" + "_".join(path), v.name("branch", label=branch.get("label", branch["id"])), "line", quizzable=True
            )
        )
        if not branch.get("then"):
            leaves.append(path)
    if v.params.get("show_outcomes", True):
        out += [Part("o_" + "_".join(p), v.name("outcome", label=" then ".join(p)), "label") for p in leaves]
    return out


def _transformation(v: View) -> Parts:
    labels = [p["label"] for p in v.params.get("object", [])]
    out = [Part("object", v.name("object_shape"), "region"), Part("image", v.name("image_shape"), "region")]
    kind = (v.params.get("transformation") or {}).get("kind")
    extra = {
        "reflection": ("mirror", "mirror"),
        "rotation": ("centre", "centre_point"),
        "enlargement": ("centre", "centre_point"),
        "translation": ("vector", "vector"),
    }.get(str(kind))
    if extra:
        out.append(Part(extra[0], v.name(extra[1]), "line"))
    out += [Part(f"object.{n}", v.name("object_vertex", label=n), "vertex") for n in labels]
    return out + [Part(f"image.{n}", v.name("image_vertex", label=n + "'"), "vertex") for n in labels]


def _motion_diagram(v: View) -> Parts:
    marks = int(v.params.get("marks", 0))
    show = set(v.params.get("show") or []) | {"velocity" for a in v.adds() if a.get("element") == "velocity_arrows"}
    out = [Part(f"dot_{i}", v.name("dot", label=str(i)), "point") for i in range(marks)]
    if "velocity" in show:
        out += [Part(f"v_{i}", v.name("velocity", label=str(i)), "line") for i in range(marks)]
    if "acceleration" in show:
        out.append(Part("acceleration", v.name("acceleration"), "line"))
    return out


def _circuit(v: View) -> Parts:
    out = []
    readings = v.computed.get("labels") or {}
    for c in v.params.get("components", []):
        out.append(
            Part(
                c["id"],
                v.name("component", label=c.get("label") or f"{c['type'].replace('_', ' ')} {c['id']}"),
                "component",
                quizzable=True,
            )
        )
        if f"{c['id']}.reading" in readings:
            out.append(Part(f"{c['id']}.reading", v.name("reading", label=c["id"]), "label"))
    return out


def _ray(v: View) -> Parts:
    optic = str(v.params.get("optic", ""))
    out = [
        Part("optic", v.name("optic", label=optic.replace("_", " ")), "line"),
        Part("principal_axis", v.name("principal_axis"), "line", focusable=False),
        Part("object", v.name("object_arrow"), "point", quizzable=True),
    ]
    if v.computed.get("image_top") is not None and "image" in (v.params.get("show") or ["image"]):
        out.append(Part("image", v.name("image_arrow"), "point", quizzable=True))
    focal = (v.computed.get("focal_points") or [])[:2]
    out += [Part(f"F{n}", v.name("focal_point", label="F"), "point") for n in range(1, len(focal) + 1)]
    out += [Part(f"ray.{r}", v.name("ray", label=r), "ray") for r in v.computed.get("rays", [])]
    return out


def _balanced(v: View) -> Parts:
    out = []
    for side, prefix in (("reactants", "r"), ("products", "p")):
        for i, s in enumerate(v.params.get(side, []), 1):
            out.append(Part(f"{prefix}{i}", v.name("species_term", label=s.get("formula", "")), "label"))
    if v.params.get("show_atom_table", True):
        out += [
            Part(f"atoms.{row['element']}", v.name("atom_row", label=row["element"]), "row")
            for row in v.computed.get("atom_counts", [])
        ]
    return out


def _t_account(v: View) -> Parts:
    """Account by account, as drawn: its heading, its postings in entry order, then its balance carried down."""
    out = []
    balances = v.computed.get("balances") or {}
    for account in v.params.get("accounts", []):
        aid = account["id"]
        out.append(Part(aid, v.name("account", label=account["name"]), "region"))
        for entry in v.params.get("entries", []):
            for side in ("debit", "credit"):
                if entry[side] == aid:
                    out.append(Part(f"{aid}.{entry['id']}", v.name("posting", label=f"{entry['id']} {side}"), "row"))
        if v.params.get("show_balances", True) and aid in balances:
            out.append(Part(f"{aid}.balance_cd", v.name("balance_cd", label=account["name"]), "row"))
    return out


def _trial_balance(v: View) -> Parts:
    out = [
        Part(f"row_{i}", v.name("tb_row", label=row["account"]), "row")
        for i, row in enumerate(v.computed.get("rows", []), 1)
    ]
    out += [Part("total_debit", v.name("total_debit"), "cell"), Part("total_credit", v.name("total_credit"), "cell")]
    if v.computed.get("agrees") is False:
        out.append(Part("mismatch", v.name("mismatch"), "cell"))
    return out


def _titration(v: View) -> Parts:
    marks = v.params.get("marks") or []
    out = []
    if "indicator_range" in marks and v.params.get("indicator", "none") != "none":
        out.append(Part("indicator_range", v.name("indicator_range"), "region"))
    out += [
        Part("curve", v.name("titration_curve"), "curve"),
        Part("equivalence", v.name("equivalence"), "point", quizzable=True),
    ]
    if "half_equivalence" in marks:
        out.append(Part("half_equivalence", v.name("half_equivalence"), "point"))
    if "start_ph" in marks:
        out.append(Part("start_ph", v.name("start_ph"), "point"))
    return out


def _library(v: View) -> Parts:
    entry = v.entry or {}
    parts = entry.get("parts", [])
    if parts and isinstance(parts[0], str):  # a reference without part names
        return [Part(p, p.replace("_", " "), "part", quizzable=True) for p in parts]
    ordered = sorted(parts, key=lambda p: (p.get("tab_order", 0), p["id"]))
    return [Part(p["id"], p["name"], "part", quizzable=p.get("quizzable", True)) for p in ordered]


def _sim(v: View) -> Parts:
    return [Part(p["id"], v.name(p["role"], label=p["label"]), p["role"]) for p in v.computed.get("parts", [])]


PARTS: dict[str, Callable[[View], Parts]] = {
    "free_body": _free_body,
    "function_graph": _function_graph,
    "number_line": _number_line,
    "geometry_figure": _geometry,
    "unit_circle": _unit_circle,
    "venn_diagram": _venn,
    "statistics_chart": _statistics,
    "matrix_table": _matrix,
    "bearing_diagram": _bearing,
    "motion_graph": _motion_graph,
    "wave_diagram": _wave,
    "particle_diagram": _particles,
    "electron_shells": _shells,
    "periodic_table": _periodic,
    "energy_profile": _energy,
    "journal_entry": _journal,
    "financial_statements": _statements,
    "bank_reconciliation": _reconciliation,
    "break_even_chart": _break_even,
    "probability_tree": _probability_tree,
    "transformation_grid": _transformation,
    "motion_diagram": _motion_diagram,
    "circuit": _circuit,
    "ray_diagram": _ray,
    "balanced_equation": _balanced,
    "t_account": _t_account,
    "trial_balance": _trial_balance,
    "titration_curve": _titration,
    "library_diagram": _library,
    "projectile_sim": _sim,
    "circuit_sim": _sim,
    "titration_sim": _sim,
    "gas_laws_sim": _sim,
    "function_transform_sim": _sim,
    "electrolysis_sim": _sim,
    "rates_sim": _sim,
    "equilibrium_sim": _sim,
}


def _unique(parts: Parts) -> Parts:
    seen: set[str] = set()
    out = []
    for p in parts:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out


def parts_of(view: View) -> Parts:
    rule = PARTS.get(view.kind)
    try:
        return _unique(rule(view)) if rule else []
    except (KeyError, TypeError, ValueError, AttributeError):  # a malformed request has no parts; stage 4 says why
        return []


# --- alternative text (VSL-14) ---------------------------------------------------------------------------------------


def _join(items: list[str], locale: str) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + say("alt", "and", locale) + items[-1]


def _alt(v: View) -> str:
    def a(key: str, **kw: Any) -> str:
        return say("alt", key, v.locale, **kw)

    p, c, label = v.params, v.computed, v.label
    kind = v.kind
    if kind == "free_body":
        forces = [
            a("free_body_force", name=f.get("name", f.get("id")), magnitude=f.get("magnitude", ""))
            for f in p.get("forces", [])
            if isinstance(f, dict)
        ]
        return a("free_body", object=say("objects", str(p.get("object")), v.locale), forces=_join(forces, v.locale))
    if kind == "function_graph":
        curves = _join(
            [str(x.get("label") or x.get("expr")) for x in p.get("curves", []) if isinstance(x, dict)], v.locale
        )
        rng = p.get("x_range") or [0, 0]
        features = ""
        for curve in p.get("curves", []):
            for f in (c.get("features") or {}).get(curve.get("id"), []) if isinstance(curve, dict) else []:
                features += " " + f["say"]
        return a("function_graph", curves=curves, x_from=rng[0], x_to=rng[1], features=features)
    if kind == "number_line":
        var = p.get("variable", "x")
        parts = []
        for i in p.get("intervals", []):
            lo, hi = str(i["from"]), str(i["to"])
            if lo == "-inf":
                parts.append(a("number_line_more", variable=var, op="≤" if i.get("to_closed") else "<", value=hi))
            elif hi == "inf":
                parts.append(a("number_line_more", variable=var, op="≥" if i.get("from_closed") else ">", value=lo))
            else:
                parts.append(a("number_line_interval", variable=var, **{"from": lo, "to": hi}))
        return a("number_line", intervals=_join(parts, v.locale))
    if kind == "geometry_figure":
        figure = p.get("figure")
        if figure == "triangle":
            names = p.get("vertices") or ["A", "B", "C"]
            sides = _join([f"{s} = {label('side_' + s, '?')}" for s in "abc"], v.locale)
            angles = _join([f"{n} = {label('angle_' + k, '?')}°" for k, n in zip("ABC", names, strict=True)], v.locale)
            return a("geometry_triangle", vertices="".join(names), sides=sides, angles=angles)
        if figure == "circle":
            return a("geometry_circle", radius=label("radius", "r"), angle=label("sector", "?"))
        if figure == "circle_theorem":
            return a(
                "geometry_theorem",
                meaning=c.get("meaning", ""),
                given=label("angle_given", "?"),
                derived=label("angle_derived", "?"),
            )
        pairs = " ".join(a(f"pair_{k}") for k in (p.get("pairs") or ["corresponding", "alternate"]))
        given = a("geometry_parallel_given", value=p["givens"]["angle"]) if "angle" in (p.get("givens") or {}) else ""
        return a("geometry_parallel", given=given, pairs=pairs)
    if kind == "unit_circle":
        ratios = [
            a("unit_circle_ratio", name=r, value=label(f"leg_{r}")) for r in ("sin", "cos", "tan") if label(f"leg_{r}")
        ]
        return a("unit_circle", angle=p.get("angle_deg"), ratios=_join(ratios, v.locale))
    if kind == "venn_diagram":
        sets = _join([s.get("label", s["id"]) for s in p.get("sets", [])], v.locale)
        regions = [
            a("venn_region", region=r["id"], value=r.get("value", ", ".join(r.get("elements", []))))
            for r in p.get("regions", [])
        ]
        return a("venn_diagram", sets=sets, regions=_join(regions, v.locale))
    if kind == "statistics_chart":
        chart = p.get("chart")
        if chart == "box_plot":
            return a("statistics_box", **(p.get("summary") or {}))
        rows = p.get("categories") or []
        values = [f"{r['label']} {r['value']}" for r in rows] or [
            f"{r['lower']} to {r['upper']}: {r['frequency']}" for r in p.get("classes", [])
        ]
        what = a("chart_categories") if rows else a("chart_classes")
        return a(
            "statistics_chart", chart=a(f"chart_{chart}"), count=len(values), what=what, values=_join(values, v.locale)
        )
    if kind == "matrix_table":
        rows = p.get("rows", [])
        return a(
            "matrix_table",
            table=a(f"table_{p.get('table')}"),
            rows=len(rows),
            cols=max((len(r) for r in rows), default=0),
        )
    if kind == "bearing_diagram":
        return a(
            "bearing_diagram",
            to=p.get("to"),
            bearing=p.get("bearing"),
            distance=p.get("distance"),
            back=label("back_bearing", "?"),
            **{"from": p.get("from")},
        )
    if kind == "motion_graph":
        points = p.get("points", [])
        first = f"({points[0]['t']}, {points[0]['value']})" if points else ""
        last = f"({points[-1]['t']}, {points[-1]['value']})" if points else ""
        return a("motion_graph", graph=a(f"graph_{p.get('graph')}"), count=len(points), first=first, last=last)
    if kind == "wave_diagram":
        amp = a("wave_amplitude", amplitude=p["amplitude"]) if p.get("amplitude") else ""
        return a("wave_diagram", wave=a(f"wave_{p.get('wave')}"), wavelength=p.get("wavelength"), amplitude=amp)
    if kind == "particle_diagram":
        if p.get("mode") == "state":
            return a("particle_state", state=a(f"state_{p.get('state', 'solid')}"))
        return a("particle_reaction", equation=c.get("equation", p.get("equation", "")))
    if kind == "electron_shells":
        charge = a("electron_charge", charge=p["charge"]) if p.get("charge") else ""
        partner = c.get("partner")
        bond = a("electron_bond", partner=partner["element"]) if partner else ""
        return a(
            "electron_shells",
            element=p.get("element"),
            shells=",".join(str(s) for s in c.get("shells", [])),
            charge=charge + bond,
        )
    if kind == "periodic_table":
        h = p.get("highlight")
        highlight = a("periodic_highlight", kind=h["kind"], values=_join(h["values"], v.locale)) if h else ""
        return a("periodic_table", highlight=highlight)
    if kind == "energy_profile":
        energies = ""
        if p.get("activation_energy"):
            energies += a("energy_activation", value=p["activation_energy"])
        if p.get("enthalpy_change"):
            energies += a("energy_enthalpy", value=p["enthalpy_change"])
        return a(
            "energy_profile",
            reaction=a(f"reaction_{p.get('reaction')}"),
            reactants=p.get("reactants", ""),
            products=p.get("products", ""),
            energies=energies,
        )
    if kind == "journal_entry":
        lines = [
            a("journal_line", side=a(f"side_{x['side']}"), account=x["account"], amount=x["amount"])
            for x in p.get("lines", [])
        ]
        return a(
            "journal_entry", lines=_join(lines, v.locale), debit=label("total_debit"), credit=label("total_credit")
        )
    if kind == "financial_statements":
        lines = c.get("lines", [])
        last = f"{lines[-1]['label']} {label(lines[-1]['id'])}" if lines else ""
        return a("financial_statements", statement=a(f"statement_{p.get('statement')}"), count=len(lines), last=last)
    if kind == "bank_reconciliation":
        lines = [f"{x['label']} {label(x['id'])}" for x in c.get("lines", [])]
        return a("bank_reconciliation", cash=c.get("updated_balance", ""), lines=_join(lines, v.locale))
    if kind == "break_even_chart":
        margin = a("break_even_margin", units=label("margin_units")) if label("margin_units") else ""
        return a(
            "break_even_chart",
            fixed=label("fixed_cost"),
            units=label("break_even_units"),
            revenue=label("break_even_revenue"),
            margin=margin,
        )
    if kind == "probability_tree":
        outcomes = [
            a("probability_outcome", path=" then ".join(path), p=label("o_" + "_".join(path)))
            for path, b in tree_paths(p.get("branches", []))
            if not b.get("then")
        ]
        return a("probability_tree", count=len(outcomes), outcomes=_join(outcomes, v.locale))
    if kind == "transformation_grid":
        obj = "".join(x["label"] for x in p.get("object", []))
        return a(
            "transformation_grid",
            kind=(p.get("transformation") or {}).get("kind", ""),
            object=obj,
            image="".join(x["label"] + "'" for x in p.get("object", [])),
        )
    if kind == "motion_diagram":
        return a(
            "motion_diagram",
            marks=p.get("marks"),
            axis=a(f"axis_{p.get('axis')}"),
            u=p.get("initial_velocity"),
            a=p.get("acceleration"),
        )
    if kind == "circuit":
        comps = _join([f"{x['type'].replace('_', ' ')} {x['id']}" for x in p.get("components", [])], v.locale)
        readings = "".join(
            a("circuit_reading", id=k.split(".")[0], value=val)
            for k, val in sorted((c.get("labels") or {}).items())
            if k.endswith(".reading")
        )
        return a("circuit", components=comps, readings=readings)
    if kind == "ray_diagram":
        return a(
            "ray_diagram",
            optic=str(p.get("optic", "")).replace("_", " "),
            u=p.get("object_distance"),
            v=label("image_distance", "?"),
            nature=c.get("nature_text", ""),
            m=label("magnification", "?"),
        )
    if kind == "balanced_equation":
        return a("balanced_equation", equation=c.get("equation", ""))
    if kind == "t_account":
        balances = [
            a("t_account_balance", account=acc["name"], amount=b["amount"], side=a(f"side_{b['side']}"))
            for acc in p.get("accounts", [])
            for b in [(c.get("balances") or {}).get(acc["id"])]
            if b
        ]
        names = _join([acc["name"] for acc in p.get("accounts", [])], v.locale)
        return a("t_account", accounts=names) + (" " + "; ".join(balances) + "." if balances else "")
    if kind == "trial_balance":
        agree = (
            a("trial_balance_agrees") if c.get("agrees") else a("trial_balance_differs", difference=c.get("difference"))
        )
        return a("trial_balance", debit=label("total_debit"), credit=label("total_credit"), agree=agree)
    if kind == "titration_curve":
        return a(
            "titration_curve", start=label("start_ph"), volume=label("equivalence_volume"), ph=label("equivalence")
        )
    if kind == "library_diagram":
        return a("library_diagram", alt=(v.entry or {}).get("alt_text", ""))
    if kind in SIM_KINDS:
        # A predict scenario's description never gives the result away before the student predicts (VSL-47).
        return a(f"{kind}_predict" if p.get("predict") else kind, **c.get("alt", {}))
    return a("fallback", kind=kind.replace("_", " "))


def alt_of(view: View, parts: Parts) -> dict[str, Any]:
    """`alt.summary` and one line per step, from the resolved spec (VSL-14)."""
    try:
        summary = _alt(view)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        summary = say("alt", "fallback", view.locale, kind=view.kind.replace("_", " "))
    names = {p.id: p.name for p in parts}
    lines = []
    sequence = _sequence(view)
    for n, step in enumerate(view.steps, 1):
        if sequence and n - 1 < len(sequence):
            lines.append(say("alt", "step_caption", view.locale, n=n, caption=sequence[n - 1].get("caption", "")))
            continue
        bits = []
        for key in ("highlight", "reveal", "hide"):
            if step.get(key):
                bits.append(
                    say(
                        "alt",
                        f"step_{key}",
                        view.locale,
                        n=n,
                        parts=_join([names.get(x, x) for x in step[key]], view.locale),
                    )
                )
        if step.get("add"):
            added = [f"{x['element'].replace('_', ' ')} {x.get('of', '')}".strip() for x in step["add"]]
            bits.append(say("alt", "step_add", view.locale, n=n, parts=_join(added, view.locale)))
        lines.append(" ".join(bits) or say("alt", "step_plain", view.locale, n=n))
    return {"summary": summary[:600], "steps": [line[:300] for line in lines[:20]], "locale": view.locale}


def _sequence(view: View) -> list[dict[str, Any]]:
    if view.kind != "library_diagram" or not view.entry:
        return []
    wanted = view.params.get("sequence")
    for seq in view.entry.get("sequences", []):
        if seq.get("id") == wanted:
            steps: list[dict[str, Any]] = seq.get("steps", [])
            return steps
    return []
