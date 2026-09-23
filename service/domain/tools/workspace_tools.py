"""Инструменты файловой песочницы: агент работает с файлами, а не только с чатом.

🔴 ГЛАВНОЕ: НИ ОДНОЙ СВОЕЙ МАШИНЕРИИ. Все инструменты — обычные `ToolSpec` с
`requires_context_attr="workspace_ref"`, и потому они наследуют гейт применимости (нет
песочницы — не выдаются, с причиной), потолок результата, кламп таймаута бюджетом прогона,
тарификацию и отчёт об отказах. То же утверждение, что и у MCP, — и проверяется оно тем же
способом.

⚠️ ТАРИФИКАЦИЯ — ОДНА ЗАПИСЬ `workspace_tool` НА ВСЕ, а не по инструменту: набор
сверяется с прайсом backend'а офлайн-гейтом, и запись на инструмент делала бы каждый новый
согласованным релизом двух репозиториев.

⚠️ Отказ сайдкара возвращается МОДЕЛИ ТЕКСТОМ, а не исключением: чужой сервис лёг — это его
дело, а пользователю нужен ответ. Выдумывать содержимое файла при этом прямо запрещено
формулировкой ответа.
"""

from __future__ import annotations

import json
import logging

from agents import FunctionTool, RunContextWrapper

from service.domain.integration_failure import IntegrationFailureCode
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools import unbilled_calls
from service.domain.tools.workspace_client import WorkspaceUnavailable, call
from service.domain.tools.workspace_tool_specs import (
    BILLING_NAME,
    build_workspace_specs,
)

logger = logging.getLogger(__name__)

# 🔴 Гейт — по РЕШЕНИЮ ОРКЕСТРАТОРА, а не по наличию песочницы. Песочница есть почти
# всегда, и по ней инструменты выдавались бы каждому запросу: шесть схем в промпте и
# соблазн модели искать в них приложенный документ.
# Потолок результата чтения ВЫШЕ общего: файл читают, чтобы получить его целиком.
# ⚠️ `None` тут нельзя — тогда содержимое файла уезжало бы в промпт КАЖДЫМ следующим
# раундом целиком; 24 000 символов это компромисс между «хватает» и «не разоряет».
READ_RESULT_LIMIT = 24_000


# 🔴 ГЕЙТ И ССЫЛКА — РАЗНЫЕ ВЕЩИ, И ИХ ОДНАЖДЫ СПУТАЛИ. `workspace_tools_enabled` это
# БУЛЕВО решение оркестратора «выдавать ли инструменты», а `workspace_ref` — сама
# песочница (идентификатор + токен владения). `_ref` читал ПЕРВОЕ и отдавал `True` туда,
# где ждут словарь: `_credentials` видел пустые данные и каждый вызов отвечал «песочница
# не выдана этому запросу». То есть ВСЕ ДЕВЯТЬ инструментов были мертвы — их предлагали
# модели, она их звала, получала отказ и честно говорила пользователю, что доступа к
# файлам нет. Найдено живым прогоном: `ws_write · 127 симв.` в трейсе — это длина текста
# отказа, а каталог песочницы оставался пуст.
#
# ⚠️ Тесты этого не ловили: фикстура подменяет `call` целиком, поэтому ЧТО именно ей
# передали, никто не проверял. Ниже добавлен страж на содержимое ссылки.
REF_ATTR = "workspace_ref"


def _ref(ctx: RunContextWrapper):
    """Ссылка на песочницу прогона — то, чем клиент подтверждает владение."""
    context = getattr(ctx, "context", None)
    if isinstance(context, dict):
        return context.get(REF_ATTR)
    return getattr(context, REF_ATTR, None)


def _args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _failure(exc: WorkspaceUnavailable) -> ToolCallOutcome:
    """Project a typed sidecar failure without parsing or forwarding its text."""

    unbilled_calls.waive(BILLING_NAME)
    failure = {
        "timeout": ToolFailureCode.TIMEOUT,
        "transport": ToolFailureCode.TRANSPORT,
        "remote": ToolFailureCode.REMOTE,
        "protocol": ToolFailureCode.PROTOCOL,
        "conflict": ToolFailureCode.CONFLICT,
        "expired": ToolFailureCode.UNAVAILABLE,
        "unavailable": ToolFailureCode.UNAVAILABLE,
        "invalid": ToolFailureCode.INVALID_ARGUMENTS,
        "cancelled": ToolFailureCode.CANCELLED,
        "policy": ToolFailureCode.POLICY,
        "internal": ToolFailureCode.INTERNAL,
    }.get(exc.reason_code, ToolFailureCode.INTERNAL)
    return ToolCallOutcome(
        exc.model_message(),
        "failed",
        0.0,
        retryable=exc.retryable,
        billable=False,
        failure_code=failure,
    )


