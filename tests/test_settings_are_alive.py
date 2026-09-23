"""Объявленная настройка ЧТО-ТО ДЕЛАЕТ — и делает это через overlay админки.

⚠️ Два разных способа соврать пользователю, и оба здесь уже случались.

**Настройка не читается вовсе.** `synthesis_max_tokens` был объявлен в обоих сервисах,
задан во всех трёх env-файлах (в проде 1200), доезжал параметром до `execute_steps` — и
в теле не читался ни разу. `run_timeout_sec` не читался нигде, и у прогона не было общего
дедлайна. `token_budget_enabled` обещал kill-switch на legacy-обрезку по символам,
которой не существует, и был при этом ТУМБЛЕРОМ В АДМИНКЕ: админ его видел, переключал,
и не происходило ничего.

**Настройка читается мимо overlay.** Тогда она работает, но её нельзя изменить из панели:
значение берётся из конфига процесса, а слепок админки игнорируется. Так было у потолка
синтеза и у ОСНОВНОГО эмбеддера — при том что запасные эмбеддеры строкой ниже читались
через overlay, то есть половина одной настройки слушалась админа, а половина нет.

## Почему страж списочный, а не поимённый

Поимённые тесты покрывают то, о чём вспомнили. Здесь перебирается ВЕСЬ `AgentsConfig`, и
новое поле обязано либо читаться, либо быть явно заявлено чужим — молча отрасти список
мёртвых настроек больше не может.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from service.settings import AgentsConfig

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SERVICE = _ROOT / "service"

# Поля, принадлежащие BACKEND'у. Живут здесь только потому, что `AgentsConfig` имеет
# `extra="forbid"`: переменные `AGENTS__*` заданы в окружении обоих сервисов, и
# незаявленная здесь уронила бы СТАРТ сайдкара.
#
# ⚠️ Добавлять сюда можно ТОЛЬКО проверив, что поле действительно читает сосед. Это не
# «список исключений», а список чужой собственности: превратится в свалку — страж умрёт.
_OWNED_BY_BACKEND = {
    # компактизация истории: compact_context_use_case, chat_worker_tasks
    "history_summary_enabled",
    "summary_trigger_messages",
    "summary_max_tokens",
    # загрузка и разбор вложений, транскрипция, индексация репозитория
    "graph_index_enabled",
    "upload_max_bytes",
    "opendataloader_max_bytes",
    # ⚠️ Читает `upload_file_use_case` бэкенда. Здесь страж считал поле живым только
    # потому, что имя УПОМИНАЛОСЬ в комментарии `contracts.py` — скан не отличает
    # упоминание от чтения. Комментарий убрали при чистке, и подмена вскрылась.
    "attachment_text_max_chars",
    "graphify_model",
    "graphify_max_bytes",
    "graphify_timeout_sec",
    "mem0_api_key",
    "memos_base_url",
    "memos_timeout_sec",
    "sidecar_url",
    "sidecar_timeout_sec",
    "doc_vector_top_k",
    "vector_search_enabled",
    "deep_research_provider",
    "ldr_model",
    "ldr_strategy",
    "ldr_search_engines",
    "ldr_iterations",
    "ldr_timeout_sec",
    "ldr_poll_interval_sec",
    "ldr_base_url",
    "ldr_username",
    "ldr_password",
    "graph_index_price_rub_per_doc",
    "mem0_app_id",
    "memory_provider",
    "memos_api_key",
    "memos_async_mode",
    "memos_embedder_dim",
    "memos_embedder_fallback",
    "memos_embedder_model",
    "memos_mem_cube_id",
    "repo_allowed_hosts",
    "repo_fetch_timeout_sec",
    "repo_max_bytes",
    "whisper_default_model",
    "whisper_enabled",
    "whisper_language",
    "whisper_model_multipliers",
    "whisper_price_rub_per_min",
    "whisper_timeout_sec",
    "whisper_url",
}


# Поля БЕЗ ПОВЕДЕНИЯ, оставленные ради старта. Читать их не должен никто; существуют
# только потому, что `.env.prod`/`.env.dev` лежат в `.gitignore` — правка окружения не
# уезжает вместе с кодом, и на хосте, где переменная ещё объявлена, `extra="forbid"` не
# даст сервису стартовать.
#
# ⚠️ Это НЕ склад для неудобных настроек. Каждая строка отсюда исчезает, как только
# переменная вычищена на всех хостах; пока список непустой, он висит напоминанием.
_DEPRECATED_ACCEPTED = {
    "token_budget_enabled",
    "max_context_chars",
    "plan_step_execution_enabled",
}


def test_deprecated_list_stays_short():
    """Напоминание, а не свалка: список не должен разрастаться."""
    assert len(_DEPRECATED_ACCEPTED) <= 3, (
        "поля без поведения копятся — вычистите переменные на хостах и снесите поля"
    )


def _source() -> str:
    """Весь код сервиса одной строкой — по нему ищем чтения."""
    return "\n".join(
        p.read_text(encoding="utf-8") for p in _SERVICE.rglob("*.py") if p.name != "settings.py"
    )


_SRC = _source()
_FIELDS = sorted(AgentsConfig.model_fields)


# Семейства, читаемые ДИНАМИЧЕСКИ: имя собирается в рантайме (`f"context_budget_{name}"`
# в `context_budget.py`), поэтому поиска по подстроке точного имени недостаточно.
# ⚠️ Проверяем, что сам ПРЕФИКС в коде есть: иначе исключение переживёт удаление
# механизма и разрешит мёртвые поля.
_DYNAMIC_PREFIXES = ("context_budget_",)


def _read_dynamically(field: str) -> bool:
    return any(field.startswith(p) and p in _SRC for p in _DYNAMIC_PREFIXES)


@pytest.mark.parametrize("field", _FIELDS)
def test_setting_is_read_somewhere(field):
    """Поле либо читается сайдкаром, либо явно заявлено принадлежащим backend'у."""
    if field in _OWNED_BY_BACKEND or field in _DEPRECATED_ACCEPTED or _read_dynamically(field):
        return
    assert field in _SRC, (
        f"'{field}' объявлено в AgentsConfig и не читается НИГДЕ в service/. "
        "Либо реализуйте поведение, либо снесите поле (сначала из env — иначе "
        "extra=forbid уронит СТАРТ), либо внесите в _OWNED_BY_BACKEND, ПРОВЕРИВ, "
        "что его читает сосед."
    )


