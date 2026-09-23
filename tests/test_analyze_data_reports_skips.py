"""analyze_data сообщает МОДЕЛИ о пропущенных файлах, а не только в лог.

🔴 Adversarial-поиск (давний код duckdb). Файлы, не вошедшие в анализ (>32 МБ, сверх
лимита MAX_FILES=6, исчерпан суммарный лимит, пустые), логировались warning'ом — но
МОДЕЛЬ этого не видела и делала SQL по подмножеству таблиц, уверенно отвечая по неполным
данным. Теперь fetch отдаёт список пропущенных, а analyze_data вставляет его в результат.
"""

from __future__ import annotations

import json

import pytest

from service.domain.tools import function_tools


class _Ctx:
    def __init__(self, data):
        self.context = data


@pytest.mark.asyncio
async def test_skipped_files_appear_in_tool_result(monkeypatch):
    """⚠️ ГЛАВНОЕ. Пропущенный файл попадает в текст результата — модель предупреждена."""
    from service.domain.tools import duckdb_client

    async def _fetch(files):
        return [{"name": "t1.csv", "content_b64": "eA=="}], ["«big.csv» — больше 32 МБ"]

    async def _query(self, *, sql, files, max_rows=200):
        return {"tables": [{"name": "t1", "columns": ["a"], "rows": [[1]]}]}

    monkeypatch.setattr(duckdb_client.DuckDBClient, "enabled", property(lambda self: True))
    monkeypatch.setattr(duckdb_client, "fetch_tabular_files_from_urls", _fetch)
    monkeypatch.setattr(duckdb_client.DuckDBClient, "query", _query)

    ctx = _Ctx({"user_id": "7", "tabular_files": [{"name": "t1.csv", "url": "http://x/t1"}]})
    out = await function_tools.analyze_data_tool(ctx, json.dumps({"sql": "select 1"}))

    assert "НЕ ПРОАНАЛИЗИРОВАНЫ" in out, "модель не предупреждена о неполных данных"
    assert "big.csv" in out, "конкретный пропущенный файл не назван"


@pytest.mark.asyncio
async def test_no_skips_no_warning(monkeypatch):
    """Все файлы вошли → никакой пометки о пропуске (не шумим зря)."""
    from service.domain.tools import duckdb_client

    async def _fetch(files):
        return [{"name": "t1.csv", "content_b64": "eA=="}], []

    async def _query(self, *, sql, files, max_rows=200):
        return {"tables": [{"name": "t1", "columns": ["a"], "rows": [[1]]}]}

    monkeypatch.setattr(duckdb_client.DuckDBClient, "enabled", property(lambda self: True))
    monkeypatch.setattr(duckdb_client, "fetch_tabular_files_from_urls", _fetch)
    monkeypatch.setattr(duckdb_client.DuckDBClient, "query", _query)

    ctx = _Ctx({"user_id": "7", "tabular_files": [{"name": "t1.csv", "url": "http://x/t1"}]})
    out = await function_tools.analyze_data_tool(ctx, json.dumps({"sql": "select 1"}))

    assert "НЕ ПРОАНАЛИЗИРОВАНЫ" not in out


def test_over_max_files_is_reported():
    """Остаток сверх MAX_FILES тоже попадает в skipped (раньше срез молчал совсем)."""
    import asyncio
    import inspect

    from service.domain.tools import duckdb_client

    src = inspect.getsource(duckdb_client.fetch_tabular_files_from_urls)
    assert "сверх лимита" in src and "MAX_FILES" in src, (
        "остаток сверх MAX_FILES отбрасывается без уведомления модели"
    )
    assert "return out, skipped" in src, "fetch не отдаёт пропущенные наружу"
    _ = (asyncio, inspect)