async def _op(ctx: RunContextWrapper, raw: str, path: str, build: str) -> str | ToolCallOutcome:
    args = _args(raw)
    try:
        payload = json.loads(build) if build else {}
    except ValueError:
        payload = {}
    payload = {k: args.get(k, v) for k, v in payload.items()}
    try:
        return json.dumps(await call(_ref(ctx), path, payload), ensure_ascii=False)
    except WorkspaceUnavailable as exc:
        return _failure(exc)


async def ws_list_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """⚠️ Пустой каталог отвечает СЛОВАМИ, а не пустым списком.

    Живой прогон: модель получила отказ на `/`, решила, что файлы недоступны в принципе, и
    сказала это пользователю — при том, что текст его документа лежал у неё в контексте.
    Пустой JSON-массив она трактовала бы так же. Ответ обязан объяснять, что каталог свой и
    пуст, а документ пользователя искать не здесь.

    🔴 ПРЕЖНИЙ ТЕКСТ УТВЕРЖДАЛ НЕПРАВДУ: «приложенные документы лежат НЕ здесь». Файлы
    диалога импортируются в каталог КАЖДЫЙ ХОД, а архив разворачивается деревом — то есть
    для архива это было прямо наоборот. Хуже, что ответ звал «отвечать по контексту»
    ИМЕННО В ТОМ СЛУЧАЕ, когда каталог пуст из-за сбоя импорта: в контексте при этом лежит
    одна карта репозитория, без единой строки кода, и модель заполняла пустоту общими
    рассуждениями об архитектуре. Ровно это и увидел человек, загрузив `src.zip`.

    Пустой каталог при приложенном архиве — ПОЛОМКА, и сказать об этом надо прямо: молчание
    здесь неотличимо от «файлов и не было».
    """
    answer = await _op(ctx, raw, "files/list", '{"path": ""}')
    if isinstance(answer, ToolCallOutcome):
        return answer
    # ⚠️ Разбираем СТРУКТУРУ, а не ищем подстроку: первая версия сравнивала строку с
    # пробелом против строки без пробелов и не срабатывала никогда.
    try:
        empty = not (json.loads(answer).get("entries") or [])
    except (ValueError, AttributeError):
        empty = False
    if empty:
        return (
            "Рабочий каталог ПУСТ. Если пользователь приложил архив или файл — значит они "
            "до каталога НЕ ДОЕХАЛИ: скажи ему об этом прямо и НЕ придумывай содержимое. "
            "Текст обычного документа (pdf, docx) приходит отдельно, в контексте: если он "
            "там есть, отвечай по нему. Карта репозитория содержимым НЕ является — в ней "
            "нет ни одной строки кода, и пересказать её как код нельзя."
        )
    return answer


async def ws_read_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    return await _op(ctx, raw, "files/read", '{"path": ""}')


async def ws_write_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    return await _op(ctx, raw, "files/write", '{"path": "", "content": ""}')


async def ws_grep_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """Поиск по содержимому. ⚠️ ПУСТОЙ РЕЗУЛЬТАТ ОТВЕЧАЕТ СЛОВАМИ, а не `{"matches": []}`.

    🔴 Тот же класс, что уже чинился у пустого каталога: пустой JSON-массив модель читает
    как «этого в коде нет» и уверенно сообщает это человеку. Между тем причин три, и две из
    них поправимы своими силами: шаблон слишком узкий, искали не в том каталоге, а «правда
    нет» — лишь третья. Ответ обязан их различать, иначе поиск с опечаткой в имени функции
    выдаётся за доказательство отсутствия.

    ⚠️ Негодный шаблон сюда не попадает: сайдкар отвечает на него отказом (422), а не пустым
    результатом — иначе несостоявшийся поиск был бы неотличим от состоявшегося.
    """
    answer = await _op(ctx, raw, "files/grep", '{"pattern": "", "path": ""}')
    if isinstance(answer, ToolCallOutcome):
        return answer
    try:
        empty = not (json.loads(answer).get("matches") or [])
    except (ValueError, AttributeError):
        empty = False
    if empty:
        pattern = str(_args(raw).get("pattern") or "").strip()
        return (
            f"Совпадений не найдено по шаблону {pattern!r}. Это НЕ доказательство, что "
            "искомого в коде нет: проверь шаблон (короче, без точного регистра, без лишних "
            "слов) и каталог поиска. Убедись хотя бы одним успешным поиском, прежде чем "
            "сказать пользователю «такого здесь нет»."
        )
    return answer


async def ws_run_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    return await _op(ctx, raw, "exec", '{"command": ""}')


