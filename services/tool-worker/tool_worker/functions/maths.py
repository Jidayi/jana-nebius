"""Mathematics functions (VER-03 to VER-07, VER-09, VER-10, VER-27).

Every function is a pure function of its arguments and the pinned libraries (VER-01): symbolic work runs inside a
time slice and answers `unknown` when the slice runs out (VER-27); numeric sampling is seeded from the arguments'
hash; outputs are canonical (sorted solutions, exact forms with LaTeX, decimals to stated precision)."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sympy as sp
from sympy.core.relational import Relational

from tool_worker.budget import SliceExpired, time_slice
from tool_worker.functions import constants
from tool_worker.functions.common import parse_arg
from tool_worker.functions.numeric import round_sf
from tool_worker.grammar import describe, exact_number
from tool_worker.protocol import Code, WorkerError
from tool_worker.registry import CallContext

Extras = dict[str, Any]


# --- shared ---------------------------------------------------------------------------------------------


def exact(value: sp.Basic, sf: int = 6) -> dict[str, Any]:
    """An exact value with its LaTeX and, when numeric, a decimal to `sf` significant figures."""
    out: dict[str, Any] = {"text": sp.sstr(value), "latex": sp.latex(value)}
    if value.is_number and value.is_real is not False:
        out["decimal"] = significant(sp.N(value, 30), sf)
    return out


def significant(value: sp.Basic, sf: int) -> str:
    """Round half away from zero to `sf` significant figures (VER-09: never banker's rounding)."""
    d = Decimal(str(sp.N(value, 40)))
    if d == 0:
        return "0"
    rounded = round_sf(d, sf)
    if rounded.adjusted() < -4 or rounded.adjusted() >= 12:  # standard form for very small or large values
        mantissa = rounded.scaleb(-rounded.adjusted())
        return f"{format(mantissa, 'f')}e{rounded.adjusted()}"
    return format(rounded, "f")


def decimal_places(value: sp.Basic, dp: int) -> str:
    d = Decimal(str(sp.N(value, 40)))
    return str(d.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP))


def slice_seconds(context: CallContext) -> float:
    return float(context.setting("symbolic_slice_ms", 800)) / 1000


def _sorted_values(values: list[sp.Basic]) -> list[sp.Basic]:
    def key(v: sp.Basic) -> tuple[int, float, str]:
        try:
            return (0, float(sp.N(v)), sp.sstr(v))
        except TypeError:
            return (1, 0.0, sp.sstr(v))

    return sorted(values, key=key)


def _variables(*trees: sp.Basic) -> list[sp.Symbol]:
    found: set[sp.Symbol] = set()
    for tree in trees:
        found |= tree.free_symbols
    return sorted(found, key=lambda s: s.name)


# --- math_parse (VER-03) ---------------------------------------------------------------------------------


def math_parse(args: dict[str, Any], context: CallContext) -> tuple[Any, Extras]:
    """Parse plain maths or the LaTeX subset with our own grammar (VER-03)."""
    parsed = parse_arg(args["text"], args)
    value = describe(parsed.tree)
    value["as_written_latex"] = sp.latex(parsed.as_written)
    return value, {"latex": value["latex"], "method": "exact", "confidence": "proved"}


# --- equivalence (VER-04, VER-05, VER-27) ----------------------------------------------------------------


def _undefined_points(expr: sp.Expr, var: sp.Symbol) -> set[sp.Basic]:
    """Real points where a rational subexpression divides by zero (finite sets only)."""
    points: set[sp.Basic] = set()
    for sub in sp.preorder_traversal(expr):
        if isinstance(sub, sp.Pow) and sub.exp.is_negative:
            zeros = sp.solveset(sub.base, var, sp.S.Reals)
            if isinstance(zeros, sp.FiniteSet):
                points |= set(zeros)
    return points


def _sample(var: sp.Symbol, rng: random.Random) -> sp.Basic:
    if var.is_integer:
        return sp.Integer(rng.randint(1 if var.is_positive else -6, 6))
    low = 0.1 if (var.is_positive or var.is_nonnegative) else -5.0
    return sp.Float(rng.uniform(low, 5.0), 30)


