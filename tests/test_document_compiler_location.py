"""Never infer a failed block from an unrelated TeX warning location."""

import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    spec = importlib.util.spec_from_file_location("location_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("message", ["Unknown fatal condition", "Undefined control sequence"])
def test_warning_location_does_not_become_failure_provenance(message):
    log = f"content/safe.tex:8: LaTeX Warning: check layout.\n! {message}\nFatal error occurred"
    path, line, code = runner()._compiler_failure_location(log)
    assert path is None and line is None
    assert code in {"compile_failed", "undefined_control_sequence"}


@pytest.mark.parametrize(
    "number", ["0", "1000001", "1" * 5000], ids=["zero", "over_limit", "digit_overflow"]
)
def test_invalid_line_number_never_becomes_repair_location(number):
    log = f"content/body.tex:{number}: Undefined control sequence.\nFatal error occurred"
    path, line, code = runner()._compiler_failure_location(log)
    assert path is None and line is None and code == "undefined_control_sequence"


def test_explicit_recognized_error_still_has_a_bounded_location():
    log = (
        "content/safe.tex:8: LaTeX Warning: check layout.\ncontent/body.tex:23: Missing $ inserted."
    )
    assert runner()._compiler_failure_location(log) == ("body.tex", 23, "missing_math_delimiter")


@pytest.mark.parametrize("prefix", ["Warning:", "LaTeX Warning:", "Package example Warning:"])
def test_warning_quoting_error_words_does_not_locate_failure(prefix):
    log = (
        f"content/safe.tex:9: {prefix} Undefined control sequence mentioned.\nFatal error occurred"
    )
    path, line, _code = runner()._compiler_failure_location(log)
    assert path is None and line is None
