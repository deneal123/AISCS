"""ВЫХОД сайдкара — тоже контракт, и именно по нему backend списывает деньги.

Тест паритета исторически сверял только ВХОД (`run_input_fields`). Между тем воркер
биллит из result-dict `/run` (`total_tokens`, `per_call_usage`, `prompt_tokens`,
`completion_tokens`) и отдельно тарифицирует роутер по `routing_usage` из `/route`.
Читает он их через ``.get(...) or 0`` — то есть переименование поля здесь НЕ падает,
а тихо даёт ноль. Недобилл без единой ошибки в логах.

Константы `RESULT_FIELDS` / `ROUTE_RESPONSE_FIELDS` живут в лёгком
`service.contracts` (без движка и SDK — чтобы сверку в CI можно было держать
дешёвой) и публикуются в `/health`. Здесь проверяется единственное, что делает их
не бумажкой: что они совпадают с тем, что код РЕАЛЬНО возвращает.
"""

import pytest
from fastapi.testclient import TestClient

from service import main as sidecar
from service.application.use_cases.agent_execution_use_cases import (
    PersistSessionHistoryUseCase,
)
from service.contracts import RESULT_FIELDS, ROUTE_RESPONSE_FIELDS


@pytest.fixture()
def client(monkeypatch):
    """Клиент с внутренним ключом: `/route` закрыт (см. test_internal_auth.py)."""
    from service.settings import config

    key = "test-internal-key"
    monkeypatch.setattr(config.agents, "llm_gateway_api_key", key, raising=False)
    return TestClient(sidecar.app, headers={"Authorization": f"Bearer {key}"})


class _Assembler:
    """Минимальный ReplyAssembler: use-case читает у него только эти поля."""

    reply_parts = ["привет"]
    prompt_tokens = 12
    completion_tokens = 3
    total_tokens = 15
    per_call_usage = [{"model": "m", "prompt": 12, "completion": 3}]


def test_result_fields_match_what_is_actually_returned():
    """Константа обязана совпадать с фактическим result-dict, иначе она бесполезна."""
    produced = PersistSessionHistoryUseCase().execute(
        reply="привет",
        metadata={},
        resolved_model="openai/gpt-4o-mini",
        reply_assembler=_Assembler(),
    )

    assert set(produced) == set(RESULT_FIELDS), (
        "result-dict разъехался с RESULT_FIELDS — только в коде: "
        f"{sorted(set(produced) - set(RESULT_FIELDS))}; "
        f"только в константе: {sorted(set(RESULT_FIELDS) - set(produced))}"
    )


def test_billing_critical_keys_are_present():
    """Явный список денежных полей: их backend читает как `.get(...) or 0`."""
    for key in (
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "per_call_usage",
        "reply_chars_count",
    ):
        assert key in RESULT_FIELDS, f"пропало денежное поле {key}"


def test_contracts_module_stays_autonomous():
    """Провод (`service.contracts`) обязан грузиться БЕЗ пакета `service` на пути.

    Офлайн-парити-гейт (scripts/check_contract_parity.py, ci.yml) грузит этот модуль ПО
    ПУТИ, без sys.path-пакета `service`, чтобы сверить контракт backend↔сайдкар без сети.
    Любой eager `X = <что-то из service.settings>` на импорте роняет гейт
    `ModuleNotFoundError: service` — и сверка контракта МОЛЧА выключается (так было 21
    коммит после 9f784bb8). MAX_BODY_BYTES поэтому ленивый (PEP 562 __getattr__), а не
    eager-атрибут модуля. Страж ловит регресс ЛОКАЛЬНО, не дожидаясь красного CI.
    """
    import service.contracts as c

    assert "MAX_BODY_BYTES" not in c.__dict__, (
        "MAX_BODY_BYTES стал eager-атрибутом — он тянет service.settings на импорте и роняет "
        "офлайн-парити-гейт. Верни ленивый доступ через __getattr__."
    )
    assert hasattr(c, "__getattr__"), "провод потерял ленивый __getattr__"
    assert c.MAX_BODY_BYTES > 0  # но доступ к значению работает (реальный сервис его читает)


def test_route_response_fields_match_endpoint(client, monkeypatch):
    """То же для `/route`: сверяем константу с реальным телом ответа."""

    async def fake_route_model(*, text, selected_model, input_type, usage_out=None, **_):
        if usage_out is not None:
            usage_out.update({"prompt": 1, "completion": 1, "total": 2})
        return "openai/gpt-4o-mini", {"tool": "none"}

    import service.domain.tools.router as router_mod

    monkeypatch.setattr(router_mod, "route_model", fake_route_model)

    body = client.post(
        "/route",
        json={
            "text": "привет",
            "selected_model": None,
            "input_type": "text",
            "web_search": False,
            "deep_research": False,
            "route_override": None,
        },
    ).json()

    assert set(body) == set(ROUTE_RESPONSE_FIELDS)


def test_health_publishes_output_contract(client):
    """Без публикации в /health backend не с чем сверяться."""
    contract = client.get("/health").json()["contract"]

    assert set(contract["result_fields"]) == set(RESULT_FIELDS)
    assert set(contract["route_response_fields"]) == set(ROUTE_RESPONSE_FIELDS)
