"""Пустой или ошибочный root не даёт ложного зелёного quality gate."""

import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize("exists", [False, True])
def test_checker_rejects_missing_and_empty_source_roots(tmp_path, exists):
    checker = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/check_module_complexity.py")
    )
    root = tmp_path / "service"
    if exists:
        root.mkdir()
    with pytest.raises(checker["QualityError"], match="--root"):
        checker["evaluate"](root, [], checker["Thresholds"](750, 250, 70, 99, 99))
