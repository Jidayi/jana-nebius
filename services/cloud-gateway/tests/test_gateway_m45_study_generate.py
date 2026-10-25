"""M45.b (STU-21, STU-22): the gateway narrows generation to the learner's chosen question types and gives chapters
their own response shape."""

from __future__ import annotations

from jsonschema import Draft202012Validator

JID = "stj_" + "0" * 26
STEM = {"text": "Question?", "citations": [{"passage_id": "p0"}]}


def test_stu21_settings_respected_question_types_narrow_the_schema():
    from cloud_gateway.study import generation_schema

    schema = generation_schema("quiz", JID, 4, passage_ids=["p0"], question_types=["fill_blank", "true_false"])
    validate = Draft202012Validator(schema["properties"]["quiz"]["properties"]["items"]["items"])
    assert validate.is_valid({"item_id": "q1", "type": "fill_blank", "stem": STEM})
    assert validate.is_valid({"item_id": "q2", "type": "true_false", "stem": STEM})
    options = [{"option_id": "a", "text": "One"}, {"option_id": "b", "text": "Two"}]
    assert not validate.is_valid({"item_id": "q3", "type": "choice", "stem": STEM, "options": options})
    assert not validate.is_valid({"item_id": "q4", "type": "numeric", "stem": STEM})
    assert not validate.is_valid({"item_id": "q2", "type": "true_false", "stem": STEM, "unit_prompt": ""})
    assert "calculation" not in schema["properties"]["quiz"]["properties"]["keys"]["items"]["properties"]
    both = generation_schema("quiz", JID, 4, passage_ids=["p0"], question_types=["multi_select"])
    check = Draft202012Validator(both["properties"]["quiz"]["properties"]["items"]["items"])
    assert check.is_valid({"item_id": "q5", "type": "multi_select", "stem": STEM, "options": options})
    assert not check.is_valid({"item_id": "q6", "type": "multi_select", "stem": STEM})


def test_stu22_chapters_and_seek_have_their_own_response_shape():
    from cloud_gateway.study import generation_schema

    schema = generation_schema("chapters", JID, passage_ids=["p0"])
    assert "chapters" in schema["required"] and "quiz" not in schema["properties"]
    chapter = {"start_ms": 0, "end_ms": 60000, "title": "Enzymes", "summary": [STEM]}
    draft = {"request_id": JID, "kind": "chapters", "claims": [STEM], "chapters": [chapter]}
    assert Draft202012Validator(schema).is_valid(draft)
    assert "chapters" not in generation_schema("notes", JID, passage_ids=["p0"])["properties"]