def _numeric(a: sp.Expr, b: sp.Expr, context: CallContext) -> tuple[str, dict[str, Any] | None, int]:
    """Compare at seeded points: ('equivalent' | 'not_equivalent' | 'unknown', counterexample, valid points)."""
    rng = random.Random(context.seed)
    points = int(context.setting("equivalence_points", 12))
    digits = int(context.setting("numeric_digits", 30))
    tolerance = float(context.setting("relative_tolerance", 1e-9))
    variables = _variables(a, b)
    valid = 0
    for _ in range(points * 3):
        if valid >= points:
            break
        point = {v: _sample(v, rng) for v in variables}
        try:
            va, vb = sp.N(a.subs(point), digits), sp.N(b.subs(point), digits)
        except (ZeroDivisionError, ValueError, TypeError):
            continue
        if not (va.is_real and vb.is_real) or va.has(sp.zoo, sp.nan, sp.oo) or vb.has(sp.zoo, sp.nan, sp.oo):
            continue
        valid += 1
        scale = max(1.0, abs(float(va)), abs(float(vb)))
        if abs(float(va - vb)) > tolerance * scale:
            example = {str(k): significant(v, 10) for k, v in point.items()}
            return "not_equivalent", {"at": example, "a": significant(va, 10), "b": significant(vb, 10)}, valid
    return ("equivalent" if valid >= int(context.setting("equivalence_min_valid", 8)) else "unknown"), None, valid


CHEAP = (sp.expand, sp.cancel, sp.together)
EXPENSIVE = (sp.trigsimp, sp.radsimp, sp.simplify)


def _reduce(difference: sp.Basic, transforms: tuple[Any, ...]) -> sp.Basic:
    for transform in transforms:
        difference = transform(difference)
        if difference == 0 or (difference.is_number and difference != 0):
            break
    return difference


def _decided(
    difference: sp.Basic, a: sp.Expr, b: sp.Expr, context: CallContext
) -> tuple[dict[str, Any], Extras] | None:
    """A symbolic verdict when the difference reduced to zero or to a non-zero number; None otherwise."""
    if difference == 0:
        variables = _variables(a, b)
        if len(variables) == 1:
            var = variables[0]
            only_a = _undefined_points(a, var) - _undefined_points(b, var)
            only_b = _undefined_points(b, var) - _undefined_points(a, var)
            if only_a or only_b:
                excluded = [
                    exact(p) | {"undefined_in": "a" if p in only_a else "b"}
                    for p in _sorted_values(list(only_a | only_b))
                ]
                return (
                    {"verdict": "equivalent_on_domain", "excluded_points": excluded},
                    {"method": "symbolic", "confidence": "proved"},
                )
        return {"verdict": "equivalent"}, {"method": "symbolic", "confidence": "proved"}
    if difference.is_number and difference.is_real and difference != 0:
        _, example, _ = _numeric(a, b, context)
        return (
            {"verdict": "not_equivalent", "difference": exact(difference), "counterexample": example},
            {"method": "symbolic", "confidence": "proved"},
        )
    return None


def _expressions(a: sp.Expr, b: sp.Expr, context: CallContext) -> tuple[dict[str, Any], Extras]:
    """Cheap symbolic reduction, then a seeded numeric screen (a counterexample proves non-equivalence), then the
    expensive simplifiers only when the samples agree. Expensive simplification of a false identity (such as
    log(x + 4) = log(x) + log(4)) can run until the slice expires; the screen answers it in milliseconds."""
    difference: sp.Basic = a - b
    try:
        with time_slice(slice_seconds(context)):
            difference = _reduce(difference, CHEAP)
            decided = _decided(difference, a, b, context)
            if decided:
                return decided
    except SliceExpired:
        pass
    try:
        with time_slice(slice_seconds(context)):
            verdict, example, valid = _numeric(a, b, context)
    except SliceExpired:
        return {"verdict": "unknown", "reason": "timeout"}, {"method": "heuristic", "confidence": "undecided"}
    if verdict == "not_equivalent":
        return (
            {"verdict": "not_equivalent", "counterexample": example},
            {"method": "numeric_sampling", "confidence": "proved"},
        )
    try:
        with time_slice(slice_seconds(context)):
            decided = _decided(_reduce(difference, EXPENSIVE), a, b, context)
            if decided:
                return decided
    except SliceExpired:
        pass
    if verdict == "equivalent":
        return {"verdict": "equivalent", "points": valid}, {"method": "numeric_sampling", "confidence": "sampled"}
    return (
        {"verdict": "unknown", "reason": "insufficient_points", "points": valid},
        {"method": "numeric_sampling", "confidence": "undecided"},
    )


def solution_set(relation: sp.Basic, var: sp.Symbol, domain: sp.Set = sp.S.Reals) -> sp.Set:
    if isinstance(relation, sp.Eq):
        return sp.solveset(relation.lhs - relation.rhs, var, domain)
    if isinstance(relation, sp.And):
        result = domain
        for part in relation.args:
            result = result.intersect(solution_set(part, var, domain))
        return result
    if isinstance(relation, Relational):
        return sp.solveset(relation, var, domain)
    raise WorkerError(Code.DOMAIN_ERROR, "not an equation or inequality")


