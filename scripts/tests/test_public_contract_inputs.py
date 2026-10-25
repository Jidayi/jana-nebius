"""The fork's public inputs remain complete and cannot silently lose their checks."""

import json
from pathlib import Path

import pytest
from jana_tools import REPO_ROOT
from jana_tools.coverage import defined_test_locations
from jana_tools.fixtures import CORPUS, corpus_errors


def test_public_acceptance_inventory_names_real_tests():
    index = json.loads((REPO_ROOT / "contracts/policies/acceptance.json").read_text())
    expected = {name: paths for tests in index.values() for name, paths in tests.items()}
    assert len(expected) > 1000
    assert expected == defined_test_locations()


def test_public_source_examples_are_independent_of_the_generated_corpus(tmp_path: Path):
    import shutil

    shutil.copytree(CORPUS, tmp_path / "corpus")
    entries = json.loads((CORPUS / "index.json").read_text())
    example = next(e for e in entries if e["origin"] == "contract example")
    changed = tmp_path / "corpus" / example["file"]
    changed.write_text("{}\n")
    errors = corpus_errors(tmp_path / "corpus")
    assert errors == [f"evals/contracts/{example['file']} is stale; run: uv run python -m jana_tools fixtures --write"]


@pytest.mark.parametrize(
    "name,value",
    [
        ("event_registry", {"turn": "forever"}),
        ("event_registry", {"bad-name": "local"}),
        ("item_types", {"numeric": {"stage": "S9", "marker": "Key"}}),
        ("item_types", {"numeric": {"stage": "S2", "marker": ""}}),
        ("availability", {"mth": {"o": [["S2", None]]}}),
        ("availability", {"mth": {"o": [["S2", None], ["S2", None]], "a": [["S3", None]]}}),
    ],
)
def test_invalid_public_policies_cannot_generate_runtime_data(tmp_path: Path, name, value):
    from jana_tools.codegen.policies import read_policy

    (tmp_path / f"{name}.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="invalid"):
        read_policy(tmp_path, name)


def test_duplicate_public_policy_keys_fail_instead_of_overwriting(tmp_path: Path):
    from jana_tools.codegen.policies import read_policy

    (tmp_path / "event_registry.json").write_text('{"turn":"local","turn":"consented"}')
    with pytest.raises(ValueError, match="duplicate policy key"):
        read_policy(tmp_path, "event_registry")