async def ws_history_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """История правок каталога. Пусто — правок не было ЛИБО истории нет вовсе.

    ⚠️ Разницу называем словами: пустой список модель прочитала бы как «ничего не
    менялось» и пообещала бы откат, которого не будет.
    """
    answer = await _op(ctx, raw, "history", "{}")
    if isinstance(answer, ToolCallOutcome):
        return answer
    try:
        empty = not (json.loads(answer).get("entries") or [])
    except (ValueError, AttributeError):
        empty = False
    if empty:
        return (
            "Снимков ещё нет: либо файлы не менялись, либо история в этом окружении "
            "недоступна. Не обещай пользователю откат, пока в списке нет ревизий."
        )
    return answer


async def ws_diff_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    return await _op(ctx, raw, "diff", '{"ref": "", "path": ""}')


async def ws_revert_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """Откат к ревизии. Требует ЯВНОЙ ревизии из `ws_history`, а не «как было».

    🔴 Откат без ревизии пришлось бы угадывать, а угаданный откат уничтожает работу,
    которую никто не просил отменять.
    """
    if not str(_args(raw).get("ref") or "").strip():
        return "Нужна ревизия из ws_history — без неё непонятно, к какому состоянию возвращать."
    return await _op(ctx, raw, "revert", '{"ref": "", "path": ""}')


async def ws_edit_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """Замена подстроки в файле: прочитать, заменить, записать.

    ⚠️ Составлен ЗДЕСЬ, а не отдельной ручкой сайдкара: три вызова вместо одного стоят
    дороже по времени, но не добавляют сервису с docker.sock ещё одной поверхности.

    🔴 Замена требует ЕДИНСТВЕННОГО вхождения. Иначе «замени X на Y» в файле с десятью X
    молча правит все десять — правка, которой никто не просил, и заметить её нечем.
    """
    args = _args(raw)
    path = str(args.get("path") or "")
    old = str(args.get("old") or "")
    new = str(args.get("new") or "")
    if not path or not old:
        return "Нужны путь и заменяемый фрагмент."
    ref = _ref(ctx)
    try:
        current = await call(ref, "files/read", {"path": path})
    except WorkspaceUnavailable as exc:
        return _failure(exc)
    content = str(current.get("content") or "")
    revision = str(current.get("revision") or "").strip()
    if not revision:
        return _failure(WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL))
    if current.get("truncated"):
        return "Файл прочитан не целиком — правка отменена, чтобы не потерять хвост."
    occurrences = content.count(old)
    if occurrences == 0:
        return "Такого фрагмента в файле нет — ничего не изменено."
    if occurrences > 1:
        return f"Фрагмент встречается {occurrences} раз — уточни его, правка отменена."
    try:
        await call(
            ref,
            "files/write",
            {
                "path": path,
                "content": content.replace(old, new, 1),
                "expected_revision": revision,
            },
        )
    except WorkspaceUnavailable as exc:
        return _failure(exc)
    return json.dumps({"path": path, "edited": True}, ensure_ascii=False)


async def ws_issues_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    """Read active workspace issues only through the explicit collaboration tool."""
    return await _op(ctx, raw, "collaboration/issues", "{}")


async def ws_issue_update_tool(ctx: RunContextWrapper, raw: str) -> str | ToolCallOutcome:
    args = _args(raw)
    issue_id = str(args.get("issue_id") or "").strip()
    status = str(args.get("status") or "").strip()
    if not issue_id or status not in {"open", "resolved", "stale"}:
        return "Нужны идентификатор issue и один из статусов: open, resolved, stale."
    payload = {"message": status}
    revision = str(args.get("revision") or "").strip()
    if revision:
        payload["ref"] = revision
    try:
        return json.dumps(
            await call(_ref(ctx), f"collaboration/issues/{issue_id}", payload), ensure_ascii=False
        )
    except WorkspaceUnavailable as exc:
        return _failure(exc)


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_PATH = {"type": "string", "description": "Путь внутри рабочего каталога."}

ws_list = FunctionTool(
    name="ws_list",
    description=(
        "Показать содержимое ТВОЕГО рабочего каталога: и то, что ты создал сам, и файлы "
        "пользователя — приложенный АРХИВ развёрнут здесь деревом, его исходники читаются "
        "`ws_read`. Текст обычного документа (pdf, docx, txt) сюда НЕ кладут: он уже в "
        "твоём контексте, и за ним ходить не нужно."
    ),
    params_json_schema=_schema({"path": _PATH}, []),
    on_invoke_tool=ws_list_tool,
)

ws_read = FunctionTool(
    name="ws_read",
    description=(
        "Прочитать файл из ТВОЕГО рабочего каталога: то, что ты сам туда положил, или "
        "исходник из развёрнутого архива пользователя. Для обычного документа (pdf, docx) "
        "инструмент НЕ нужен — его текст уже в контексте."
    ),
    params_json_schema=_schema({"path": _PATH}, ["path"]),
    on_invoke_tool=ws_read_tool,
)

