"""Контракт HttpAgentEngine — движка, которым backend исполняет агента НА САЙДКАРЕ.

Это код, который понесёт БОЕВОЙ трафик в момент переключения
``AGENTS__ENGINE_MODE=http``, поэтому фиксируем его поведение до переключения:

* события из NDJSON восстанавливаются в ``AgentEvent`` и уходят в тот же ``on_event``
  (иначе воркер не сможет форвардить их в Redis/WS и копить текст ответа);
* терминальный ``__result__`` возвращается как result-dict (из него воркер БИЛЛИТ);
* ``__error__`` и обрыв без результата → ИСКЛЮЧЕНИЕ, а не тихий успех: иначе воркер
  спишет деньги за пустоту;
* несериализуемое (``pseudo_session``/``on_event``) в тело запроса не попадает.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from service.infrastructure.agents_client import http_agent_engine as hae
from service.infrastructure.agents_client.contracts.events import EventType

RUN_FINALIZATION_CORPUS_VERSION = "s26-v1"
_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "run_quality_s16.json"


@dataclass(frozen=True)
class _FinalizationScenario:
    manifest_id: str
    lines: list[str]
    expected_reply: str
    expected_reasons: list[str]


class _FakeResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b"sidecar boom"


class _FakeStreamCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeClient:
    def __init__(self, response: _FakeResponse, captured: dict, client_kwargs: dict) -> None:
        self._response = response
        self._captured = captured
        self._captured["client_kwargs"] = client_kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def stream(self, method: str, url: str, json=None, headers=None):  # noqa: A002
        self._captured.update(
            {"method": method, "url": url, "json": json, "headers": headers or {}}
        )
        return _FakeStreamCtx(self._response)


def _engine(
    monkeypatch,
    lines: list[str],
    status_code: int = 200,
    api_key: str = "",
    run_timeout_sec: float = 570.0,
) -> tuple[hae.HttpAgentEngine, dict]:
    captured: dict = {}
    response = _FakeResponse(lines, status_code=status_code)
    monkeypatch.setattr(hae.httpx, "AsyncClient", lambda **kw: _FakeClient(response, captured, kw))

    class _Agents:
        sidecar_url = "http://agents:8090"
        sidecar_timeout_sec = 5.0
        llm_gateway_api_key = api_key

    _Agents.run_timeout_sec = run_timeout_sec

    class _Cfg:
        agents = _Agents()

    return hae.HttpAgentEngine(_Cfg()), captured


def _event_line(type_: str, data: str = "", **extra) -> str:
    # Форма — как у EventSerializer: с транспортными полями, которых нет в AgentEvent.
    payload = {
        "type": type_,
        "job_id": "job-1",
        "data": data,
        "message": data,
        "agent_name": "general",
        "metadata": {},
        "seq": 0,
        "timestamp": "2026-07-18T00:00:00+00:00",
        **extra,
    }
    return json.dumps(payload, ensure_ascii=False)


def _base_kwargs(**over):
    kw = {
        "text": "привет",
        "thread_id": "t1",
        "user_id": "7",
        "session_data": None,
        "selected_model": None,
        "route_override": None,
        "input_type": None,
        "web_search": False,
        "deep_research": False,
        "file_context": "",
    }
    kw.update(over)
    return kw


def test_backend_default_run_deadline_matches_sidecar_contract() -> None:
    from service.settings import AgentsConfig

    assert AgentsConfig.model_fields["run_timeout_sec"].default == 570.0


def test_transport_quality_manifest_is_versioned_and_data_free() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    scenario_ids = {item["id"] for item in manifest["scenarios"]}

    assert manifest["version"] == RUN_FINALIZATION_CORPUS_VERSION
    assert {
        "first_valid_result",
        "error_before_result_recovery",
        "post_terminal_discard",
        "invalid_terminal_and_eof",
        "privacy_boundary",
        "malformed_event_drop",
        "crash_redelivery_single_billing",
    } <= scenario_ids
    assert "synthetic-request-must-not-enter" not in str(manifest)
    assert not {"prompt", "arguments", "result", "request_text", "url"} & set(manifest)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        _FinalizationScenario(
            manifest_id="first_valid_result",
            lines=[
                json.dumps({"__result__": {"reply": "first"}}),
                json.dumps({"__result__": {"reply": "second"}}),
            ],
            expected_reply="first",
            expected_reasons=["duplicate_result"],
        ),
        _FinalizationScenario(
            manifest_id="error_before_result_recovery",
            lines=[
                json.dumps({"__error__": "recovering"}),
                json.dumps({"__result__": {"reply": "recovered", "per_call_usage": []}}),
            ],
            expected_reply="recovered",
            expected_reasons=["result_after_error"],
        ),
    ],
    ids=lambda item: item.manifest_id,
)
async def test_run_finalization_golden_contract(
    monkeypatch, scenario: _FinalizationScenario
) -> None:
    """Versioned deterministic transport gate: one reply, one accounting envelope."""
    engine, _ = _engine(monkeypatch, scenario.lines)
    events = []

    result = await engine.execute(on_event=events.append, **_base_kwargs())

    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    expected = next(item for item in manifest["scenarios"] if item["id"] == scenario.manifest_id)

    assert RUN_FINALIZATION_CORPUS_VERSION == "s26-v1"
    assert result["reply"] == scenario.expected_reply
    assert [event.metadata["kind"] for event in events] == ["run_integrity"]
    reasons = events[0].metadata["run_integrity"]["reasons"]
    assert reasons == scenario.expected_reasons == expected["reasons"]
    assert all("reply" not in str(event.metadata) for event in events)


@pytest.mark.asyncio
async def test_forwards_events_and_returns_result(monkeypatch) -> None:
    lines = [
        _event_line("routing_complete", "Выбран агент: general"),
        _event_line("stream_chunk", "прив"),
        json.dumps({"__result__": {"reply": "прив", "resolved_model": "m", "prompt_tokens": 5}}),
    ]
    engine, _ = _engine(monkeypatch, lines)
    seen = []
    result = await engine.execute(on_event=seen.append, **_base_kwargs())

    # События восстановлены в AgentEvent (воркер зовёт .type/.data) и доехали по порядку.
    assert [e.type for e in seen] == ["routing_complete", "stream_chunk"]
    assert [e.data for e in seen] == ["Выбран агент: general", "прив"]
    assert seen[0].agent_name == "general"
    # result-dict вернулся как есть — из него воркер биллит.
    assert result == {"reply": "прив", "resolved_model": "m", "prompt_tokens": 5}


@pytest.mark.asyncio
async def test_run_request_carries_bearer_key(monkeypatch) -> None:
    """Backend обязан слать ключ: сайдкар закрыл `/run`.

    ⚠️ Без этого заголовка прод встал бы целиком — каждый чат получал бы 401. Тест
    закрепляет ПАРУ: сайдкар требует ключ (agents/tests/test_internal_auth.py), backend
    его отправляет. Половина этой пары в одиночку означает сломанный сервис.
    """
    engine, captured = _engine(
        monkeypatch, [json.dumps({"__result__": {"reply": "ok"}})], api_key="secret-key"
    )

    await engine.execute(on_event=None, **_base_kwargs())

    assert captured["headers"]["Authorization"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_unknown_event_type_is_dropped_and_counted_without_payload(monkeypatch) -> None:
    """Незнакомый тип события НЕ должен уносить с собой полезную нагрузку.

    ⚠️ `type` в `AgentEvent` — строгий StrEnum, поэтому событие нового типа (сайдкар
    новее backend) роняет ВСЮ модель. Раньше такая строка молча исчезала: окажись это
    `stream_chunk`, пользователь потерял бы КУСОК ОТВЕТА и не узнал бы об этом.

    Основную защиту даёт офлайн-гейт (сверяет наборы типов и блокирует CI); здесь —
    последний рубеж на случай, когда версии всё же разъехались.
    """
    lines = [
        _event_line("stream_chunk", "начало "),
        _event_line("совершенно_новый_тип", "важный хвост"),
        json.dumps({"__result__": {"reply": "начало важный хвост"}}),
    ]
    engine, _ = _engine(monkeypatch, lines)
    seen = []

    await engine.execute(on_event=seen.append, **_base_kwargs())

    assert len(seen) == 2
    assert seen[0].type == EventType.STREAM_CHUNK
    integrity = seen[1].metadata["run_integrity"]
    assert integrity["anomaly_count"] == 1
    assert integrity["reasons"] == ["invalid_event"]
    assert "важный хвост" not in str(seen)
    assert "совершенно_новый_тип" not in str(seen)


@pytest.mark.asyncio
async def test_error_line_raises(monkeypatch) -> None:
    error = "synthetic-sidecar-error-must-not-leak"
    engine, _ = _engine(monkeypatch, [json.dumps({"__error__": error})])
    with pytest.raises(RuntimeError, match="agents sidecar run failed") as exc_info:
        await engine.execute(on_event=lambda _e: None, **_base_kwargs())
    assert error not in str(exc_info.value)


@pytest.mark.asyncio
async def test_partial_result_wins_over_trailing_diagnostic_error(monkeypatch) -> None:
    """Usage частичного результата важнее диагностической строки после него."""
    partial = {
        "reply": "Успели подготовить часть ответа",
        "metadata": {"execution_status": "timed_out", "partial_failure": True},
        "per_call_usage": [{"model": "m", "prompt": 20, "completion": 3}],
    }
    engine, _ = _engine(
        monkeypatch,
        [json.dumps({"__result__": partial}), json.dumps({"__error__": "hard deadline"})],
    )

    assert await engine.execute(on_event=None, **_base_kwargs()) == partial


@pytest.mark.asyncio
async def test_first_valid_result_is_the_only_billable_envelope(monkeypatch) -> None:
    first = {"reply": "first", "per_call_usage": [{"model": "m", "prompt": 3}]}
    second = {"reply": "second", "per_call_usage": [{"model": "m", "prompt": 999}]}
    engine, _ = _engine(
        monkeypatch,
        [
            json.dumps({"__result__": first}),
            json.dumps({"__result__": second}),
            _event_line("stream_chunk", "must not reach a client"),
            json.dumps({"__error__": "late diagnostic"}),
        ],
    )
    seen = []

    assert await engine.execute(on_event=seen.append, **_base_kwargs()) == first
    assert len(seen) == 1
    integrity = seen[0].metadata["run_integrity"]
    assert integrity["policy"] == "first_valid_result"
    assert integrity["reasons"] == ["duplicate_result", "error_after_result", "event_after_result"]
    assert "second" not in str(seen[0].metadata)
    assert "must not reach" not in str(seen[0].metadata)


@pytest.mark.asyncio
async def test_invalid_and_mixed_terminals_cannot_become_results(monkeypatch) -> None:
    valid = {"reply": "safe"}
    engine, _ = _engine(
        monkeypatch,
        [
            json.dumps({"__result__": {"reply": 1}}),
            json.dumps({"__result__": valid, "__error__": "ambiguous"}),
            json.dumps({"__result__": valid}),
        ],
    )
    seen = []

    assert await engine.execute(on_event=seen.append, **_base_kwargs()) == valid
    assert seen[0].metadata["run_integrity"]["reasons"] == ["invalid_result", "mixed_terminal"]


@pytest.mark.asyncio
async def test_result_after_error_preserves_usage_and_records_only_safe_signal(monkeypatch) -> None:
    result = {"reply": "recovered", "per_call_usage": [{"model": "m", "prompt": 2}]}
    engine, _ = _engine(
        monkeypatch,
        [json.dumps({"__error__": "recovering"}), json.dumps({"__result__": result})],
    )
    seen = []

    assert await engine.execute(on_event=seen.append, **_base_kwargs()) == result
    assert seen[0].metadata["run_integrity"] == {
        "policy": "first_valid_result",
        "anomaly_count": 1,
        "reasons": ["result_after_error"],
    }


@pytest.mark.asyncio
async def test_invalid_result_without_recovery_fails_without_billing_envelope(monkeypatch) -> None:
    engine, _ = _engine(monkeypatch, [json.dumps({"__result__": {"reply": None}})])

    with pytest.raises(RuntimeError, match="без терминального результата"):
        await engine.execute(on_event=lambda _event: None, **_base_kwargs())


@pytest.mark.asyncio
async def test_transport_timeout_follows_snapshot_deadline_and_grace(monkeypatch) -> None:
    engine, captured = _engine(monkeypatch, [json.dumps({"__result__": {"reply": "ok"}})])

    await engine.execute(
        on_event=None,
        agent_settings={"run_timeout_sec": 42.0},
        **_base_kwargs(),
    )

    assert captured["client_kwargs"]["timeout"] == 107.0


@pytest.mark.asyncio
async def test_disabled_deadline_keeps_configured_sidecar_timeout(monkeypatch) -> None:
    engine, captured = _engine(
        monkeypatch,
        [json.dumps({"__result__": {"reply": "ok"}})],
        run_timeout_sec=9.0,
    )

    await engine.execute(
        on_event=None,
        agent_settings={"run_timeout_sec": 0},
        **_base_kwargs(),
    )

    assert captured["client_kwargs"]["timeout"] == 5.0


@pytest.mark.asyncio
async def test_stream_without_result_raises(monkeypatch) -> None:
    """Обрыв без терминального результата — ошибка, а НЕ тихий успех.

    Иначе воркер счёл бы прогон удачным и списал деньги за пустой ответ.
    """
    engine, _ = _engine(monkeypatch, [_event_line("stream_chunk", "кусок")])
    with pytest.raises(RuntimeError, match="без терминального результата"):
        await engine.execute(on_event=lambda _e: None, **_base_kwargs())


@pytest.mark.asyncio
async def test_http_error_status_raises(monkeypatch) -> None:
    engine, _ = _engine(monkeypatch, [], status_code=503)
    with pytest.raises(RuntimeError, match="503") as exc_info:
        await engine.execute(on_event=lambda _e: None, **_base_kwargs())
    assert "sidecar boom" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_malformed_ndjson_is_logged_without_its_contents(monkeypatch, caplog) -> None:
    secret = "synthetic-request-must-not-enter-log"
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    expected = next(item for item in manifest["scenarios"] if item["id"] == "malformed_event_drop")
    engine, _ = _engine(
        monkeypatch,
        [
            _event_line("stream_chunk", "safe-delta"),
            secret,
            _event_line("unknown_event", "synthetic-event-payload-must-not-enter"),
            json.dumps(
                {
                    "__result__": {
                        "reply": "ok",
                        "per_call_usage": [
                            {
                                "provider": "scripted",
                                "model": "golden",
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                            }
                        ],
                    }
                }
            ),
        ],
    )
    seen = []

    result = await engine.execute(on_event=seen.append, **_base_kwargs())

    integrity_events = [event for event in seen if event.metadata.get("kind") == "run_integrity"]
    projected_events = [event for event in seen if event.type == EventType.STREAM_CHUNK]
    actual_order = ["stream_projection", "run_integrity", "finalization"]
    actual_counts = {
        "billing_envelopes": int(bool(result.get("per_call_usage"))),
        "terminal_results": int(isinstance(result.get("reply"), str)),
        "forwarded_events": len(projected_events),
        "dropped_records": integrity_events[0].metadata["run_integrity"]["anomaly_count"],
    }

    assert actual_order == expected["event_order"]
    assert actual_counts == expected["counts"]
    assert integrity_events[0].metadata["run_integrity"]["reasons"] == expected["reasons"]
    assert integrity_events[0].metadata["run_integrity"]["reasons"] == expected["statuses"]
    assert result["reply"] == "ok"
    assert secret not in caplog.text
    assert secret not in str(seen)
    assert "synthetic-event-payload-must-not-enter" not in caplog.text
    assert "synthetic-event-payload-must-not-enter" not in str(seen)


@pytest.mark.asyncio
async def test_non_serializable_kwargs_are_not_sent(monkeypatch) -> None:
    """pseudo_session/on_event не попадают в тело: они несериализуемы, а историю
    несёт history_messages (Фаза 0b)."""
    lines = [json.dumps({"__result__": {"reply": "ok"}})]
    engine, captured = _engine(monkeypatch, lines)
    await engine.execute(
        on_event=lambda _e: None,
        pseudo_session=object(),
        memory_parts=("факты", "recall"),
        history_messages=[{"role": "user", "content": "прошлое"}],
        **_base_kwargs(),
    )
    body = captured["json"]
    assert "pseudo_session" not in body and "on_event" not in body
    # А поля контракта — на месте (в т.ч. собранные бэкендом данные Фазы 0b).
    assert body["text"] == "привет" and body["thread_id"] == "t1"
    assert body["memory_parts"] == ["факты", "recall"]  # tuple → JSON-массив
    assert body["history_messages"] == [{"role": "user", "content": "прошлое"}]
    assert captured["url"].endswith("/run")
