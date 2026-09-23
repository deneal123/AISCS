"""Инструменты песочницы: гейт, тарификация, отказ словами.

🔴 Главное утверждение среза — то же, что у MCP: шесть инструментов НЕ получают своей
машинерии. Они регистрируются обычными `ToolSpec` и наследуют гейт применимости, потолки,
тарификацию и отчёт об отказах. Сеть не трогаем: клиент подменяется.
"""

from __future__ import annotations

import json

import pytest

from service.contracts import BILLABLE_TOOLS
from service.domain.capabilities import tool_registry
from service.domain.integration_failure import IntegrationFailureCode
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.tools import workspace_tools as wt
from service.domain.tools.workspace_client import WorkspaceUnavailable

REF = {"workspace_id": "ws1", "token": "t.sig", "user_id": "7", "root": "/workspace"}


class _Ctx:
    def __init__(self, ref=None) -> None:
        self.context = {"workspace_ref": ref} if ref is not None else {}


def _text(answer: str | ToolCallOutcome) -> str:
    return answer.text if isinstance(answer, ToolCallOutcome) else answer


@pytest.fixture
def calls(monkeypatch):
    """Подменяет клиента и записывает, что ушло в сайдкар."""
    seen: list[tuple[str, dict]] = []
    replies: dict[str, dict] = {}

    async def fake_call(ref, path, payload):
        # 🔴 ПРОВЕРЯЕМ, ЧТО УШЛО В КЛИЕНТ, А НЕ ТОЛЬКО ЧТО ЕГО ПОЗВАЛИ. Раньше фикстура
        # подменяла `call` целиком и первый аргумент не смотрела — а туда уезжал БУЛЕВ
        # флаг гейта вместо ссылки на песочницу, и все девять инструментов отвечали
        # «песочница не выдана этому запросу». Найдено живым прогоном, не тестом.
        assert isinstance(ref, dict) and ref.get("workspace_id") and ref.get("token"), (
            f"в клиент уехала не ссылка на песочницу, а {ref!r} — инструменты будут "
            "отказывать на каждом вызове"
        )
        seen.append((path, payload))
        if isinstance(replies.get(path), Exception):
            raise replies[path]
        return replies.get(path, {"ok": True})

    monkeypatch.setattr(wt, "call", fake_call)
    return seen, replies


# --- гейт и реестр ------------------------------------------------------------------


def test_tools_are_absent_until_the_orchestrator_asks() -> None:
    """🔴 Песочница есть почти всегда — гейт по НЕЙ выдавал бы шесть схем каждому запросу.

    Замер на живом прогоне: «прочитай файл и сделай саммери» стоил 38k токенов вместо 19k,
    потому что модель полезла в песочницу за документом, лежавшим у неё в контексте.
    """

    class _OnlyWorkspace:
        workspace_ref = REF
        workspace_tools_enabled = False

    resolved = tool_registry.resolve_toolset(list(wt.WORKSPACE_TOOLS), _OnlyWorkspace())
    assert resolved.tools == []
    assert {o.detail for o in resolved.omissions} == {"workspace_tools_enabled"}


def test_tools_appear_when_the_orchestrator_asks_for_files() -> None:
    class _Context:
        workspace_ref = REF
        workspace_tools_enabled = True

    resolved = tool_registry.resolve_toolset(list(wt.WORKSPACE_TOOLS), _Context())
    assert [t.name for t in resolved.tools] == [t.name for t in wt.WORKSPACE_TOOLS]


def test_admin_toggle_actually_removes_the_tools(monkeypatch) -> None:
    """🔴 Поле `enabled_field` было ОБЪЯВЛЕНО И НЕ ЧИТАЛОСЬ — тумблер-обманка."""
    monkeypatch.setattr(tool_registry, "_flag_enabled", lambda field: False)

    class _Context:
        workspace_ref = REF
        workspace_tools_enabled = True

    resolved = tool_registry.resolve_toolset(list(wt.WORKSPACE_TOOLS), _Context())
    assert resolved.tools == []
    assert {o.reason for o in resolved.omissions} == {"disabled_by_config"}


