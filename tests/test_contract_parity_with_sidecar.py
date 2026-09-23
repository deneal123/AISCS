"""Backend и сайдкар обязаны говорить на ОДНОМ контракте.

Общего пакета больше нет: провод описан у каждого своей копией. Значит расхождение —
не гипотеза, а штатный режим отказа, и ловить его должен страж, а не удача.

Чем это опасно именно здесь: тело `/run` и поток `AgentEvent` — денежный путь. Воркер
биллит и персистит из result-dict, поэтому поле, потерянное при рассинхроне контракта,
означает: пользователь платит не за то либо получает вызов бесплатно. Такой сбой не
падает громко, а тихо искажает цифры.

Поэтому сверяем ИМЕНА (не счётчики: «20 полей» совпадёт и при разных наборах).

⚠️ Тест интеграционный: без поднятого сайдкара он пропускается. То есть он ловит
расхождение там, где стек запущен (dev, e2e-прогон), и НЕ ловит в изолированном юнит-CI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from service.infrastructure.agents_client.contracts.events import EventType
from service.infrastructure.agents_client.contracts.run import AMBIENT_FIELDS, AgentRunInput

_SIDECAR = os.environ.get("AGENTS__SIDECAR_URL", "http://agents:8090").rstrip("/")


def _sidecar_contract() -> dict | None:
    try:
        with urllib.request.urlopen(f"{_SIDECAR}/health", timeout=5) as resp:
            body = json.load(resp) or {}
            # Фолбэк на старое имя `gpthub_core` снят вместе с самим ключом в
            # сайдкаре. Держать его было незачем: оба сервиса выкладываются из
            # ОДНОГО коммита суперпроекта, поэтому «сайдкары обеих версий в
            # обороте» — ситуация, которой в этой топологии не бывает.
            return body.get("contract")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


@pytest.fixture(scope="module")
def sidecar_contract() -> dict:
    contract = _sidecar_contract()
    if not isinstance(contract, dict):
        pytest.skip(f"сайдкар недоступен по {_SIDECAR} — сверять контракт не с чем")
    if not isinstance(contract.get("run_input_fields"), list):
        pytest.skip("сайдкар отдаёт контракт СЧЁТЧИКАМИ (старая версия) — сверка невозможна")
    return contract


def test_run_input_fields_match(sidecar_contract: dict) -> None:
    """Тело /run у сторон одинаковое: иначе поле молча не доедет до движка."""
    ours = sorted(AgentRunInput.model_fields)
    theirs = sorted(sidecar_contract["run_input_fields"])

    assert theirs == ours, (
        "контракт /run разъехался — только у backend: "
        f"{sorted(set(ours) - set(theirs))}; только у сайдкара: {sorted(set(theirs) - set(ours))}"
    )


def test_ambient_fields_match(sidecar_contract: dict) -> None:
    """Разъедется этот список — окружение прогона уедет В АРГУМЕНТЫ execute и уронит
    каждый прогон, либо наоборот потеряется и политика перестанет применяться."""
    assert sorted(sidecar_contract["ambient_fields"]) == sorted(AMBIENT_FIELDS)


# Поля result-dict, из которых воркер СПИСЫВАЕТ ДЕНЬГИ. Список намеренно повторён
# здесь как ожидание ПОТРЕБИТЕЛЯ: он сверяется с тем, что публикует провайдер. Читает
# их `_charge_usage`/`_charge_router_usage` через `.get(...) or 0`, поэтому пропажа
# имени не падает, а тихо даёт ноль — недобилл, который иначе никто не заметит.
_BILLING_RESULT_KEYS = frozenset(
    {
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "per_call_usage",
        "reply_chars_count",
        "metadata",
        "resolved_model",
        "reply",
    }
)


def test_result_fields_cover_what_worker_bills(sidecar_contract: dict) -> None:
    """Сайдкар обязан отдавать ВСЕ поля, по которым воркер считает деньги."""
    published = sidecar_contract.get("result_fields")
    if not isinstance(published, list):
        pytest.skip("сайдкар ещё не публикует result_fields (старая версия)")

    missing = sorted(_BILLING_RESULT_KEYS - set(published))
    assert not missing, (
        f"сайдкар перестал отдавать поля, по которым воркер биллит: {missing}. "
        "Воркер прочитает их как 0 — списание молча занизится."
    )


def test_route_response_carries_billed_usage(sidecar_contract: dict) -> None:
    """`routing_usage` тарифицируется ОТДЕЛЬНО: потеряется — вызов достанется бесплатно."""
    published = sidecar_contract.get("route_response_fields")
    if not isinstance(published, list):
        pytest.skip("сайдкар ещё не публикует route_response_fields (старая версия)")

    for key in ("selected_model", "routing_usage"):
        assert key in published, f"/route перестал отдавать {key}"


def test_event_types_match(sidecar_contract: dict) -> None:
    """Типы событий — то, что backend форвардит в WS. Лишний у сайдкара доедет
    неузнанным, недостающий — оборвёт ожидаемую фронтом последовательность."""
    ours = sorted(e.value for e in EventType)
    theirs = sorted(sidecar_contract["event_types"])

    assert theirs == ours, (
        f"типы событий разъехались — только у backend: {sorted(set(ours) - set(theirs))}; "
        f"только у сайдкара: {sorted(set(theirs) - set(ours))}"
    )