def test_backend_owned_list_has_no_stale_entries():
    """⚠️ Список чужой собственности не должен переживать сами поля.

    Иначе он превращается в кладбище: имена, которых уже нет, тихо «разрешают»
    несуществующее, и страж перестаёт что-либо значить.
    """
    stale = sorted(_OWNED_BY_BACKEND - set(AgentsConfig.model_fields))
    assert not stale, f"в _OWNED_BY_BACKEND есть поля, которых уже нет в конфиге: {stale}"


def _direct_config_reads() -> list[tuple[str, int, str]]:
    """`config.agents.<поле>` в коде — кандидаты на чтение мимо overlay."""
    found: list[tuple[str, int, str]] = []
    for path in _SERVICE.rglob("*.py"):
        if path.name == "settings.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value
            if (
                isinstance(owner, ast.Attribute)
                and owner.attr == "agents"
                and isinstance(owner.value, ast.Name)
                and owner.value.id in ("config", "_config")
            ):
                found.append((str(path.relative_to(_ROOT)), node.lineno, node.attr))
    return found


def _overlay_fields() -> set[str]:
    """Поля, которые ХОТЬ ГДЕ-ТО читаются через overlay админки."""
    fields: set[str] = set()
    for node in ast.walk(ast.parse(_SRC)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("get_agents", "_agent_flag"):
            pass
        elif isinstance(func, ast.Name) and func.id == "_agent_flag":
            pass
        else:
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            fields.add(str(node.args[0].value))
    return fields


def _mixed_read_fields() -> list[str]:
    """Поля, читаемые И через overlay, И напрямую из конфига — в РАЗНЫХ местах.

    Прямое чтение рядом с overlay-чтением в одном выражении
    (`get_agents("x", config.agents.x)`) — норма: это дефолт. А вот когда одно место
    слушает админа, а другое берёт значение из конфига само — настройка работает
    наполовину, и какая половина сработает, зависит от того, чей код исполнится.
    """
    overlay = _overlay_fields()
    direct: dict[str, list[str]] = {}
    for path in _SERVICE.rglob("*.py"):
        if path.name == "settings.py":
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Строки, где overlay-чтение и прямое стоят вместе — это дефолт, не расхождение.
        overlay_lines = {
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Attribute) and n.func.attr in ("get_agents", "_agent_flag"))
                or (isinstance(n.func, ast.Name) and n.func.id == "_agent_flag")
            )
        }
        # ⚠️ Форма `аргумент if аргумент is not None else config.agents.X` — это тоже
        # РАЗРЕШЕНИЕ ДЕФОЛТА, просто разнесённое по файлам: значение приходит от
        # вызывающего, который уже сходил в overlay. Так устроен клиент LDR
        # (`_resolve_ldr_settings`: per-user → overlay → config), и без этой поправки
        # страж давал пять ложных срабатываний — а страж с ложными срабатываниями
        # обрастает исключениями и умирает.
        default_lines = {
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.IfExp)
            and isinstance(n.test, ast.Compare)
            and any(isinstance(op, ast.IsNot) for op in n.test.ops)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value
            if (
                isinstance(owner, ast.Attribute)
                and owner.attr == "agents"
                and isinstance(owner.value, ast.Name)
                and owner.value.id in ("config", "_config")
                and node.attr in overlay
                and not any(abs(node.lineno - ln) <= 3 for ln in overlay_lines)
                and not any(abs(node.lineno - ln) <= 2 for ln in default_lines)
            ):
                direct.setdefault(node.attr, []).append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return sorted(f"{field} ({', '.join(places)})" for field, places in direct.items())