def test_every_tool_is_registered_and_billed_by_one_name() -> None:
    """⚠️ ОДНА запись на шесть: запись на инструмент делала бы каждый новый релизом двух
    репозиториев через парити-гейт."""
    specs = tool_registry.tool_specs()
    names = [t.name for t in wt.WORKSPACE_TOOLS]
    assert set(names) <= set(specs)
    assert {specs[n].billing_name for n in names} == {"workspace_tool"}
    assert "workspace_tool" in BILLABLE_TOOLS


def test_read_gets_a_larger_result_limit_than_the_rest() -> None:
    """Файл читают, чтобы получить его целиком; вывод команды — чтобы увидеть исход."""
    assert tool_registry.tool_result_limit("ws_read") > tool_registry.tool_result_limit("ws_run")


# --- поведение инструментов ----------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_id_comes_from_the_run_not_from_the_model(calls) -> None:
    """🔴 Модель не называет песочницу: иначе она назвала бы ЧУЖУЮ."""
    seen, _ = calls
    await wt.ws_read_tool(_Ctx(REF), json.dumps({"path": "a.txt", "workspace_id": "чужая"}))
    path, payload = seen[0]
    assert path == "files/read"
    assert "workspace_id" not in payload and payload["path"] == "a.txt"


@pytest.mark.asyncio
async def test_dead_sidecar_becomes_words_not_a_crash(calls) -> None:
    seen, replies = calls
    replies["exec"] = WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE, retryable=True)
    answer = await wt.ws_run_tool(_Ctx(REF), json.dumps({"command": "ls"}))
    assert isinstance(answer, ToolCallOutcome)
    assert answer.failure_code == "unavailable"
    assert answer.retryable is True
    assert answer.billable is False
    assert "временно недоступна" in answer.text


@pytest.mark.asyncio
async def test_edit_refuses_an_ambiguous_fragment(calls) -> None:
    """🔴 Иначе «замени X на Y» в файле с десятью X молча правит все десять."""
    seen, replies = calls
    replies["files/read"] = {"content": "a\nX\nX\n", "truncated": False, "revision": "r1"}
    answer = await wt.ws_edit_tool(_Ctx(REF), json.dumps({"path": "f", "old": "X", "new": "Y"}))
    assert "2 раз" in _text(answer)
    assert not [p for p, _ in seen if p == "files/write"], "правка ушла, хотя отменена"


@pytest.mark.asyncio
async def test_edit_refuses_a_truncated_file(calls) -> None:
    """Записать хвост, которого мы не видели, значит его потерять."""
    seen, replies = calls
    replies["files/read"] = {"content": "X", "truncated": True, "revision": "r1"}
    answer = await wt.ws_edit_tool(_Ctx(REF), json.dumps({"path": "f", "old": "X", "new": "Y"}))
    assert "не целиком" in _text(answer)
    assert not [p for p, _ in seen if p == "files/write"]


@pytest.mark.asyncio
async def test_edit_writes_once_when_unambiguous(calls) -> None:
    seen, replies = calls
    replies["files/read"] = {
        "content": "before X after",
        "truncated": False,
        "revision": "r1",
    }
    await wt.ws_edit_tool(_Ctx(REF), json.dumps({"path": "f", "old": "X", "new": "Y"}))
    written = [p for p, _ in seen if p == "files/write"]
    assert len(written) == 1
    assert dict(seen[-1][1])["content"] == "before Y after"
    assert dict(seen[-1][1])["expected_revision"] == "r1"


@pytest.mark.asyncio
async def test_missing_fragment_changes_nothing(calls) -> None:
    seen, replies = calls
    replies["files/read"] = {
        "content": "nothing here",
        "truncated": False,
        "revision": "r1",
    }
    answer = await wt.ws_edit_tool(_Ctx(REF), json.dumps({"path": "f", "old": "X", "new": "Y"}))
    assert "нет" in _text(answer)
    assert not [p for p, _ in seen if p == "files/write"]


