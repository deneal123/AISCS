"""Контракт HTTP-слоя сайдкара: /health, /catalog и — главное — /run.

`/run` понесёт боевой трафик после переключения ``AGENTS__ENGINE_MODE=http``, а его
логика нетривиальна: движок отдаёт события СИНХРОННЫМ колбэком, и они мостятся в
NDJSON-поток через очередь. Фиксируем ровно то, на что опирается backend
(``HttpAgentEngine``) и, дальше по цепочке, воркер с биллингом:

* события уходят построчно и В ПОРЯДКЕ появления (иначе стрим в UI поедет);
* терминальная строка ``__result__`` — result-dict, ИЗ НЕГО СПИСЫВАЮТСЯ ДЕНЬГИ;
* падение движка отдаётся строкой ``__error__``, а не немым обрывом (иначе воркер
  счёл бы прогон удачным);
* нет движка → 503 с причиной, а /health при этом остаётся живым для диагностики.

Запуск (pytest в образ намеренно не кладём — он не нужен в проде):
    docker exec gpthub-dev-agents-1 pip install -q pytest pytest-asyncio
    docker exec gpthub-dev-agents-1 python -m pytest /opt/agents-sidecar/tests -q
"""

import json

import pytest
from fastapi.testclient import TestClient

from service import main as sidecar
from service.presentation import runtime


@pytest.fixture()
def client(monkeypatch):
    """Клиент, УЖЕ несущий внутренний ключ.

    ⚠️ `/run` и `/route` закрыты (см. `test_internal_auth.py`): без заголовка каждый
    тест здесь получил бы 401 и проверял бы авторизацию вместо своего предмета.
    Ключ подставляется по умолчанию, чтобы эти тесты остались про ПОВЕДЕНИЕ ручки, а
    сама авторизация проверялась там, где она предмет.
    """
    from service.settings import config

    key = "test-internal-key"
    monkeypatch.setattr(config.agents, "llm_gateway_api_key", key, raising=False)
    return TestClient(sidecar.app, headers={"Authorization": f"Bearer {key}"})


