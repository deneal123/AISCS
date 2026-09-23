"""Отказ файлового инструмента даёт следующий шаг, а не повод сдаться.

🔴 ЗАМЕРЕНО НА ЖИВОЙ ПЕСОЧНИЦЕ (архив `requests` развёрнут, инструменты выданы). Два разных
промаха давали один и тот же ответ-капитуляцию:

    ws_read «нет-такого.py» → «Не удалось обратиться к файлам: файла нет.
                               Скажи об этом пользователю прямо…»
    ws_read «requests»      → то же самое, хотя это КАТАЛОГ и он полон нужных файлов

Путь модель берёт из карты репозитория, где путей нет вовсе, — значит промах на один
каталог это норма, а не сбой. Прежняя формулировка велела в обоих случаях идти к человеку с
«файл недоступен», при том что дерево стоило одного вызова.

⚠️ Запрет выдумывать содержимое ОСТАЁТСЯ везде: он про другое. Ошибка была не в запрете, а в
том, что кроме запрета модели не давали ничего.
"""

from __future__ import annotations

import json

import pytest

from service.domain.integration_failure import IntegrationFailureCode
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.tools import workspace_tools as wt
from service.domain.tools.workspace_client import WorkspaceUnavailable

REF = {"workspace_id": "ws1", "token": "t.sig", "user_id": "7", "root": "/workspace"}


class _Ctx:
    def __init__(self, ref=REF) -> None:
        self.context = {"workspace_ref": ref}


@pytest.fixture
def calls(monkeypatch):
    """Подменяет клиента: сеть не трогаем, ответы задаём по ручке."""
    replies: dict[str, object] = {}

    async def fake_call(ref, path, payload):
        assert isinstance(ref, dict) and ref.get("token"), "в клиент уехала не ссылка на песочницу"
        if isinstance(replies.get(path), Exception):
            raise replies[path]
        return replies.get(path, {"ok": True})

    monkeypatch.setattr(wt, "call", fake_call)
    return replies


def _flat(value: str | ToolCallOutcome) -> str:
    text = value.text if isinstance(value, ToolCallOutcome) else value
    return " ".join(str(text).lower().split())


# --- промах путём поправим --------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_missing_file_points_at_the_tree(calls):
    """An invalid read gets a bounded repair instruction without echoing its path."""
    marker = "S24_PRIVATE_PATH"
    calls["files/read"] = WorkspaceUnavailable(IntegrationFailureCode.INVALID)

    outcome = await wt.ws_read_tool(_Ctx(), f'{{"path": "{marker}"}}')
    answer = _flat(outcome)

    assert isinstance(outcome, ToolCallOutcome)
    assert outcome.failure_code == "invalid_arguments"
    assert "исправь аргументы" in answer
    assert marker.lower() not in answer


@pytest.mark.asyncio
async def test_a_directory_is_also_recoverable(calls):
    """⚠️ Второй замеренный случай: путь есть, но это каталог. Тоже промах, тоже поправим."""
    calls["files/read"] = WorkspaceUnavailable(IntegrationFailureCode.INVALID)

    answer = _flat(await wt.ws_read_tool(_Ctx(), '{"path": "requests"}'))

    assert "исправь аргументы" in answer


@pytest.mark.asyncio
async def test_the_model_is_told_not_to_declare_failure_early(calls):
    """🔴 Ровно это и происходило: модель шла к человеку с «файл недоступен», не поискав."""
    calls["files/read"] = WorkspaceUnavailable(IntegrationFailureCode.INVALID)

    answer = _flat(await wt.ws_read_tool(_Ctx(), '{"path": "x.py"}'))

    assert "исправь аргументы" in answer


@pytest.mark.asyncio
async def test_a_bad_pattern_is_the_models_own_fix(calls):
    """⚠️ Негодная регулярка — ошибка МОДЕЛИ, и починить её может только она. Отправлять
    человека разбираться с чужим `[unclosed` бессмысленно, а именно это и предлагалось."""
    calls["files/grep"] = WorkspaceUnavailable(IntegrationFailureCode.INVALID)

    answer = _flat(await wt.ws_grep_tool(_Ctx(), '{"pattern": "[unclosed"}'))

    assert "исправь аргументы" in answer
    assert "[unclosed" not in answer


@pytest.mark.asyncio
async def test_a_real_outage_stays_a_plain_refusal(calls):
    """🔴 ГРАНИЦА. Лежащий сайдкар НЕ поправим сменой пути: советовать `ws_list` здесь
    значило бы гонять модель по кругу до конца раундов."""
    calls["exec"] = WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE, retryable=True)

    answer = _flat(await wt.ws_run_tool(_Ctx(), '{"command": "ls"}'))

    assert "временно недоступна" in answer
    assert "исправь аргументы" not in answer


@pytest.mark.asyncio
async def test_a_denied_path_stays_a_plain_refusal(calls):
    """🔴 ГРАНИЦА. Путь за пределами песочницы — запрет, а не опечатка: предлагать поискать
    «верный путь» значило бы намекать, что где-то он есть."""
    calls["files/list"] = WorkspaceUnavailable(IntegrationFailureCode.POLICY)

    answer = _flat(await wt.ws_list_tool(_Ctx(), '{"path": "/etc"}'))

    assert "запрещена политикой" in answer
    assert "/etc" not in answer


# --- пустой поиск ------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_empty_search_answers_in_words(calls):
    """🔴 `{"matches": []}` модель читает как «этого в коде нет» и говорит это человеку.
    Причин три, и две поправимы своими силами: узкий шаблон и не тот каталог."""
    calls["files/grep"] = {"matches": [], "truncated": False}

    answer = _flat(await wt.ws_grep_tool(_Ctx(), '{"pattern": "timeout_handler"}'))

    assert "совпадений не найдено" in answer
    assert "не доказательство" in answer, "пустой поиск выдан за доказательство отсутствия"
    assert "шаблон" in answer, "не подсказано, что шаблон можно изменить"


@pytest.mark.asyncio
async def test_the_empty_search_names_the_pattern(calls):
    """⚠️ Шаблон в ответе — чтобы модель увидела СВОЮ опечатку, а не искала её на ощупь."""
    calls["files/grep"] = {"matches": []}

    answer = await wt.ws_grep_tool(_Ctx(), '{"pattern": "Sesion.request"}')

    assert "Sesion.request" in answer


@pytest.mark.asyncio
async def test_a_successful_search_returns_the_matches_untouched(calls):
    """🔴 ГРАНИЦА. Нашлось — отдаём данные, без подсказок: они бы только съели контекст."""
    calls["files/grep"] = {"matches": ["/workspace/a.py:1:def request("], "truncated": False}

    answer = await wt.ws_grep_tool(_Ctx(), '{"pattern": "def request"}')

    assert "def request(" in answer
    assert "не доказательство" not in answer
    assert json.loads(answer)["matches"], "ответ перестал быть разбираемым JSON"
