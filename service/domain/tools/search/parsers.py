"""Парсеры поисковых выдач: html -> [(url, title, snippet)].

Отдельный модуль, потому что это самая волатильная часть поиска: разбор ЧУЖОЙ вёрстки,
которая меняется без предупреждения. Оркестрация (кого за кем звать, сколько ждать)
живёт в `web_search.py` и меняется по совсем другим поводам.

Каждый парсер ЧИСТЫЙ и вызываемый снаружи. Раньше все пятеро были замыканиями внутри
`web_search`: писали в общий список результатов и читали оттуда же лимит — позвать их
из теста было нельзя, и три из пяти не были покрыты вовсе.
"""

from __future__ import annotations

import logging
import re
from html import unescape

logger = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --------------------------------------------------------------------------- #
# Парсеры выдач                                                                 #
#                                                                               #
# Каждый парсер ЧИСТЫЙ: html -> [(url, title, snippet)]. Раньше все пятеро были #
# замыканиями внутри web_search: писали в общий список `results` и читали оттуда #
# же `num_results`. Из-за этого их нельзя было ни позвать снаружи, ни проверить  #
# отдельно — а именно они ломаются первыми, потому что зависят от чужой вёрстки. #
# Нормализация, дедупликация и лимит переехали в _collect: разбор HTML и учёт    #
# найденного — разные задачи, и смешаны они были только ради общего замыкания.   #
# --------------------------------------------------------------------------- #

# (сырой url, заголовок, сниппет)
_Hit = tuple[str, str, str]


def _parse_duckduckgo(html: str) -> list[_Hit]:
    """Канонические якоря DDG; если разметка сменилась — любые внешние ссылки."""
    anchors = list(
        re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.S | re.I,
        )
    )
    if not anchors:
        anchors = list(
            re.finditer(
                r'<a[^>]+href="(https?://[^"]+|[^"]*uddg=[^"]+)"[^>]*>(.*?)</a>',
                html,
                re.S | re.I,
            )
        )

    hits: list[_Hit] = []
    for match in anchors:
        # Сниппет DDG живёт не внутри якоря, а рядом с ним — отсюда «хвост».
        tail = html[match.end() : match.end() + 1200]
        snippet_match = re.search(
            r'<(?:a|div|span|p)[^>]+class="[^"]*(?:result__snippet|snippet)[^"]*"[^>]*>(.*?)</(?:a|div|span|p)>',
            tail,
            re.S | re.I,
        )
        hits.append(
            (
                (match.group(1) or "").strip(),
                _strip_html(match.group(2) or ""),
                _strip_html(snippet_match.group(1)) if snippet_match else "",
            )
        )
    return hits


def _parse_duckduckgo_lite(html: str) -> list[_Hit]:
    """Lite-версия отдаёт голый список ссылок без сниппетов."""
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I)
    return [((url or "").strip(), _strip_html(title), "") for url, title in links]


def _parse_bing(html: str) -> list[_Hit]:
    hits: list[_Hit] = []
    for block in re.findall(r'<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.S | re.I):
        link_match = re.search(
            r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I
        )
        if not link_match:
            continue
        snippet_match = re.search(
            r'<div[^>]+class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>',
            block,
            re.S | re.I,
        )
        hits.append(
            (
                (link_match.group(1) or "").strip(),
                _strip_html(link_match.group(2) or ""),
                _strip_html(snippet_match.group(1)) if snippet_match else "",
            )
        )
    return hits


def _parse_yandex(html: str) -> list[_Hit]:
    lowered = html.lower()
    if "верификац" in lowered or "captcha" in lowered:
        logger.info("Yandex returned verification page, skipping parser")
        return []

    # Yandex SERP often keeps links inside h2.organic__title-wrapper a or plain h2 > a.
    hits: list[_Hit] = []
    blocks = re.findall(
        r'<li[^>]+class="[^"]*(?:serp-item|organic)[^"]*"[^>]*>(.*?)</li>', html, re.S | re.I
    )
    for block in blocks:
        link_match = re.search(
            r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I
        )
        if not link_match:
            link_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        if not link_match:
            continue
        snippet_match = re.search(
            r'<div[^>]+class="[^"]*(?:organic__text|text-container|ExtendedText)[^"]*"[^>]*>(.*?)</div>',
            block,
            re.S | re.I,
        )
        hits.append(
            (
                (link_match.group(1) or "").strip(),
                _strip_html(link_match.group(2) or ""),
                _strip_html(snippet_match.group(1)) if snippet_match else "",
            )
        )
    return hits


def _parse_brave(html: str) -> list[_Hit]:
    """Brave размечает результаты не блоками, а маркерами ``data-type="web"``."""
    positions = [m.start() for m in re.finditer(r'data-type="web"', html, re.I)]
    hits: list[_Hit] = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else min(len(html), pos + 8000)
        block = html[pos:end]

        link_match = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>', block, re.S | re.I)
        if not link_match:
            continue

        title_match = re.search(
            r'<div[^>]+class="[^"]*(?:search-snippet-title|title)[^"]*"[^>]*>(.*?)</div>',
            block,
            re.S | re.I,
        )
        if title_match:
            title = _strip_html(title_match.group(1) or "")
        else:
            anchor_text_match = re.search(
                r'<a[^>]+href="https?://[^"]+"[^>]*>(.*?)</a>', block, re.S | re.I
            )
            title = _strip_html(anchor_text_match.group(1) if anchor_text_match else "")

        snippet_match = re.search(
            r'<div[^>]+class="[^"]*generic-snippet[^"]*"[^>]*>.*?<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            block,
            re.S | re.I,
        )
        hits.append(
            (
                (link_match.group(1) or "").strip(),
                title,
                _strip_html(snippet_match.group(1)) if snippet_match else "",
            )
        )
    return hits


def _parse_external_anchors(html: str) -> list[_Hit]:
    """Последняя надежда: любые внешние ссылки с осмысленным текстом.

    Короткие подписи («сюда», «ещё») отсекаются — это навигация, а не результаты.
    """
    hits: list[_Hit] = []
    for href, text in re.findall(
        r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I
    ):
        title = _strip_html(text or "")
        if len(title) < 12:
            continue
        hits.append(((href or "").strip(), title, ""))
    return hits
