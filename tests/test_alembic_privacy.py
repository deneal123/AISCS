from pathlib import Path


def test_alembic_environment_never_prints_database_dsn() -> None:
    source = (Path(__file__).resolve().parents[1] / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )

    assert "print(" not in source
    assert "logger.info(url" not in source
    assert "logger.debug(url" not in source
    assert "Setting sqlalchemy.url" not in source
