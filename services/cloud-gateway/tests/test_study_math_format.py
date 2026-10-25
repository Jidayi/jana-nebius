"""Displayed math requires delimiters; frozen citations and grading syntax must remain literal."""

import pytest
from cloud_gateway.study import Refused, bind_math_parts, generation_schema, retain_formatted, unformatted_maths


@pytest.mark.parametrize(
    "text", ["x_i=2", "w = (Phi^T Phi)^-1 Phi^T y", "∑ x_i", "Broken \x0crac{1}{2}", r"α\(t+1(i)\)"]
)
def test_displayed_equations_need_explicit_math_delimiters(text):
    assert unformatted_maths({"kind": "summary", "claims": [{"text": text}]})


@pytest.mark.parametrize(
    "text",
    [r"\(x_i=2\)", r"\[x_i=2\]", "$2x^2$", "It costs $20 and $35.", "A definition.", "The parameter θ has a prior."],
)
def test_delimited_math_and_plain_prose_are_accepted(text):
    assert not unformatted_maths({"kind": "summary", "claims": [{"text": text}]})


def test_every_display_surface_is_checked_without_rewriting_evidence_or_grading_keys():
    good = {"text": r"\(x_i=2\)", "citations": [{"quote": "x_i=2"}]}
    draft = {
        "kind": "quiz",
        "claims": [good],
        "quiz": {
            "items": [{"stem": good, "options": [{"text": r"\(x_i=2\)"}]}],
            "keys": [{"answer": "x_i=2", "calculation": "x_i=2", "explanation": good}],
        },
    }
    assert not unformatted_maths(draft)
    draft["quiz"]["items"][0]["options"][0]["text"] = "x_i=2"
    assert unformatted_maths(draft)
    assert not unformatted_maths({"kind": "audio_overview", "claims": [{"text": "x_i=2"}]})


def test_generation_contract_explains_math_format_for_claims_and_quiz_options():
    schema = generation_schema("quiz", "stj_" + "0" * 26, passage_ids=["p0"])
    claim = schema["properties"]["claims"]["items"]["properties"]["text"]
    assert "LaTeX" in claim["description"]


def test_nebius_parts_bind_to_renderable_text_and_leave_exact_quotes_and_keys_unchanged():
    quote = {"quote": "x_i=2"}
    display = [{"kind": "prose", "value": "The value is "}, {"kind": "math", "value": "x_i=2"}]
    draft = {
        "kind": "quiz",
        "claims": [{"text": display, "citations": [quote]}],
        "quiz": {
            "items": [{"options": [{"text": [{"kind": "math", "value": r"\frac{1}{2}"}]}]}],
            "keys": [{"answer": "x_i=2", "calculation": "1/2"}],
        },
    }
    bind_math_parts(draft)
    assert draft["claims"][0]["text"] == r"The value is \(x_i=2\)"
    assert draft["claims"][0]["citations"] == [quote]
    assert draft["quiz"]["items"][0]["options"][0]["text"] == r"\(\frac{1}{2}\)"
    assert draft["quiz"]["keys"][0] == {"answer": "x_i=2", "calculation": "1/2"}
    assert not unformatted_maths(draft)
    schema = generation_schema("quiz", "stj_" + "0" * 26, passage_ids=["p0"], structured_math=True)
    assert schema["properties"]["claims"]["items"]["properties"]["text"]["type"] == "array"
    assert schema["properties"]["quiz"]["properties"]["items"]["maxItems"] == 12
    assert schema["properties"]["claims"]["items"]["properties"]["text"]["maxItems"] == 16
    assert schema["properties"]["quiz"]["properties"]["items"]["items"]["type"] == "object"
    assert "anyOf" not in schema["properties"]["quiz"]["properties"]["items"]["items"]


@pytest.mark.parametrize("parts", [[], [{"kind": "html", "value": "x"}], [{"kind": "math", "value": 4}]])
def test_invalid_display_parts_are_withheld(parts):
    with pytest.raises(Refused):
        bind_math_parts({"text": parts})


def test_typed_math_parts_separate_words_but_keep_punctuation():
    value = {
        "text": [
            {"kind": "prose", "value": "Let"},
            {"kind": "math", "value": "x"},
            {"kind": "prose", "value": "be positive."},
            {"kind": "math", "value": "x>0"},
            {"kind": "prose", "value": "."},
        ]
    }
    bind_math_parts(value)
    assert value["text"] == r"Let \(x\) be positive. \(x>0\)."


def test_format_filter_keeps_whole_quiz_items_and_matching_keys_without_editing_evidence():
    good = {"text": r"The value is \(x_i=2\).", "citations": [{"quote": "x_i=2"}]}
    bad = {"text": "x_i=2"}
    draft = {
        "kind": "quiz",
        "claims": [bad],
        "quiz": {
            "items": [
                {"item_id": "a", "stem": good, "options": [good]},
                {"item_id": "b", "stem": good, "options": [bad]},
            ],
            "keys": [
                {"item_id": "a", "answer": "x_i=2", "explanation": good},
                {"item_id": "b", "answer": "x_i=2", "explanation": good},
            ],
        },
    }
    kept = retain_formatted(draft)
    assert kept["claims"] == [good]
    assert [q["item_id"] for q in kept["quiz"]["items"]] == ["a"]
    assert [k["item_id"] for k in kept["quiz"]["keys"]] == ["a"]
    assert kept["claims"][0]["citations"][0]["quote"] == "x_i=2"
    assert len(draft["quiz"]["items"]) == 2
    assert retain_formatted({"kind": "summary", "claims": [bad]}) is None