def _any_element(s: sp.Set) -> sp.Basic | None:
    if isinstance(s, sp.FiniteSet) and s.args:
        return _sorted_values(list(s.args))[0]
    if isinstance(s, sp.Interval):
        lo, hi = s.inf, s.sup
        if lo.is_finite and hi.is_finite:
            return (lo + hi) / 2
        if lo.is_finite:
            return lo + 1
        if hi.is_finite:
            return hi - 1
        return sp.Integer(0)
    if isinstance(s, sp.Union):
        return _any_element(s.args[0])
    return None


def _relations(a: sp.Basic, b: sp.Basic, context: CallContext) -> tuple[dict[str, Any], Extras]:
    variables = _variables(a, b)
    try:
        with time_slice(slice_seconds(context)):
            if len(variables) == 1:
                var = variables[0]
                sa, sb = solution_set(a, var), solution_set(b, var)
                if isinstance(sa, sp.ConditionSet) or isinstance(sb, sp.ConditionSet):
                    return (
                        {"verdict": "unknown", "reason": "no_closed_form"},
                        {"method": "symbolic", "confidence": "undecided"},
                    )
                if sa == sb:
                    return {"verdict": "equivalent"}, {"method": "symbolic", "confidence": "proved"}
                witness = _any_element(sp.Complement(sa, sb)) or _any_element(sp.Complement(sb, sa))
                result: dict[str, Any] = {
                    "verdict": "not_equivalent",
                    "solutions_a": sp.sstr(sa),
                    "solutions_b": sp.sstr(sb),
                }
                if witness is not None:
                    result["counterexample"] = {"at": {var.name: exact(witness)["text"]}}
                return result, {"method": "symbolic", "confidence": "proved"}
            if isinstance(a, sp.Eq) and isinstance(b, sp.Eq):
                ratio = sp.simplify((a.lhs - a.rhs) / (b.lhs - b.rhs))
                if ratio.is_number and ratio != 0:
                    return {"verdict": "equivalent"}, {"method": "symbolic", "confidence": "proved"}
    except SliceExpired:
        return {"verdict": "unknown", "reason": "timeout"}, {"method": "heuristic", "confidence": "undecided"}
    return {"verdict": "unknown", "reason": "ambiguous"}, {"method": "symbolic", "confidence": "undecided"}


def math_check_equivalence(args: dict[str, Any], context: CallContext) -> tuple[Any, Extras]:
    """Equivalence of two expressions, equations or inequalities (VER-04) under assumptions (VER-05)."""
    a = parse_arg(args["a"], args, "a").tree
    b = parse_arg(args["b"], args, "b").tree
    is_relation = (isinstance(a, (Relational, sp.And)), isinstance(b, (Relational, sp.And)))
    if is_relation[0] != is_relation[1]:
        raise WorkerError(
            Code.DOMAIN_ERROR, "compare an equation with an equation, or an expression with an expression"
        )
    value, extras = (_relations if is_relation[0] else _expressions)(a, b, context)
    warnings = (
        [{"code": "assumption_added", "message": "variables are taken as real numbers"}]
        if not args.get("assumptions") and _variables(a, b)
        else []
    )
    if warnings:
        extras["warnings"] = warnings
    return value, extras


# --- solve (VER-07) ---------------------------------------------------------------------------------------

DOMAINS = {"real": sp.S.Reals, "integer": sp.S.Integers, "positive": sp.Interval.open(0, sp.oo)}


def _numeric_roots(expr: sp.Expr, var: sp.Symbol, interval: list[Any], context: CallContext) -> list[sp.Basic]:
    lo, hi = (exact_number(str(v), 0) for v in interval)
    roots: list[sp.Basic] = []
    steps = 200
    xs = [lo + (hi - lo) * sp.Rational(i, steps) for i in range(steps + 1)]
    values = []
    for x in xs:
        try:
            values.append(sp.N(expr.subs(var, x), 30))
        except (ZeroDivisionError, TypeError):
            values.append(sp.nan)
    for (x0, v0), (x1, v1) in zip(zip(xs, values, strict=True), zip(xs[1:], values[1:], strict=True), strict=False):
        if v0.is_real and v1.is_real and (v0 == 0 or v0 * v1 < 0):
            try:
                root = sp.nsolve(expr, var, (x0 + x1) / 2, prec=30, verify=True)
            except (ValueError, ZeroDivisionError):
                continue
            if lo <= root <= hi and not any(abs(root - r) < 1e-12 for r in roots):
                roots.append(root)
    return _sorted_values(roots)


