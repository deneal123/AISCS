"""Инструмент `analyze_data` в сайдкаре: файлы приходят ССЫЛКАМИ, а не из хранилища.

Раньше здесь была ветка «ссылок нет → сходи в PG/MinIO сам». В сайдкаре этих
модулей не существует, поэтому вместо вежливого «нет табличных файлов» инструмент
падал ModuleNotFoundError — то есть самый обычный случай (пользователь ничего не
прикрепил) выглядел как поломка агента.
"""

import pytest

from service.domain.tools import function_tools


class _Ctx:
    """Минимальный RunContextWrapper: инструменту нужен только словарь контекста."""

    def __init__(self, data: dict):
        self.context = data


@pytest.mark.asyncio
async def test_no_files_returns_message_not_crash(monkeypatch):
    monkeypatch.setattr(
        "service.domain.tools.duckdb_client.DuckDBClient.enabled",
        property(lambda self: True),
    )

    res = await function_tools.analyze_data_tool(_Ctx({"user_id": "7"}), "{}")

    assert "Нет табличных файлов" in res


@pytest.mark.asyncio
async def test_storage_fallback_is_gone():
    """Ветка похода в хранилище удалена вместе с функцией — не должна вернуться."""
    from service.domain.tools import duckdb_client

    assert not hasattr(duckdb_client, "gather_user_tabular_files")
    assert not hasattr(duckdb_client, "list_user_tabular_file_links")
    # Живой путь остаётся
    assert hasattr(duckdb_client, "fetch_tabular_files_from_urls")


@pytest.mark.asyncio
async def test_presigned_links_are_used(monkeypatch):
    """Ссылки из тела /run — единственный источник файлов для инструмента."""
    seen = {}

    async def fake_fetch(files):
        seen["files"] = files
        return [{"name": "t1.csv", "content_b64": "eA=="}], []

    async def fake_query(self, *, sql, files, max_rows=200):
        return {"tables": [{"name": "t1", "columns": [{"name": "a", "type": "VARCHAR"}]}]}

    monkeypatch.setattr(
        "service.domain.tools.duckdb_client.DuckDBClient.enabled",
        property(lambda self: True),
    )
    monkeypatch.setattr(
        "service.domain.tools.duckdb_client.fetch_tabular_files_from_urls",
        fake_fetch,
    )
    monkeypatch.setattr("service.domain.tools.duckdb_client.DuckDBClient.query", fake_query)

    links = [{"name": "t1.csv", "url": "https://example.invalid/t1.csv"}]
    await function_tools.analyze_data_tool(_Ctx({"user_id": "7", "tabular_files": links}), "{}")

    assert seen["files"] == links