# --- опись созданного -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_are_an_inventory_not_bytes(monkeypatch) -> None:
    """⚠️ Байты забирает backend, у которого есть хранилище: сайдкар агентов их не возит.

    ⚠️ Подменяем `call` В МОДУЛЕ КЛИЕНТА, а не в модуле инструментов: `list_artifacts`
    берёт его из своего пространства имён, и подмена соседа на него не действует —
    первая версия теста именно так и зеленела бы вхолостую, вернув пустой список.
    """
    from service.domain.tools import workspace_client as wc

    async def fake_call(ref, path, payload):
        assert path == "artifacts"
        return {"artifacts": [{"path": "out/report.md", "size": 9}]}

    monkeypatch.setattr(wc, "call", fake_call)
    items = await wc.list_artifacts(REF)
    assert items == [{"path": "out/report.md", "size": 9}]
    assert all("content" not in i for i in items)


@pytest.mark.asyncio
async def test_dead_sidecar_does_not_lose_the_finished_reply(monkeypatch) -> None:
    """🔴 Отчёт в КОНЦЕ прогона: уронить из-за него уже готовый ответ — худший размен."""
    from service.domain.tools import workspace_client as wc

    async def dead(ref, path, payload):
        raise wc.WorkspaceUnavailable("сервис песочницы не отвечает")

    monkeypatch.setattr(wc, "call", dead)
    assert await wc.list_artifacts(REF) == []


@pytest.mark.asyncio
async def test_no_workspace_means_the_sidecar_is_not_asked_at_all(monkeypatch) -> None:
    """Без песочницы описи нет — и сайдкар при этом НЕ СПРАШИВАЮТ.

    ⚠️ Проверяем ФАКТ обращения, а не пустой ответ: пустой список отдал бы и клиент, у
    которого ссылка без токена, — то есть проверка «не спрашиваем без песочницы» осталась
    бы непроверенной.
    """
    from service.application.agent_execution_service import _workspace_artifacts
    from service.domain.tools import workspace_client as wc

    asked = []

    async def recorder(ref, path, payload):
        asked.append(path)
        return {}

    monkeypatch.setattr(wc, "call", recorder)
    assert await _workspace_artifacts(None) == []
    assert asked == [], "сайдкар спрошен, хотя песочницы нет"


@pytest.mark.asyncio
async def test_junk_entries_never_reach_the_inventory(monkeypatch) -> None:
    """Опись уезжает в биллинг и в UI: строка вместо записи сломала бы потребителя."""
    from service.domain.tools import workspace_client as wc

    async def fake_call(ref, path, payload):
        return {"artifacts": [{"path": "a", "size": 1}, "мусор", None, 42]}

    monkeypatch.setattr(wc, "call", fake_call)
    assert await wc.list_artifacts(REF) == [{"path": "a", "size": 1}]


def test_inventory_is_declared_in_the_result_contract() -> None:
    """Ключ, которого нет в контракте, потребитель прочитает как пустоту — молча."""
    from service.contracts import RESULT_FIELDS

    assert "workspace_artifacts" in RESULT_FIELDS


@pytest.mark.asyncio
async def test_empty_workspace_answers_in_words_not_with_an_empty_list(calls) -> None:
    """🔴 Живой прогон: модель решила, что файлы недоступны ВООБЩЕ, и сказала это
    пользователю — при том, что текст его документа лежал у неё в контексте. Пустой
    JSON-массив она трактует так же, поэтому ответ обязан объяснять словами."""
    seen, replies = calls
    replies["files/list"] = {"entries": [], "truncated": False}
    answer = await wt.ws_list_tool(_Ctx(REF), "{}")
    low = answer.lower()
    assert "пуст" in low and "контексте" in low