def test_no_setting_is_half_managed_by_the_admin_panel():
    """⚠️ Настройка не должна слушаться админки НАПОЛОВИНУ.

    Ровно это уже случалось дважды. Потолок синтеза мульти-интента читался из конфига,
    хотя соседние флаги в том же файле — через overlay. У эмбеддера было ещё нагляднее:
    ЗАПАСНЫЕ эмбеддеры читались через overlay, а ОСНОВНОЙ — напрямую, так что админ мог
    менять фолбэки и не мог основной. Ошибок при этом нет нигде: значение просто берётся
    из конфига процесса и меняется только рестартом.

    Страж намеренно узкий. Проверять «всё читается через overlay» бессмысленно: адреса
    сервисов, ключи и параметры TLS резолвятся при построении клиентов, когда слепка
    админ-настроек ещё нет. Здесь ловится именно РАСХОЖДЕНИЕ — поле, которое где-то уже
    признано управляемым, но в другом месте читается мимо.
    """
    mixed = _mixed_read_fields()
    assert not mixed, (
        "настройка читается и через overlay админки, и напрямую из конфига — "
        "тумблер подействует не везде:\n  " + "\n  ".join(mixed)
    )


# Настройки, которые админ меняет из панели, и это ОБЯЗАНО действовать без рестарта.
# Список короткий и явный намеренно: каждое имя сюда попало после того, как чтение мимо
# overlay было найдено в проде.
_ADMIN_TUNABLE = (
    "subtask_synthesis_max_tokens",  # потолок синтеза мульти-интента
    "doc_embedder_model",  # основной эмбеддер (фолбэки читались через overlay, он — нет)
    "doc_embedder_dim",
    "run_timeout_sec",  # общий дедлайн прогона
)


@pytest.mark.parametrize("field", _ADMIN_TUNABLE)
def test_admin_tunable_setting_is_read_through_the_overlay(field):
    """⚠️ ОТДЕЛЬНО ОТ СТРАЖА ВЫШЕ, И ВОТ ПОЧЕМУ.

    `test_no_setting_is_half_managed_by_the_admin_panel` ловит РАСХОЖДЕНИЕ: поле
    читается и через overlay, и мимо. Но если убрать ЕДИНСТВЕННОЕ overlay-чтение,
    расхождения не станет — поле просто выпадет из его поля зрения, и страж промолчит.
    Проверено мутацией: возврат `synthesis_max_tokens` к прямому чтению из конфига тот
    страж не заметил.

    Поэтому здесь — поимённо. Список короткий и растёт только по факту найденного бага,
    иначе он превратится в копию реестра админки, живущую отдельной жизнью.
    """
    assert field in _overlay_fields(), (
        f"'{field}' не читается через runtime_settings ни разу — тумблер в админке "
        "не подействует, и ошибок при этом не будет нигде"
    )
