import json
from pathlib import Path

import pytest


NOTEBOOKS = (
    "09_feature_engineering.ipynb",
    "10_model_development.ipynb",
    "11_model_evaluation.ipynb",
)
FORBIDDEN_TEST_ARTIFACTS = (
    "sepsis3_test_landmarks",
    "sepsis3_test_features",
    "septic_shock_test_landmarks",
    "septic_shock_test_features",
)


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_development_notebooks_are_clean_and_do_not_name_test_artifacts(name):
    path = Path(__file__).parents[1] / "notebooks" / name
    notebook = json.loads(path.read_text(encoding="utf-8"))
    source = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )
    assert not any(fragment in source for fragment in FORBIDDEN_TEST_ARTIFACTS)
    assert all(not cell.get("outputs") for cell in notebook["cells"])
    assert all(cell.get("execution_count") is None for cell in notebook["cells"])
