"""Гибридный поиск по документам: эмбеддинги ⊕ граф.

Почему гибрид, а не что-то одно: graphify прямо говорит о себе, что он НЕ векторный
индекс. Он силён на реляционных вопросах («как X связан с Y»), потому что обходит рёбра,
но узел графа — это сущность, а не абзац, и дословного текста в нём нет. Эмбеддинги —
наоборот. Проверено вживую: на вопрос «какой срок оплаты и штраф» векторы вернули точные
строки договора, а граф — только сущности вокруг него.
"""

from types import SimpleNamespace

import pytest

from service.domain.tools import vector_store


# --------------------------------------------------------------------------- #
# Нарезка на чанки                                                             #
# --------------------------------------------------------------------------- #
def test_short_document_is_a_single_chunk():
    assert vector_store.chunk_text("Короткий документ.") == ["Короткий документ."]


def test_empty_document_yields_nothing():
    assert vector_store.chunk_text("") == []
    assert vector_store.chunk_text("   \n  ") == []


def test_long_document_is_split_with_overlap():
    """Перекрытие обязательно: без него факт на стыке чанков не найдётся ни в одном
    из них целиком."""
    body = "\n".join(f"Строка номер {i} с содержательным текстом." for i in range(400))
    chunks = vector_store.chunk_text(body)

    assert len(chunks) > 1
    # Соседние чанки должны пересекаться — иначе перекрытия нет.
    tail = chunks[0][-60:]
    assert any(part in chunks[1] for part in tail.split("\n") if part.strip())


def test_chunks_cover_the_whole_document():
    """Ни один кусок текста не должен потеряться между чанками."""
    body = "\n".join(f"Уникальный маркер {i}." for i in range(300))
    joined = " ".join(vector_store.chunk_text(body))
    for marker in (0, 150, 299):
        assert f"Уникальный маркер {marker}." in joined


def test_chunks_respect_embedder_token_limit():
    """Регрессия: чанк не должен превышать лимит входа эмбеддера (GigaChat 514) —
    иначе 413 «Tokens limit exceeded» и индексация документа падает целиком."""
    from service.settings import config
    from service.shared.token_budget import estimate_tokens

    embed_max = int(config.agents.doc_embedder_max_tokens or 480)
    # Длинный ПЛОТНЫЙ кириллический текст (без частых переносов — стресс на длину чанка).
    body = "Автоматизация процессов требует тщательного анализа рисков и данных. " * 400
    chunks = vector_store.chunk_text(body)
    assert len(chunks) > 1
    for ch in chunks:
        # С запасом на неточность оценки: не должен вылезать за лимит эмбеддера.
        assert estimate_tokens(ch) <= embed_max + 5, f"чанк {estimate_tokens(ch)} ток > {embed_max}"


# --------------------------------------------------------------------------- #
# Изоляция пользователей                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_search_filters_by_user(monkeypatch):
    """Коллекция одна на всех — без фильтра нашлись бы ЧУЖИЕ документы."""
    sent: dict = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"result": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _url):
            # Коллекция существует и её dim совпадает (8) → search не пересоздаёт её.
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"result": {"config": {"params": {"vectors": {"size": 8}}}}},
            )

        async def post(self, _url, json=None, **_kw):
            sent.update(json or {})
            return _Resp()

    async def _fake_embed(_texts):
        return [[0.0] * 8], 8, True  # (vectors, dim, is_primary)

    monkeypatch.setattr(vector_store, "_embed_with_dim", _fake_embed)
    monkeypatch.setattr(vector_store.httpx, "AsyncClient", lambda **_kw: _Client())
    monkeypatch.setattr(vector_store, "enabled", lambda: True)

    await vector_store.search(user_id="u1", query="вопрос")

    conditions = sent["filter"]["must"]
    assert conditions == [{"key": "user_id", "match": {"value": "u1"}}]


@pytest.mark.asyncio
async def test_search_is_fail_open(monkeypatch):
    """Qdrant лёг — поиск возвращает пусто, а не роняет ход диалога."""

    async def _boom(_texts):
        raise RuntimeError("qdrant недоступен")

    monkeypatch.setattr(vector_store, "_embed_with_dim", _boom)
    monkeypatch.setattr(vector_store, "enabled", lambda: True)

    assert await vector_store.search(user_id="u1", query="вопрос") == []


@pytest.mark.asyncio
async def test_disabled_vector_search_does_nothing(monkeypatch):
    monkeypatch.setattr(vector_store, "enabled", lambda: False)
    assert await vector_store.search(user_id="u1", query="x") == []
    assert await vector_store.index_document(user_id="u1", filename="a.md", text="текст") == 0


# --------------------------------------------------------------------------- #
# Инструмент: два источника, помеченные по отдельности                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_merges_passages_and_relations(monkeypatch):
    """Модель должна видеть, ЧТО дословно написано и КАК это связано — раздельно."""
    import service.domain.tools.function_tools as ft
    from service.domain.tools import graphify_client as gc

    async def _passages(**_kw):
        return [{"filename": "dogovor.md", "text": "Срок оплаты: 45 дней.", "score": 0.83}]

    class _Graph:
        async def query(self, *_a, **_kw):
            return "NODE Договор --references--> Покупатель"

    monkeypatch.setattr(vector_store, "search", _passages)
    monkeypatch.setattr(gc, "GraphifyClient", _Graph)

    out = await ft.search_knowledge_graph_tool(
        SimpleNamespace(context={"user_id": "u1"}), '{"question": "срок оплаты"}'
    )

    assert "## Фрагменты документов (дословно)" in out
    assert "Срок оплаты: 45 дней." in out
    assert "## Связи из графа знаний" in out
    assert "--references-->" in out


@pytest.mark.asyncio
async def test_tool_survives_one_source_dying(monkeypatch):
    """Векторы упали — связи из графа всё равно доходят до модели (и наоборот)."""
    import service.domain.tools.function_tools as ft
    from service.domain.tools import graphify_client as gc

    async def _no_passages(**_kw):
        return []

    class _Graph:
        async def query(self, *_a, **_kw):
            return "NODE Foo --uses--> Bar"

    monkeypatch.setattr(vector_store, "search", _no_passages)
    monkeypatch.setattr(gc, "GraphifyClient", _Graph)

    out = await ft.search_knowledge_graph_tool(
        SimpleNamespace(context={"user_id": "u1"}), '{"question": "что угодно"}'
    )

    assert "Фрагменты документов" not in out
    assert "Foo --uses--> Bar" in out


@pytest.mark.asyncio
async def test_tool_reports_empty_knowledge_base(monkeypatch):
    """Пусто — говорим прямо, чтобы модель не выдумывала связи."""
    import service.domain.tools.function_tools as ft
    from service.domain.tools import graphify_client as gc

    async def _nothing(**_kw):
        return []

    class _Graph:
        async def query(self, *_a, **_kw):
            return ""

    monkeypatch.setattr(vector_store, "search", _nothing)
    monkeypatch.setattr(gc, "GraphifyClient", _Graph)

    out = await ft.search_knowledge_graph_tool(
        SimpleNamespace(context={"user_id": "u1"}), '{"question": "x"}'
    )
    assert "ничего не найдено" in out
