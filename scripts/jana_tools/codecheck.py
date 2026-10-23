"""Static checks for code execution (SEC-07 in the worker, SEC-09 across the device code).

Flags any call that executes a string as code or loads code: eval, exec, compile, __import__, sympify or S on a
string, parse_expr, lambdify, pickle or marshal loads, os.system and subprocess with shell=True."""

from __future__ import annotations

import ast
from pathlib import Path

ALWAYS = {"eval", "exec", "compile", "__import__", "parse_expr", "lambdify", "execfile"}
LOADERS = {("pickle", "loads"), ("pickle", "load"), ("marshal", "loads"), ("marshal", "load"), ("os", "system"),
           ("os", "popen")}  # fmt: skip
SYMPIFY = {"sympify", "S"}


def _name(node: ast.expr) -> tuple[str | None, str]:
    if isinstance(node, ast.Name):
        return None, node.id
    if isinstance(node, ast.Attribute):
        owner = node.value.id if isinstance(node.value, ast.Name) else None
        return owner, node.attr
    return None, ""


def file_errors(path: Path, text: str | None = None) -> list[str]:
    source = text if text is not None else path.read_text()
    errors = []
    for node in ast.walk(ast.parse(source, str(path))):
        if isinstance(node, ast.ImportFrom) and any(a.name == "parse_expr" for a in node.names):
            errors.append(f"{path}:{node.lineno}: imports parse_expr")
        if not isinstance(node, ast.Call):
            continue
        owner, name = _name(node.func)
        where = f"{path}:{node.lineno}"
        if name in ALWAYS and owner in (None, "builtins", "sympy", "sp"):
            errors.append(f"{where}: calls {name}")
        elif (owner, name) in LOADERS:
            errors.append(f"{where}: calls {owner}.{name}")
        elif name in SYMPIFY and owner in (None, "sympy", "sp") and node.args:
            argument = node.args[0]
            if not (isinstance(argument, ast.Constant) and isinstance(argument.value, (int, float))):
                errors.append(f"{where}: calls {name} on something that may be a string")
        elif owner == "subprocess" and any(
            k.arg == "shell" and getattr(k.value, "value", False) for k in node.keywords
        ):
            errors.append(f"{where}: runs a shell")
    return errors


def tree_errors(roots: list[Path], exclude: tuple[str, ...] = ()) -> list[str]:
    errors = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if not any(part in exclude for part in path.parts):
                errors += file_errors(path)
    return errors
