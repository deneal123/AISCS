"""Ссылки прошлого хода доезжают до промпта следующего.

История уходит в модель как `[{role, content}]` — поле рядом с `content` до неё не
доедет по построению, поэтому источники ДОПИСЫВАЮТСЯ в текст реплики.
"""

from __future__ import annotations

import json

from service.services.chat.persistence.chat_worker_repository import (
    _HISTORY_SOURCES_LIMIT,
    _sources_note,
)


def test_urls_reach_the_note() -> None:
    """🔴 Без адреса следующий ход не может дочитать источник через `fetch_url`."""
    note = _sources_note({"sources": [{"url": "https://hh.test/vacancy/1", "title": "Вакансия"}]})

    assert "https://hh.test/vacancy/1" in note


def test_note_survives_json_stored_as_text() -> None:
    """Драйвер отдаёт `jsonb` то словарём, то строкой — разбирать обязаны оба вида."""
    note = _sources_note(json.dumps({"sources": [{"url": "https://a.test/x"}]}))

    assert "https://a.test/x" in note


def test_message_without_sources_gets_nothing() -> None:
    """Приписка без повода — шум в КАЖДОМ ходу и надбавка к цене каждого промпта."""
    assert _sources_note({}) == ""
    assert _sources_note(None) == ""
    assert _sources_note({"sources": []}) == ""
    assert _sources_note("не json") == ""


def test_note_is_capped() -> None:
    """⚠️ История едет в промпт КАЖДЫЙ ход: потолок здесь — про постоянную цену."""
    note = _sources_note(
        {"sources": [{"url": f"https://a.test/{i}"} for i in range(_HISTORY_SOURCES_LIMIT + 6)]}
    )

    assert note.count("https://") == _HISTORY_SOURCES_LIMIT
