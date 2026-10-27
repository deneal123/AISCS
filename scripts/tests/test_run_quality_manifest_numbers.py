"""Quality evidence must use real integer counts, never JSON boolean surrogates."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "check_run_quality_gate.py"
SPEC = importlib.util.spec_from_file_location("quality_manifest_numbers", PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def payload(field, value):
    result = deepcopy(json.loads(gate.AGENTS_MANIFEST.read_text(encoding="utf-8")))
    result["scenarios"][0][field] = {"fixture_count": value}
    return result


@pytest.mark.parametrize("field", ["counts", "budgets"])
@pytest.mark.parametrize("value", [True, False])
def test_boolean_count_is_not_integer_evidence(field, value):
    with pytest.raises(ValueError, match="bounded integers"):
        gate._validate(
            gate.AGENTS_MANIFEST, payload(field, value), gate._REQUIRED_AGENT_SCENARIOS
        )


@pytest.mark.parametrize("field", ["counts", "budgets"])
@pytest.mark.parametrize("value", [0, 1, 200])
def test_nonnegative_integer_evidence_remains_valid(field, value):
    assert gate._validate(
        gate.AGENTS_MANIFEST, payload(field, value), gate._REQUIRED_AGENT_SCENARIOS
    )
