"""Парсеры поисковых выдач — по отдельности.

⚠️ Раньше проверить их было НЕЧЕМ: все пятеро жили замыканиями внутри ``web_search``,
писали в общий список и читали оттуда же лимит. Единственный способ дотянуться до
парсера — поднять весь поиск с подменённым httpx и надеяться, что до нужного движка
дойдёт очередь. Поэтому три из пяти не были покрыты вовсе — при том что ломаются они
первыми: это разбор ЧУЖОЙ вёрстки, которая меняется без предупреждения.

Здесь каждый парсер вызывается напрямую. Формат общий: html -> [(url, title, snippet)].
"""

from __future__ import annotations

import pytest

from service.domain.tools.web_search import (
    _collect,
    _parse_bing,
    _parse_brave,
    _parse_duckduckgo,
    _parse_duckduckgo_lite,
    _parse_external_anchors,
    _parse_yandex,
)


def test_duckduckgo_reads_canonical_anchors_with_nearby_snippet():
    html = """
    <a class="result__a" href="https://example.com/a">Заголовок</a>
    <div class="result__snippet">Пояснение к результату</div>
    """
    assert _parse_duckduckgo(html) == [
        ("https://example.com/a", "Заголовок", "Пояснение к результату")
    ]


def test_duckduckgo_falls_back_to_plain_anchors_when_markup_changed():
    """⚠️ Ради этого запасного пути движок и живой: DDG периодически меняет классы."""
    html = '<a href="https://example.com/b">Просто ссылка</a>'
    assert _parse_duckduckgo(html) == [("https://example.com/b", "Просто ссылка", "")]


def test_duckduckgo_lite_returns_links_without_snippets():
    html = '<a href="https://example.com/c">Заголовок C</a>'
    assert _parse_duckduckgo_lite(html) == [("https://example.com/c", "Заголовок C", "")]


def test_bing_reads_block_title_and_caption():
    html = """
    <li class="b_algo">
      <h2><a href="https://example.org/x">Новость</a></h2>
      <div class="b_caption"><p>Краткое содержание.</p></div>
    </li>
    """
    assert _parse_bing(html) == [("https://example.org/x", "Новость", "Краткое содержание.")]


def test_yandex_skips_captcha_page():
    """Страница верификации — не выдача: разобрав её, мы вернули бы мусор как результат."""
    assert _parse_yandex("<html><body>Подтвердите, что вы не робот: captcha</body></html>") == []


def test_yandex_reads_organic_block():
    html = """
    <li class="serp-item">
      <h2><a href="https://example.net/y">Материал</a></h2>
      <div class="organic__text">Подробности по теме.</div>
    </li>
    """
    assert _parse_yandex(html) == [("https://example.net/y", "Материал", "Подробности по теме.")]


def test_brave_splits_results_by_data_type_markers():
    """У Brave нет блоков-контейнеров — результаты нарезаются по маркерам."""
    html = """
    <div data-type="web">
      <a href="https://example.dev/one"><div class="search-snippet-title">Первый</div></a>
      <div class="generic-snippet"><div class="content">Описание первого.</div></div>
    </div>
    <div data-type="web">
      <a href="https://example.dev/two"><div class="search-snippet-title">Второй</div></a>
    </div>
    """
    hits = _parse_brave(html)

    assert [h[0] for h in hits] == ["https://example.dev/one", "https://example.dev/two"]
    assert hits[0][2] == "Описание первого."


def test_external_anchors_ignore_navigation_labels():
    """Короткие подписи — это навигация («сюда», «ещё»), а не результаты поиска."""
    html = """
    <a href="https://example.com/real">Содержательный заголовок статьи</a>
    <a href="https://example.com/nav">сюда</a>
    """
    assert _parse_external_anchors(html) == [
        ("https://example.com/real", "Содержательный заголовок статьи", "")
    ]


# --------------------------------------------------------------------------- #
# Накопитель: нормализация, внешность, дедуп, потолок                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("hits", "expected", "why"),
    [
        (
            [("https://example.com/a", "A", ""), ("https://example.com/a", "A снова", "")],
            ["https://example.com/a"],
            "один и тот же url двумя движками — это один результат",
        ),
        (
            [("https://duckduckgo.com/?q=x", "внутренняя", ""), ("https://example.com/b", "B", "")],
            ["https://example.com/b"],
            "ссылки самого поисковика — не результаты",
        ),
    ],
)
def test_collect_filters(hits, expected, why):
    results: list[dict] = []
    _collect(results, hits, limit=10)
    assert [r["url"] for r in results] == expected, why


def test_collect_respects_the_limit():
    results: list[dict] = []
    _collect(results, [(f"https://example.com/{i}", f"T{i}", "") for i in range(10)], limit=3)
    assert len(results) == 3


def test_collect_keeps_filling_across_calls():
    """⚠️ Потолок общий на все движки, а не на каждый: иначе фолбэк добавлял бы сверх лимита."""
    results: list[dict] = []
    _collect(results, [("https://example.com/1", "A", "")], limit=2)
    _collect(results, [("https://example.com/2", "B", ""), ("https://example.com/3", "C", "")], 2)
    assert len(results) == 2