ws_write = FunctionTool(
    name="ws_write",
    description=(
        "Записать файл в ТВОЙ рабочий каталог, чтобы отдать его пользователю результатом "
        "(существующий будет перезаписан целиком)."
    ),
    params_json_schema=_schema(
        {"path": _PATH, "content": {"type": "string", "description": "Новое содержимое."}},
        ["path", "content"],
    ),
    on_invoke_tool=ws_write_tool,
)

ws_edit = FunctionTool(
    name="ws_edit",
    description=(
        "Заменить фрагмент в файле ТВОЕГО рабочего каталога. Фрагмент должен встречаться "
        "ровно один раз, иначе правка отменяется."
    ),
    params_json_schema=_schema(
        {
            "path": _PATH,
            "old": {"type": "string", "description": "Заменяемый фрагмент, дословно."},
            "new": {"type": "string", "description": "Чем заменить."},
        },
        ["path", "old", "new"],
    ),
    on_invoke_tool=ws_edit_tool,
)

ws_grep = FunctionTool(
    name="ws_grep",
    description=(
        "Найти строки по шаблону в файлах ТВОЕГО рабочего каталога, а не в документах пользователя."
    ),
    params_json_schema=_schema(
        {"pattern": {"type": "string", "description": "Что искать."}, "path": _PATH},
        ["pattern"],
    ),
    on_invoke_tool=ws_grep_tool,
)

_REF = {"type": "string", "description": "Ревизия из ws_history (короткий хеш)."}

ws_history = FunctionTool(
    name="ws_history",
    description=(
        "Показать снимки ТВОЕГО рабочего каталога: что менялось и когда. Снимок делается "
        "после каждого хода, который что-то изменил."
    ),
    params_json_schema=_schema({}, []),
    on_invoke_tool=ws_history_tool,
)

ws_diff = FunctionTool(
    name="ws_diff",
    description=(
        "Показать, что изменилось в ТВОЁМ рабочем каталоге от снимка до текущего "
        "состояния. Без ревизии — изменения относительно последнего снимка."
    ),
    params_json_schema=_schema({"ref": _REF, "path": _PATH}, []),
    on_invoke_tool=ws_diff_tool,
)

ws_revert = FunctionTool(
    name="ws_revert",
    description=(
        "Вернуть файл ТВОЕГО рабочего каталога (или весь каталог, если путь не указан) "
        "к состоянию снимка. Ревизию бери из ws_history — угадывать нельзя."
    ),
    params_json_schema=_schema({"ref": _REF, "path": _PATH}, ["ref"]),
    on_invoke_tool=ws_revert_tool,
)

ws_issues = FunctionTool(
    name="ws_issues",
    description=(
        "Показать активные issues в ТВОЕЙ рабочей области: путь, диапазон строк, статус и "
        "текст задачи. Это единственный способ прочитать задачи пользователя."
    ),
    params_json_schema=_schema({}, []),
    on_invoke_tool=ws_issues_tool,
)

ws_issue_update = FunctionTool(
    name="ws_issue_update",
    description=(
        "Обновить статус существующей issue в ТВОЕЙ рабочей области после выполнения "
        "или уточнения задачи."
    ),
    params_json_schema=_schema(
        {
            "issue_id": {"type": "string", "description": "Идентификатор из ws_issues."},
            "status": {
                "type": "string",
                "description": "Новый статус issue.",
                "enum": ["open", "resolved", "stale"],
            },
            "revision": {"type": "string", "description": "Текущая revision, если она известна."},
        },
        ["issue_id", "status"],
    ),
    on_invoke_tool=ws_issue_update_tool,
)

ws_run = FunctionTool(
    name="ws_run",
    description=(
        "Выполнить команду в ТВОЁМ изолированном контейнере (без доступа в сеть). "
        "Вернёт код возврата, stdout и stderr."
    ),
    params_json_schema=_schema(
        {"command": {"type": "string", "description": "Команда для оболочки."}}, ["command"]
    ),
    on_invoke_tool=ws_run_tool,
)

WORKSPACE_TOOLS = [
    ws_list,
    ws_read,
    ws_write,
    ws_edit,
    ws_grep,
    ws_run,
    ws_history,
    ws_diff,
    ws_revert,
    ws_issues,
    ws_issue_update,
]

SPECS = build_workspace_specs(
    WORKSPACE_TOOLS,
    # Дифф читают целиком — по обрезанному диффу нельзя судить, что изменилось.
    result_limits={"ws_read": READ_RESULT_LIMIT, "ws_diff": READ_RESULT_LIMIT},
)
