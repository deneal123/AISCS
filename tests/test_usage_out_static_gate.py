"""S26: mutable usage compatibility must stay isolated from production execution."""

from pathlib import Path


def _offenders(service):
    return [
        path.relative_to(service).as_posix()
        for path in service.rglob("*.py")
        if path.relative_to(service).as_posix() != "domain/usage/legacy.py"
        and "usage_out" in path.read_text(encoding="utf-8")
    ]


def test_usage_out_exists_only_in_legacy_adapter():
    assert _offenders(Path(__file__).parents[1] / "service") == []


def test_compatibility_exception_is_one_exact_path_not_a_reusable_filename(tmp_path):
    allowed = tmp_path / "domain/usage/legacy.py"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("usage_out = {}\n")
    forbidden = tmp_path / "elsewhere/legacy.py"
    forbidden.parent.mkdir()
    forbidden.write_text("usage_out = {}\n")
    assert _offenders(tmp_path) == ["elsewhere/legacy.py"]