@pytest.mark.asyncio
async def test_an_empty_directory_is_reported_as_a_failure_not_as_normal(calls) -> None:
    """🔴 ЖИВАЯ ЖАЛОБА. Человек загрузил `src.zip`, импорт упал, каталог остался пуст — и
    прежний ответ звал «отвечать по контексту». В контексте при этом лежала одна КАРТА
    репозитория, без единой строки кода, и модель заполнила пустоту рассуждениями об
    архитектуре: «никак не могу с ней взаимодействовать, ни посмотреть что внутри».

    Пустой каталог при приложенном архиве — ПОЛОМКА. Ответ обязан велеть сказать об этом
    прямо и запретить выдумывать: молчание здесь неотличимо от «файлов и не было».
    """
    seen, replies = calls
    replies["files/list"] = {"entries": [], "truncated": False}

    answer = await wt.ws_list_tool(_Ctx(REF), "{}")
    low = answer.lower()

    assert "не доехали" in low or "не доехал" in low, (
        "пустой каталог выдан за норму — про сбой импорта не сказано ничего"
    )
    assert "не придумывай" in low, "выдумывать содержимое не запрещено — ровно это и случилось"
    assert "карта" in low, (
        "про карту репозитория не сказано: модель сочтёт её содержимым и «перескажет» код, "
        "которого в ней нет"
    )
    assert "не здесь" not in low, (
        "ответ снова утверждает, что вложения лежат не в каталоге — это НЕПРАВДА: файлы "
        "диалога импортируются каждый ход, а архив разворачивается деревом"
    )


@pytest.mark.asyncio
async def test_non_empty_workspace_returns_the_listing(calls) -> None:
    seen, replies = calls
    replies["files/list"] = {"entries": [{"path": "/workspace/a.txt", "size": 1}]}
    assert "a.txt" in await wt.ws_list_tool(_Ctx(REF), "{}")


def test_descriptions_say_whose_directory_it_is() -> None:
    """⚠️ Именно формулировка «рабочий каталог пользователя» и увела модель в песочницу за
    приложенным PDF. Описание — это интерфейс инструмента, и оно обязано говорить правду.

    ⚠️ Требование ПОЛОЖИТЕЛЬНОЕ, а не запрет формулировки: чёрный список ловит ту фразу,
    которую в него вписали, и пропускает любую её вариацию — первая версия этого стража
    зеленела на «в рабочем каталоге пользователя», отличавшемся одной буквой.
    """
    for tool in wt.WORKSPACE_TOOLS:
        assert "тво" in tool.description.lower(), (
            f"{tool.name}: описание не говорит, ЧЕЙ это каталог — модель решит, что там "
            f"лежит документ пользователя"
        )


def test_reading_tools_point_back_to_the_context() -> None:
    """Инструменты чтения обязаны сказать, где ДЕЙСТВИТЕЛЬНО лежит документ пользователя."""
    for tool in (wt.ws_list, wt.ws_read):
        assert "контекст" in tool.description.lower(), tool.name


def test_orchestrator_signal_needs_a_workspace_too() -> None:
    """🔴 Два условия сходятся в ОДИН признак: спека проверяет одно поле, и разносить
    условия по двум местам значило бы однажды проверить только одно."""
    from datetime import UTC, datetime

    from service.domain.pipeline.auto_mode import AutoPlan, apply_plan
    from service.schemas.agents import UserContext

    def _ctx(**kw):
        return UserContext(user_id="7", request_time=datetime.now(UTC), **kw)

    without = _ctx()
    apply_plan(
        context=without,
        plan=AutoPlan(files_tool=True),
        multi_intent=None,
        planning=None,
        resolved_category=None,
    )
    assert without.workspace_tools_enabled is False, "инструменты без песочницы"

    granted = _ctx(workspace_ref=REF)
    apply_plan(
        context=granted,
        plan=AutoPlan(files_tool=True),
        multi_intent=None,
        planning=None,
        resolved_category=None,
    )
    from service.domain.run_context import require_execution

    assert require_execution().policy.flag("workspace_tools_enabled") is True

    silent = _ctx(workspace_ref=REF)
    apply_plan(
        context=silent,
        plan=AutoPlan(files_tool=False),
        multi_intent=None,
        planning=None,
        resolved_category=None,
    )
    assert silent.workspace_tools_enabled is False, "выдано без просьбы оркестратора"


def test_prompt_teaches_the_distinction_in_users_own_words() -> None:
    """🔴 Рядовой пользователь про «workspace» не знает и никогда его не назовёт — решать
    обязан оркестратор ПО СМЫСЛУ просьбы. Поэтому в промпте живые формулировки с обеих
    сторон границы, а не термин системы."""
    from service.domain.routing.auto_prompt import auto_prompt

    text = auto_prompt()
    assert "needs_files" in text
    for wants_file in ("пришли файлом", "оформи в docx", "построй график"):
        assert wants_file in text, wants_file
    for wants_text in ("сделай саммери", "перескажи"):
        assert wants_text in text, wants_text
    assert "ставь false" in text.lower(), "нет правила на случай сомнения"


