"""LaTeX in a model's JSON is read as LaTeX, not as JSON escapes: the live memory evaluation found `\\times` read as a
tab and "imes", which corrupts an equation on the board as much as an answer. Inputs here are what models write."""

from __future__ import annotations

import json

from agent_core.providers.model_json import loads, repair_latex_escapes
from agent_core.providers.openai_compat import _arguments
from agent_core.router.normalise import _call_from_json
from agent_core.router.structured import check
from jsonschema import Draft202012Validator

WRITTEN = r'{"latex": "s = 4 \times 6 + \frac{1}{2} \cdot 3 \times 36", "note": "\nu = \beta \rho, \alpha \sqrt{2}"}'
MEANT = {
    "latex": "s = 4 \\times 6 + \\frac{1}{2} \\cdot 3 \\times 36",
    "note": "\\nu = \\beta \\rho, \\alpha \\sqrt{2}",
}


def test_latex_commands_survive_reading() -> None:
    assert loads(WRITTEN) == MEANT
    # Real escapes are untouched: a newline before a word, a tab, quotes, backslashes and unicode escapes.
    unicode_escapes = '{"t": "one\\ntwo\\tthree \\"q\\" \\\\ \\u00e9 \\u2212"}'
    assert loads(unicode_escapes) == {"t": 'one\ntwo\tthree "q" \\ é −'}
    # Correctly escaped LaTeX is unchanged, and so is text with no backslash at all.
    assert loads(json.dumps(MEANT)) == MEANT
    assert repair_latex_escapes('{"a": "plain"}') == '{"a": "plain"}'
    # Keys and the structure outside strings are never touched.
    assert loads(r'{"x\times": 1}') == {"x\\times": 1}


def test_structured_replies_keep_latex() -> None:
    validator = Draft202012Validator({"type": "object", "properties": {"latex": {"type": "string"}}})
    checked = check(WRITTEN, validator)
    assert checked.errors == [] and checked.value is not None and checked.value["latex"] == MEANT["latex"]
    # A backslash before a letter JSON never allows (\alpha) used to make the whole reply invalid.
    assert check(r'{"latex": "\alpha"}', validator).value == {"latex": "\\alpha"}


def test_tool_arguments_keep_latex() -> None:
    assert _arguments(r'{"expression": "\frac{1}{2} \times 4"}') == {"expression": "\\frac{1}{2} \\times 4"}
    call = _call_from_json(r'{"name": "math_evaluate", "arguments": {"expression": "\sqrt{2} \times \pi"}}')
    assert call == ("math_evaluate", {"expression": "\\sqrt{2} \\times \\pi"})


def test_non_object_replies_are_never_valid() -> None:
    # A loose schema can accept `null` or a list; a structured reply is one object or it is invalid (corrected once),
    # never "valid with no value", which broke the delegation envelope on small models.
    loose = Draft202012Validator({"properties": {"latex": {"type": "string"}}})
    for text in ("null", "[]", "3", '"plan"'):
        checked = check(text, loose)
        assert checked.value is None and checked.errors and "one JSON object" in checked.errors[0], text
    assert check('{"latex": "x"}', loose).errors == []