def math_solve(args: dict[str, Any], context: CallContext) -> tuple[Any, Extras]:
    """Every solution in the domain, exact and to 6 significant figures (VER-07), with the constants used and their
    sources (VER-12) and the recorded positive direction for motion problems (VER-17)."""
    trees = [parse_arg(text, args, f"equations[{i}]").tree for i, text in enumerate(args["equations"])]
    if not all(isinstance(t, sp.Eq) for t in trees):
        raise WorkerError(Code.DOMAIN_ERROR, "math_solve takes equations; use the inequality tools for inequalities")
    from tool_worker.functions import quantities  # imported here: quantities builds on units, which imports maths

    try:
        trees, stated_units = quantities.apply(trees, args)  # VER-17: quantities with units, dimension-checked
        trees, constant_extras = constants.apply(trees, args, args.get("unknowns", []))
    except constants.ConventionMissing as no_convention:
        return no_convention.result()
    if any(t is sp.false for t in trees):
        value, extras = {"case": "no_solution"}, {"method": "symbolic", "confidence": "proved"}
    elif all(t is sp.true for t in trees):
        value, extras = {"case": "all_values"}, {"method": "symbolic", "confidence": "proved"}
    else:
        value, extras = _solve([t for t in trees if t is not sp.true], args, context)
    if args.get("positive_direction"):
        value["positive_direction"] = args["positive_direction"]
    solutions: list[dict[str, dict[str, Any]]] = list(value.get("solutions") or [])  # type: ignore[arg-type]
    for solution in solutions:
        for name in sorted(solution.keys() & stated_units.keys()):
            solution[name]["unit"] = stated_units[name]
    return value, {**extras, **constant_extras}


def _solve(trees: list[sp.Basic], args: dict[str, Any], context: CallContext) -> tuple[dict[str, Any], Extras]:
    equations: list[sp.Eq | None] = [t if isinstance(t, sp.Eq) else None for t in trees]
    names = args.get("unknowns") or [s.name for s in _variables(*trees)]
    symbols = {s.name: s for t in trees for s in t.free_symbols}
    unknowns = [symbols.get(n) or sp.Symbol(n, real=True) for n in names]
    domain_name = args.get("domain", "real")
    domain = DOMAINS[domain_name]
    try:
        with time_slice(slice_seconds(context)):
            if len(equations) == 1 and len(unknowns) == 1:
                eq, var = equations[0], unknowns[0]
                assert eq is not None
                result = sp.solveset(eq.lhs - eq.rhs, var, domain)
                if result == domain:
                    return {"case": "all_values"}, {"method": "symbolic", "confidence": "proved"}
                if result == sp.S.EmptySet:
                    return {"case": "no_solution"}, {"method": "symbolic", "confidence": "proved"}
                if isinstance(result, sp.FiniteSet):
                    solutions = [{var.name: exact(v)} for v in _sorted_values(list(result.args))]
                    return {"case": "solutions", "solutions": solutions}, {"method": "symbolic", "confidence": "proved"}
                if not isinstance(result, sp.ConditionSet):
                    return (
                        {"case": "parametric", "set": sp.sstr(result), "latex": sp.latex(result)},
                        {"method": "symbolic", "confidence": "proved"},
                    )
            else:
                solved = sp.solve([e.lhs - e.rhs for e in equations if e is not None], unknowns, dict=True)
                real = [s for s in solved if all(v.is_real is not False for v in s.values())]
                if not real:
                    return {"case": "no_solution"}, {"method": "symbolic", "confidence": "proved"}
                if any(len(s) < len(unknowns) for s in real):
                    return (
                        {"case": "parametric", "set": sp.sstr(real)},
                        {"method": "symbolic", "confidence": "proved"},
                    )
                ordered = sorted(real, key=lambda s: [float(sp.N(s[u])) for u in unknowns])
                solutions = [{u.name: exact(s[u]) for u in unknowns} for s in ordered]
                return {"case": "solutions", "solutions": solutions}, {"method": "symbolic", "confidence": "proved"}
    except SliceExpired:
        pass
    if len(equations) == 1 and len(unknowns) == 1 and args.get("interval"):
        eq = equations[0]
        assert eq is not None
        roots = _numeric_roots(eq.lhs - eq.rhs, unknowns[0], args["interval"], context)
        solutions = [{unknowns[0].name: {"decimal": significant(r, 6), "text": significant(r, 15)}} for r in roots]
        return (
            {"case": "solutions" if roots else "no_solution", "solutions": solutions, "numeric": True},
            {"method": "numeric_sampling", "confidence": "sampled"},
        )
    raise WorkerError(Code.DOMAIN_ERROR, "no exact solution; give an interval")