@pytest.mark.asyncio
async def test_decision_reaches_the_plan(monkeypatch) -> None:
    """⚠️ Тесты выше строят план НАПРЯМУЮ и потому не видят связку «решение → план».

    Мутация «files_tool всегда False» оставалась зелёной: решение оркестратора могло не
    доезжать до плана вовсе, а гейт при этом выглядел работающим.
    """
    from datetime import UTC, datetime

    from service.domain.pipeline import auto_mode
    from service.domain.routing.auto_decision import AutoDecision
    from service.schemas.agents import UserContext

    async def decided(*args, **kwargs):
        return AutoDecision(route="general", confidence="high", needs_files=True)

    monkeypatch.setattr(auto_mode, "decide_modes", decided)

    context = UserContext(user_id="7", request_time=datetime.now(UTC), workspace_ref=REF)
    plan = await auto_mode.resolve_auto_plan(
        user_input="собери отчёт файлом", context=context, input_type="text"
    )
    assert plan.files_tool is True, "решение оркестратора не доехало до плана"


@pytest.mark.parametrize(
    "text",
    [
        "воспользуйся workspace",
        "Воспользуйся Workspace и переведи",
        "запусти код и покажи вывод",
        "сохрани в файл результат",
        "поработай в песочнице",
        "создай в рабочем месте файл agent-note.txt",
        "обнови файл в рабочей области",
    ],
)
def test_an_explicit_request_beats_the_orchestrator(text: str) -> None:
    """🔴 Живой прогон: на «воспользуйся workspace» оркестратор не поставил признак, и
    ассистент ответил, что доступа к файлам у него нет. Спорить с прямой просьбой нельзя.

    ⚠️ Правило ДЕТЕРМИНИРОВАННОЕ, а не «модель поймёт»: тот же урок, что с оговорками у
    личностей — там помогло только дописывание кодом.
    """
    from service.domain.pipeline.auto_mode import _explicitly_asks_for_files

    assert _explicitly_asks_for_files(text) is True


@pytest.mark.parametrize(
    "text", ["прочитай файл и сделай саммери", "переведи файл на английский", "что в файле?"]
)
def test_reading_a_document_is_not_an_explicit_request(text: str) -> None:
    """Обратная сторона: слово «файл» само по себе НЕ включает инструменты, иначе вернётся
    та самая двойная отправка вложения, которая стоила 8260 кредитов."""
    from service.domain.pipeline.auto_mode import _explicitly_asks_for_files

    assert _explicitly_asks_for_files(text) is False


def test_explicit_request_works_even_when_the_orchestrator_is_off() -> None:
    """Выключенная настройка не повод игнорировать прямую просьбу."""
    from service.domain.pipeline.auto_mode import AutoPlan

    assert AutoPlan.passthrough("выключен", files_tool=True).files_tool is True


def test_tools_receive_the_workspace_ref_not_the_gate_flag() -> None:
    """🔴 ГЕЙТ И ССЫЛКА — РАЗНЫЕ ВЕЩИ, и их однажды спутали.

    `workspace_tools_enabled` — булево решение оркестратора «выдавать ли инструменты»;
    `workspace_ref` — сама песочница (идентификатор + токен владения). Пока `_ref` читал
    первое, в клиент уезжало `True`, и КАЖДЫЙ вызов отвечал «песочница не выдана этому
    запросу»: модель послушно сообщала пользователю, что доступа к файлам нет.
    """

    class _Context:
        workspace_ref = REF
        workspace_tools_enabled = True

    class _Wrapper:
        context = _Context()

    assert wt._ref(_Wrapper()) == REF, "инструментам достаётся флаг гейта вместо песочницы"
    assert wt._ref(_Ctx(REF)) == REF, "словарный контекст отдаёт не ссылку"
