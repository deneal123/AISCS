"""S26: mutable usage compatibility must stay isolated from production execution."""

from pathlib import Path


def test_usage_out_exists_only_in_legacy_adapter():
    service = Path(__file__).parents[1] / "service"
    offenders = [
        path.relative_to(service).as_posix()
        for path in service.rglob("*.py")
        if path.name != "legacy_usage.py" and "usage_out" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