def _lines(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def _payload(**over):
    body = {"text": "привет", "thread_id": "t1", "user_id": "7"}
    body.update(over)
    return body


class _FakeEngine:
    """Движок-дублёр: зовёт on_event синхронно (как настоящий) и возвращает result."""

    def __init__(self, events=(), result=None, boom: str | None = None):
        self._events = events
        self._result = result or {"reply": "ok", "prompt_tokens": 1}
        self._boom = boom

    async def execute(self, *, on_event=None, **kwargs):
        for ev in self._events:
            if on_event:
                on_event(ev)
        if self._boom:
            raise RuntimeError(self._boom)
        return self._result


class _Ev:
    """Событие с полями, которые читает EventSerializer."""

    def __init__(self, type_: str, data: str = "", agent_name: str = "general"):
        self.type = type_
        self.data = data
        self.agent_name = agent_name
        self.metadata: dict = {}
        self.seq = 0


def test_health_reports_engine_and_gateway(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["service"] == "agents"
    capabilities = body["capabilities"]
    assert capabilities["status"] == "ok"
    assert capabilities["capability_version"].startswith("s29.")
    assert len(capabilities["capability_digest"]) == 64
    assert capabilities["agent_count"] > 0
    assert capabilities["workflow_count"] > 0
    assert capabilities["native_tool_count"] > 0
    assert set(capabilities) == {
        "status",
        "capability_version",
        "capability_digest",
        "agent_count",
        "workflow_count",
        "native_tool_count",
    }
    # Контракт отдаётся ИМЕНАМИ: по ним backend сверяет, что говорит с сайдкаром на
    # одном языке. Счётчики тут не годятся — «20 полей» совпадёт и при разных наборах.
    core = body["contract"]
    assert "text" in core["run_input_fields"] and "thread_id" in core["run_input_fields"]
    assert "provider_policy" in core["ambient_fields"]
    assert core["event_types"] == sorted(core["event_types"]) and core["event_types"]
    # Готовность движка/шлюза отражается явно (по ней диагностируют контейнер).
    assert set(body["engine"]) == {"available", "error"}
    assert set(body["gateway_v1"]) == {"available", "error"}


def test_run_streams_events_in_order_then_result(client, monkeypatch):
    events = [_Ev("routing_complete", "Выбран агент: general"), _Ev("stream_chunk", "прив")]
    monkeypatch.setattr(
        runtime, "DefaultAgentExecutionService", lambda: _FakeEngine(events, {"reply": "прив"})
    )
    lines = _lines(client.post("/run", json=_payload()))

    assert [line["type"] for line in lines[:-1]] == ["routing_complete", "stream_chunk"]
    assert [line["data"] for line in lines[:-1]] == ["Выбран агент: general", "прив"]
    # job_id проставлен (воркер публикует события под ним) — берём из thread_id.
    assert all(line["job_id"] == "t1" for line in lines[:-1])
    # Терминальная строка — result-dict: из него воркер биллит и персистит.
    assert lines[-1] == {"__result__": {"reply": "прив"}}
    assert sum("__result__" in line or "__error__" in line for line in lines) == 1


def test_run_reports_engine_failure_as_error_line(client, monkeypatch):
    """Падение движка обязано доехать строкой __error__, а не оборвать поток молча."""
    monkeypatch.setattr(
        runtime, "DefaultAgentExecutionService", lambda: _FakeEngine(boom="engine exploded")
    )
    lines = _lines(client.post("/run", json=_payload()))
    assert lines[-1] == {"__error__": "internal"}
    assert "engine exploded" not in json.dumps(lines, ensure_ascii=False)
    assert not any("__result__" in line for line in lines)
    assert sum("__result__" in line or "__error__" in line for line in lines) == 1


def test_run_503_when_engine_unavailable(client, monkeypatch):
    """Домен не подан → честный 503 с причиной; /health при этом продолжает отвечать."""
    monkeypatch.setattr(runtime, "DefaultAgentExecutionService", None)
    monkeypatch.setattr(runtime, "ENGINE_ERROR", "ImportError: no domain")
    resp = client.post("/run", json=_payload())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "unavailable"
    assert "no domain" not in resp.text
    assert client.get("/health").json()["status"] == "ok"


def test_run_rejects_body_without_required_fields(client):
    """Тело валидируется по общему контракту AgentRunInput (text/thread_id обязательны)."""
    assert client.post("/run", json={"text": "нет треда"}).status_code == 422


def test_run_passes_contract_fields_to_engine(client, monkeypatch):
    """Собранные бэкендом данные (Фаза 0b) доезжают до движка, а транспортное — нет."""
    seen = {}

    class _Capture(_FakeEngine):
        async def execute(self, *, on_event=None, **kwargs):
            seen.update(kwargs)
            return {"reply": "ok"}

    monkeypatch.setattr(runtime, "DefaultAgentExecutionService", lambda: _Capture())
    client.post(
        "/run",
        json=_payload(
            memory_parts=["факты", "recall"],
            history_messages=[{"role": "user", "content": "прошлое"}],
            compact_summary="резюме",
            tabular_files=[{"name": "t1.csv", "url": "http://minio/x"}],
        ),
    )
    assert seen["memory_parts"] == ("факты", "recall")  # JSON-массив → tuple контракта
    assert seen["history_messages"] == [{"role": "user", "content": "прошлое"}]
    assert seen["compact_summary"] == "резюме"
    assert seen["tabular_files"][0]["name"] == "t1.csv"
    assert "on_event" not in seen  # колбэк передаётся отдельно, не через kwargs тела


def test_providers_keys_applies_snapshot_wholesale(client, monkeypatch):
    """Снимок ключей применяется ЦЕЛИКОМ: чего нет в теле — override снимается.

    Иначе снятый в панели ключ навсегда остался бы жить в сайдкаре: он ведь не знает
    про удаление, а PG/Redis у него нет. Снимок целиком лечит и рестарт сайдкара.
    """
    calls = {"set": [], "cleared": [], "rebuilt": []}
    overrides = {"openrouter": "старый-ключ"}  # уже стоит override у openrouter

    fake_pc = type(
        "PC",
        (),
        {
            "get_override": staticmethod(lambda p: overrides.get(p)),
            "set_override": staticmethod(
                lambda p, k: (overrides.__setitem__(p, k), calls["set"].append(p))
            ),
            "clear_override": staticmethod(
                lambda p: (overrides.pop(p, None), calls["cleared"].append(p))
            ),
        },
    )
    monkeypatch.setattr(runtime, "known_provider_names", lambda: ["openai", "openrouter"])

    async def _rebuild(provider):
        calls["rebuilt"].append(provider)

    monkeypatch.setitem(
        __import__("sys").modules,
        "service.domain.client",
        type("M", (), {"rebuild_provider_generation": staticmethod(_rebuild)}),
    )
    # ⚠️ Учётные данные живут в ПОДПАКЕТЕ providers, и подменять надо именно его:
    # `keys.py` берёт их как `from ...client.providers import credentials`. Подмена
    # только родительского пакета оставила бы настоящий модуль на месте, и тест
    # проверял бы прод вместо дублёра — молча.
    monkeypatch.setitem(
        __import__("sys").modules,
        "service.domain.client.providers",
        type("P", (), {"credentials": fake_pc}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "service.presentation.routers.gateway.openai_v1",
        type("G", (), {"_auth": staticmethod(lambda a: None)}),
    )

    body = client.post(
        "/providers/keys", json={"version": 11, "overrides": {"openai": "новый-ключ"}}
    ).json()

    assert calls["set"] == ["openai"]  # новый override поставлен
    assert calls["cleared"] == ["openrouter"]  # отсутствующий в снимке — СНЯТ
    assert sorted(calls["rebuilt"]) == ["openai", "openrouter"]  # клиенты пересобраны
    assert body["version"] == 11
    # Наружу — только имена; значений ключей в ответе быть не должно.
    assert "новый-ключ" not in str(body)
    assert client.get("/health").json()["provider_keys"] == {"version": 11}


def test_providers_health_reports_probe_and_policy(client, monkeypatch):
    """`/providers/health` — здоровье глазами САЙДКАРА (он единственный звонит провайдерам).

    Панель отличает «выключен админом» от «упал сам», поэтому политика едет рядом с
    пробой. А `policy.known` показывает, знает ли сайдкар политику ВООБЩЕ: до первого
    /run он её не видел, и blocked/disabled в этот момент читать нельзя.
    """
    import service.shared.provider_policy_context as ppc

    seen: dict = {}

    async def _fake_health(*, force_probe=False, only=None):
        seen["only"] = only
        return {
            "active_provider": "gigachat",
            "providers": {
                "mws": {"configured": True, "reachable": False, "probed_force": force_probe}
            },
        }

    monkeypatch.setattr("service.domain.client.health.compute_provider_health", _fake_health)
    monkeypatch.setattr(ppc, "_LAST_SEEN", None)

    body = client.get("/providers/health").json()
    assert body["active_provider"] == "gigachat"
    assert body["providers"]["mws"]["reachable"] is False
    assert seen["only"] is None, "без ?only ручка обязана спрашивать про всех"

    # ?only=a,b — точечная проба (периодическая самопроверка заблокированных на
    # стороне backend'а). Пустое значение значит «никого», а не «всех»: иначе опечатка
    # в вызове молча возвращает полный обход с настоящими вызовами к провайдерам.
    client.get("/providers/health?only=mws,openai")
    assert seen["only"] == {"mws", "openai"}, f"фильтр не доехал до движка: {seen['only']}"
    client.get("/providers/health?only=")
    assert seen["only"] == set(), f"пустой фильтр превратился в «всех»: {seen['only']}"
    assert body["policy"]["known"] is False  # прогонов не было — политика неизвестна
    assert body["providers"]["mws"]["probed_force"] is False  # по умолчанию без force

    # force=true — «Проверить» в панели: пробить всех, не доверяя breaker'у.
    forced = client.get("/providers/health?force=true").json()
    assert forced["providers"]["mws"]["probed_force"] is True


def test_run_applies_provider_policy_snapshot(client, monkeypatch):
    """Снимок политики разворачивается в ОКРУЖЕНИЕ прогона, а не летит аргументом движка.

    Кого выключил админ и кого заблокировала health-проверка — знает только backend
    (его БД+Redis). Не развернём снимок — мультипровайдерный слой МОЛЧА решит, что
    запрещённых нет, и снятый админом провайдер снова примет трафик.
    """
    seen = {}

    class _Capture(_FakeEngine):
        async def execute(self, *, on_event=None, **kwargs):
            from service.shared.provider_policy_context import get_blocked, get_disabled

            seen["disabled"] = get_disabled()
            seen["blocked"] = get_blocked()
            seen["kwargs"] = kwargs
            return {"reply": "ok"}

    monkeypatch.setattr(runtime, "DefaultAgentExecutionService", lambda: _Capture())
    client.post(
        "/run",
        json=_payload(provider_policy={"disabled": [" MWS "], "blocked": ["OpenAI"]}),
    )

    assert seen["disabled"] == frozenset({"mws"})  # имена нормализованы
    assert seen["blocked"] == frozenset({"openai"})
    # execute такого аргумента не знает — попади он в kwargs, упал бы КАЖДЫЙ прогон.
    assert "provider_policy" not in seen["kwargs"]


def test_run_without_policy_leaves_context_untouched(client, monkeypatch):
    """Backend старее сайдкара снимка не пришлёт → «политика неизвестна».

    Снимок ЗАПОМИНАЕТСЯ на весь процесс (ради `/v1`), поэтому тест обязан сам сбросить
    память — иначе он проверял бы остаток от соседнего теста, а не заявленное поведение.
    """
    from service.shared import provider_policy_context as ppc

    monkeypatch.setattr(ppc, "_LAST_SEEN", None)
    seen = {}

    class _Capture(_FakeEngine):
        async def execute(self, *, on_event=None, **kwargs):
            seen["disabled"] = ppc.get_disabled()
            return {"reply": "ok"}

    monkeypatch.setattr(runtime, "DefaultAgentExecutionService", lambda: _Capture())
    client.post("/run", json=_payload())
    assert seen["disabled"] is None  # None ≠ пустое множество: источник читаем свой


def test_run_remembers_policy_for_paths_without_their_own(client, monkeypatch):
    """Снимок остаётся известен ПОСЛЕ прогона — иначе `/v1` (OpenAI-протокол, места под
    политику нет) продолжил бы считать, что запрещённых провайдеров не существует."""
    from service.shared import provider_policy_context as ppc

    monkeypatch.setattr(ppc, "_LAST_SEEN", None)
    monkeypatch.setattr(runtime, "DefaultAgentExecutionService", lambda: _FakeEngine())

    assert client.get("/health").json()["provider_policy"]["known"] is False
    client.post("/run", json=_payload(provider_policy={"disabled": ["mws"], "blocked": []}))

    assert ppc.get_disabled() == frozenset({"mws"})  # вне запроса — память процесса
    assert client.get("/health").json()["provider_policy"] == {
        "known": True,
        "disabled": ["mws"],
        "blocked": [],
    }