# --- simplify -------------------------------------------------------------------------------------------

FORMS = {"simplest": sp.simplify, "expanded": sp.expand, "factorised": sp.factor, "single_fraction": sp.together}


def math_simplify(args: dict[str, Any], context: CallContext) -> tuple[Any, Extras]:
    tree = parse_arg(args["expression"], args, "expression").tree
    if isinstance(tree, (Relational, sp.And)):
        raise WorkerError(Code.DOMAIN_ERROR, "simplify takes an expression, not an equation")
    form = args.get("form", "simplest")
    try:
        with time_slice(slice_seconds(context)):
            result = FORMS[form](tree)
    except SliceExpired:
        return {"status": "unknown", "reason": "timeout"}, {"method": "heuristic", "confidence": "undecided"}
    return (
        {"status": "ok", "form": form, "result": exact(result)},
        {"latex": sp.latex(result), "method": "symbolic", "confidence": "proved"},
    )


# --- evaluate (VER-09 subset, VER-05 angles) ---------------------------------------------------------------

TRIG = (sp.sin, sp.cos, sp.tan, sp.sec, sp.csc, sp.cot)
INVERSE_TRIG = (sp.asin, sp.acos, sp.atan)


def _in_degrees(tree: sp.Basic) -> sp.Basic:
    """Trig functions take degrees; inverse trig functions answer in degrees."""

    def convert(node: sp.Basic) -> sp.Basic:
        if not node.args:
            return node
        args = [convert(a) for a in node.args]
        if isinstance(node, TRIG):
            return node.func(args[0] * sp.pi / 180)
        if isinstance(node, INVERSE_TRIG):
            return node.func(args[0]) * 180 / sp.pi
        return node.func(*args)

    return convert(tree)


def math_evaluate(args: dict[str, Any], context: CallContext) -> tuple[Any, Extras]:
    tree = parse_arg(args["expression"], args, "expression").tree
    warnings = []
    level = args.get("level", "O")
    angle_unit = args.get("angle_unit")
    if angle_unit is None and tree.has(*TRIG, *INVERSE_TRIG):
        angle_unit = "degrees" if level == "O" else "radians"
        warnings.append({"code": "assumption_added", "message": f"angles are taken in {angle_unit}"})
    if angle_unit == "degrees":
        tree = _in_degrees(tree)
    given = sorted(set(args.get("values", {})) & {c["symbol"] for c in args.get("constants", [])})
    if given:
        raise WorkerError(Code.DOMAIN_ERROR, f"give {', '.join(given)} once: in values or in constants")
    try:
        [tree], constant_extras = constants.apply([tree], args)
    except constants.ConventionMissing as no_convention:
        return no_convention.result()
    warnings += constant_extras.pop("warnings", [])
    symbols = {s.name: s for s in tree.free_symbols}
    values = {}
    for name, raw in args.get("values", {}).items():
        if name not in symbols:
            continue
        values[symbols[name]] = exact_number(str(raw), 0) if isinstance(raw, (int, float, str)) else raw
    missing = sorted(set(symbols) - {s.name for s in values})
    if missing:
        raise WorkerError(Code.DOMAIN_ERROR, f"no value given for {', '.join(missing)}")
    try:
        with time_slice(slice_seconds(context)):
            # Parsed numbers and supplied constants are already exact. Searching
            # numerically for another closed form adds no evidence and can spend
            # the whole slice on ordinary non-special-angle trigonometry.
            result = sp.simplify(tree.subs(values))
    except SliceExpired:
        return {"status": "unknown", "reason": "timeout"}, {"method": "heuristic", "confidence": "undecided"}
    if result.has(sp.zoo, sp.nan) or result.is_real is False:
        raise WorkerError(Code.DOMAIN_ERROR, "the expression is undefined for these values")
    value: dict[str, Any] = {"status": "ok", "exact": exact(result)}
    if "sf" in args:
        value["rounded"] = significant(result, int(args["sf"]))
    elif "dp" in args:
        value["rounded"] = decimal_places(result, int(args["dp"]))
    extras: Extras = {"latex": sp.latex(result), "method": "exact", "confidence": "proved", **constant_extras}
    if warnings:
        extras["warnings"] = warnings
    return value, extras
