#!/usr/bin/env python3
"""Офлайн-сверка контракта backend ↔ сайдкар. Гоняется в CI суперпроекта.

Зачем отдельно от `backend/tests/test_contract_parity_with_sidecar.py`: тот ходит по
HTTP в живой сайдкар и **пропускается**, если его нет. В юнит-CI сайдкара нет никогда,
значит гейтом он быть не может — «зелёный» там означал бы просто пропуск.

Здесь обе половины лежат на диске (checkout с `submodules: recursive`), поэтому сверка
делается импортом, без сети и без возможности пропуститься.

Сверяются ДВЕ НЕЗАВИСИМЫЕ КОПИИ: провод описан у провайдера (`agents/service`) и у
потребителя (`service/infrastructure/agents_client/contracts`). Общего класса нет —
он означал бы, что правка контракта требует согласованного релиза обоих сервисов.
Расхождение ловится здесь, в момент правки, а не деньгами в проде.

Запуск: python scripts/check_contract_parity.py
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
import sys

# Кириллица в выводе на Windows-консоли (cp1251) иначе роняет скрипт раньше проверок.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
# sys.path НЕ трогаем намеренно: оба пакета зовутся `service`, и добавление обоих
# каталогов дало бы победу одному — сверка сравнивала бы копию сама с собой и была
# бы зелена всегда. Модули грузятся по путям, см. `_load`.


def _fail(msg: str) -> None:
    print(f"РАСХОЖДЕНИЕ КОНТРАКТА: {msg}", file=sys.stderr)
    sys.exit(1)


def _compare(name: str, provider: set[str], consumer: set[str]) -> None:
    if provider == consumer:
        print(f"  ok  {name}: {len(provider)} имён")
        return
    only_provider = sorted(provider - consumer)
    only_consumer = sorted(consumer - provider)
    _fail(
        f"{name} — только у провайдера: {only_provider}; только у потребителя: {only_consumer}"
    )


def _load(alias: str, path: pathlib.Path):
    """Загрузить модуль ПО ПУТИ, а не по имени пакета.

    ⚠️ Иначе эта проверка невозможна в принципе. Обе половины провода лежат в пакетах
    с ОДНИМ именем — `service` у backend и `service` у сайдкара, — и обычный импорт
    подтянул бы одну и ту же копию дважды, сверив её саму с собой. Такая проверка
    зелена всегда и потому хуже отсутствующей.

    Работает это только потому, что все четыре модуля провода АВТОНОМНЫ: внутри
    ничего, кроме stdlib и pydantic. Появится у них внутренний импорт вида
    `from service.x import y` — он уедет не туда, и здесь понадобится настоящий
    загрузчик пакета, а не загрузка одного файла.
    """
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        _fail(f"не удалось загрузить {path}")
    module = importlib.util.module_from_spec(spec)
    # В sys.modules — чтобы pydantic смог разрешить аннотации при построении модели.
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _dict_literal_keys(path: pathlib.Path, name: str) -> set[str]:
    """Ключи словаря-литерала по имени переменной — через AST, без импорта модуля.

    ⚠️ Именно AST, а не импорт. `backend/service/settings.py` тянет за собой половину
    пакета `service`, а гейт обязан оставаться дешёвым: как только проверка начинает
    требовать установки зависимостей, её перестают ставить блокирующей. Ровно поэтому
    и `contracts.py` у обеих сторон написан на голом stdlib.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets or [None])[0]
        if not isinstance(target, ast.Name) or target.id != name or node.value is None:
            continue
        # Значение может быть как голым литералом, так и обёрткой вида
        # `Field(default_factory=lambda: {...})` — ищем первый словарь ВНУТРИ него.
        for inner in ast.walk(node.value):
            if isinstance(inner, ast.Dict):
                return {
                    k.value
                    for k in inner.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    _fail(f"не нашёл словарь {name} в {path}")
    return set()


def _string_args_of_call(root: pathlib.Path, *func_names: str) -> set[str]:
    """Первые строковые аргументы всех вызовов `func_name(...)` в дереве файлов.

    ⚠️ Имён НЕСКОЛЬКО не для красоты. Ключи overlay читаются не только напрямую через
    `runtime_settings.get_agents(...)`, но и через тонкие обёртки вроде
    `_agent_flag(name, default)`. Скан, знающий одно имя, объявил бы такие ключи
    «не читаемыми» — и я на этом уже ошибся, посчитав рабочие ручки мёртвыми.

    ⚠️ И ПОЗИЦИЯ КЛЮЧА РАЗНАЯ. У `get_agents` он первый, а у `_flag(config, name,
    default)` — ВТОРОЙ. Скан, смотревший только `args[0]`, объявил «ненайденными» все 14
    настроек бюджета контекста, хотя каждая читается через overlay. Поэтому берём первый
    строковый аргумент, но НЕ дальше второго: в третьем уже сидит дефолт, и строковый
    дефолт попал бы в набор «прочитанных ключей» как выдуманное имя.
    """
    wanted = set(func_names)
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        sequences = _module_string_sequences(tree)
        loop_sources = _loop_variable_sources(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            attr = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if attr not in wanted:
                continue
            for arg in node.args[:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
                    break
                if isinstance(arg, ast.JoinedStr):
                    found |= _expand_fstring_key(arg, sequences, loop_sources, path)
                    break
    return found


def _module_string_sequences(tree: ast.Module) -> dict[str, list[str]]:
    """Модульные константы вида ``X = ("a", "b")`` — только полностью строковые."""
    out: dict[str, list[str]] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if not isinstance(target, ast.Name) or not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        items = [
            e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if items and len(items) == len(node.value.elts):
            out[target.id] = items
    return out


def _loop_variable_sources(tree: ast.Module) -> dict[str, str]:
    """``for name in SEQ`` и ``... for name in SEQ`` → {name: "SEQ"}."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        pairs = []
        if isinstance(node, (ast.For, ast.AsyncFor)):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, ast.comprehension):
            pairs = [(node.target, node.iter)]
        for target, iterable in pairs:
            if isinstance(target, ast.Name) and isinstance(iterable, ast.Name):
                out[target.id] = iterable.id
    return out


def _expand_fstring_key(
    node: ast.JoinedStr,
    sequences: dict[str, list[str]],
    loop_sources: dict[str, str],
    path: pathlib.Path,
) -> set[str]:
    """Развернуть ключ, собранный f-строкой, во все его возможные значения.

    ⚠️ ЭТО БЫЛО СЛЕПЫМ ПЯТНОМ, И ОНО УЖЕ СРАБОТАЛО. Веса бюджета контекста читаются как
    ``_flag(config, f"context_budget_{name}", 0.0)`` в цикле по ``SECTION_PRIORITY``.
    Скан искал строковые литералы, f-строку не видел — и семь ключей просто не попадали
    в набор «читаемых». Один из них (``context_budget_knowledge``) в админ-реестре так и
    не был объявлен: тумблера у секции базы знаний не существовало, а страж молчал,
    потому что и про сам ключ не знал.

    Разворачиваем только честно разрешимый случай: подстановка — имя переменной цикла,
    цикл идёт по модульной константе-кортежу строк. Всё остальное — ЯВНЫЙ ОТКАЗ, а не
    тихий пропуск: слепое пятно, о котором страж молчит, хуже отсутствующего стража.
    """
    prefix_parts: list[str] = []
    names: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            prefix_parts.append(part.value)
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            names.append(part.value.id)
        else:
            _fail(f"{path.name}: ключ overlay собран выражением, которое скан не разбирает")

    if len(names) != 1:
        _fail(f"{path.name}: ключ overlay собран из {len(names)} подстановок — скан ждёт одну")

    source = loop_sources.get(names[0])
    values = sequences.get(source or "")
    if not values:
        _fail(
            f"{path.name}: ключ overlay собран из '{names[0]}', но чем оно пробегает — "
            "скан не видит (ожидалась модульная константа-кортеж строк)"
        )

    prefix = "".join(prefix_parts)
    return {f"{prefix}{value}" for value in values}


# Функции, через которые читается admin-overlay. ⚠️ Их ЧЕТЫРЕ, и это не избыточность:
# `get_agents` — прямой вызов, `_agent_flag(name, default)` — обёртка в processor,
# `_flag(config, name, default)` — обёртка в context_budget, где ключ ВТОРЫМ аргументом,
# `_csv_flag(name, default)` — обёртка над `_agent_flag` для настроек-списков.
# Пропусти любую — и её ключи выглядят «нечитаемыми»; на этом я уже ошибался трижды.
_OVERLAY_READERS = ("get_agents", "_agent_flag", "_flag", "_csv_flag")


def _check_billable_tools(billable: frozenset[str]) -> None:
    """Имена инструментов у провайдера и цены у потребителя — один список.

    ⚠️ Расхождение здесь не падает НИГДЕ. Backend ищет цену через
    `surcharge_map.get(tool)`: переименованный инструмент даёт `None`, надбавка молча
    перестаёт начисляться, прогон при этом успешен. Обнаружить это можно только по
    выручке.
    """
    priced = _dict_literal_keys(ROOT / "backend" / "service" / "settings.py", "tool_surcharge_rub")
    _compare("billable_tools", set(billable), priced)


_CONSUMER_BILLING_TEST = (
    ROOT / "backend" / "tests" / "test_contract_parity_with_sidecar.py",
    "_BILLING_RESULT_KEYS",
)


def _consumer_billing_keys() -> set[str]:
    """Поля result-dict, по которым воркер СЧИТАЕТ ДЕНЬГИ, — из списка ПОТРЕБИТЕЛЯ.

    ⚠️ ЧИТАЕМ, А НЕ ДУБЛИРУЕМ. Раньше набор был переписан сюда руками и отстал: здесь
    сторожилось 5 полей, а потребитель читал 8 — `metadata` (весь surcharge/complexity
    путь: model_routing, agent_type, steps, артефакты), `resolved_model` (база потолка
    цены при подмене модели) и `reply` оставались в слепой зоне. Выкинь их сайдкар из
    `RESULT_FIELDS` — гейт зелёный, тарификация молча сломана.

    Особенно неприятно это здесь: ЭТОТ офлайн-гейт создан ЗАМЕНИТЬ HTTP-тест, который
    в юнит-CI скипается без поднятого сайдкара. Замена, стерегущая меньше оригинала, —
    худший вид гейта: он создаёт уверенность, которой не обеспечивает. Поэтому источник
    истины один, и расхождение теперь невозможно конструктивно.
    """
    path, var = _CONSUMER_BILLING_TEST
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except OSError:
        _fail(f"не нашёл ожидания потребителя ({var}) — {path} недоступен")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if var not in names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            # frozenset({...}) — literal_eval не разворачивает вызов, берём аргумент.
            call = node.value
            if not isinstance(call, ast.Call) or not call.args:
                break
            value = ast.literal_eval(call.args[0])
        keys = {str(k) for k in value}
        if not keys:
            _fail(f"{var} у потребителя пуст — денежные поля не стерегутся")
        return keys
    _fail(f"не нашёл {var} в {path.name} — гейт денежных полей ослеп")
    raise AssertionError("unreachable")  # _fail завершает процесс


def _check_admin_settings_keys() -> None:
    """Каждый ключ, который сайдкар ЧИТАЕТ, должен быть объявлен в админ-реестре.

    ⚠️ Сопоставление идёт по СТРОКАМ: сайдкар зовёт `get_agents("duckdb_enabled", …)`,
    а backend объявляет `"agents.duckdb_enabled"` в `settings_registry`. Опечатка с
    любой стороны означает, что тумблер в админке перестаёт действовать: значение
    просто не попадает в снимок, и поведение молча откатывается на дефолт конфига.
    Ни ошибки, ни записи в логе — админ жмёт переключатель, а ничего не меняется.

    Проверяем в одну сторону: ЧИТАЕМОЕ ⊆ ОБЪЯВЛЕННОГО. Обратное (объявлено, но не
    читается) — не поломка, а «ручка на будущее»: реестр сам это допускает
    (см. комментарий про отложенные флаги), поэтому здесь только предупреждаем.
    """
    registry = ROOT / "backend" / "service" / "services" / "admin" / "application"
    declared_raw = _string_args_of_call(registry, "_s")
    declared = {k.split("agents.", 1)[1] for k in declared_raw if k.startswith("agents.")}
    if not declared:
        _fail("не нашёл объявленных ключей agents.* в реестре настроек админки")

    read = _string_args_of_call(ROOT / "agents" / "service", *_OVERLAY_READERS)
    unknown = sorted(read - declared)
    if unknown:
        _fail(
            "сайдкар читает ключи, которых НЕТ в админ-реестре (тумблер не будет "
            f"действовать): {unknown}"
        )
    print(f"  ok  ключи agents.*: читается {len(read)}, объявлено {len(declared)}")

    _check_knobs_actually_apply(declared)


# ⚠️ ХРАПОВИК, А НЕ ЦЕЛЬ. Ключи ниже объявлены в админке, но читаются НЕ через overlay
# — значит тумблер не действует: админ меняет значение, оно сохраняется, поведение
# прежнее. Их не «14 непонятных»: столько ключей вообще не нашлось поиском по строке,
# и они разбираются отдельно (часть читается backend'ом под другими именами).
#
# Список — снимок долга на момент введения проверки. Новые сюда добавлять НЕЛЬЗЯ:
# смысл храповика в том, чтобы мёртвых ручек не становилось больше. Чинится каждая
# одинаково — `config.agents.X` → `runtime_settings.get_agents("X", config.agents.X)`.
_KNOBS_NOT_APPLIED_BASELINE: frozenset[str] = frozenset()


def _check_knobs_actually_apply(declared: set[str]) -> None:
    """Объявленный ключ должен читаться ЧЕРЕЗ overlay, иначе тумблер декоративный.

    Обратная сторона предыдущей проверки. Та ловит «читаем то, чего нет в админке»;
    эта — «в админке есть, а на поведение не влияет». Второе безобиднее на вид и
    неприятнее на практике: интерфейс показывает работающую настройку.

    ⚠️ Метод грубый — ищем `config.agents.<ключ>` текстом. Он не отличит чтение внутри
    функции, которая сама сидит за overlay, поэтому проверка НЕ падает на всём подряд,
    а сверяется с базовым списком известного долга.
    """
    readers = _string_args_of_call(ROOT / "agents" / "service", *_OVERLAY_READERS)
    readers |= _string_args_of_call(ROOT / "backend" / "service", *_OVERLAY_READERS)

    sources: list[str] = []
    for area in ("agents", "backend"):
        for path in (ROOT / area / "service").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            sources.append(path.read_text(encoding="utf-8", errors="ignore"))
    blob = "\n".join(sources)

    dead = {
        key
        for key in declared - readers
        if re.search(rf"config\.agents\.{re.escape(key)}\b", blob)
    }
    new_dead = sorted(dead - _KNOBS_NOT_APPLIED_BASELINE)
    if new_dead:
        _fail(
            "тумблер админки не будет действовать — ключ читается в обход overlay: "
            f"{new_dead}. Почини: config.agents.X → runtime_settings.get_agents('X', ...)"
        )
    healed = sorted(_KNOBS_NOT_APPLIED_BASELINE - dead)
    if healed:
        _fail(f"долг починен — убери из _KNOBS_NOT_APPLIED_BASELINE: {healed}")
    print(f"  ok  тумблеры админки действуют (в обход overlay: {len(dead)})")


def main() -> None:
    # Провайдер: сайдкар владеет проводом, он его и публикует.
    provider_root = ROOT / "agents" / "service"
    _p_contracts = _load("_p_contracts", provider_root / "contracts.py")
    RESULT_FIELDS = _p_contracts.RESULT_FIELDS
    ROUTE_RESPONSE_FIELDS = _p_contracts.ROUTE_RESPONSE_FIELDS
    BILLABLE_TOOLS = _p_contracts.BILLABLE_TOOLS
    ProviderServiceKinds = _p_contracts.SERVICE_USAGE_KINDS
    ProviderEvents = _load("_p_events", provider_root / "events.py").EventType
    _p_run = _load("_p_run", provider_root / "schemas" / "run.py")
    ProviderAmbient, ProviderRun = _p_run.AMBIENT_FIELDS, _p_run.AgentRunInput

    # Потребитель: своя копия того же провода в клиенте сайдкара.
    consumer_root = ROOT / "backend" / "service" / "infrastructure" / "agents_client" / "contracts"
    ConsumerEvents = _load("_c_events", consumer_root / "events.py").EventType
    _c_run = _load("_c_run", consumer_root / "run.py")
    ConsumerAmbient, ConsumerRun = _c_run.AMBIENT_FIELDS, _c_run.AgentRunInput
    ConsumerServiceKinds = _load(
        "_c_usage_kinds", consumer_root / "usage_kinds.py"
    ).SERVICE_USAGE_KINDS

    print("Сверка контракта (офлайн, без сети):")

    _compare("run_input_fields", set(ProviderRun.model_fields), set(ConsumerRun.model_fields))
    _compare(
        "event_types",
        {e.value for e in ProviderEvents},
        {e.value for e in ConsumerEvents},
    )
    _compare("ambient_fields", set(ProviderAmbient), set(ConsumerAmbient))
    # Служебные виды вызовов: по ним воркер решает, показывать ли «замена модели».
    # Разъедься набор — и бейдж снова начнёт врать (или спрячет настоящий фейловер),
    # причём молча: ошибок не будет ни на одной стороне.
    _compare("service_usage_kinds", set(ProviderServiceKinds), set(ConsumerServiceKinds))

    # AMBIENT_FIELDS обязаны быть ПОДМНОЖЕСТВОМ полей тела: они едут в запросе, но
    # исключаются из аргументов execute(). Разъедется — либо попадут в kwargs и уронят
    # каждый прогон, либо потеряются, и политика провайдеров перестанет применяться.
    ambient_extra = set(ProviderAmbient) - set(ProviderRun.model_fields)
    if ambient_extra:
        _fail(f"ambient_fields не входят в тело /run: {sorted(ambient_extra)}")
    print(f"  ok  ambient_fields входят в run_input_fields ({len(ProviderAmbient)} имён)")

    # Поля result-dict, из которых воркер СПИСЫВАЕТ ДЕНЬГИ. Набор НЕ дублируем — ЧИТАЕМ
    # у самого потребителя (`_BILLING_RESULT_KEYS`), см. `_consumer_billing_keys`.
    billing = _consumer_billing_keys()
    missing = sorted(billing - set(RESULT_FIELDS))
    if missing:
        _fail(f"провайдер не отдаёт поля, по которым воркер биллит: {missing}")
    print(f"  ok  result_fields покрывают денежные поля ({len(billing)} из {len(RESULT_FIELDS)})")

    # `routing_usage` тарифицируется ОТДЕЛЬНЫМ событием (токены роутер-ЛЛМ), а
    # `selected_model` уходит в резерв кредитов. До сих пор это проверял только
    # HTTP-тест, который в CI не выполняется НИКОГДА (скипается без живого сайдкара) —
    # то есть роутер мог начать работать бесплатно, и узнали бы мы об этом по счёту.
    route_billing = {"selected_model", "routing_usage"}
    missing_route = sorted(route_billing - set(ROUTE_RESPONSE_FIELDS))
    if missing_route:
        _fail(f"провайдер не отдаёт поля /route, по которым воркер биллит: {missing_route}")
    print(f"  ok  route_response_fields покрывают денежные поля ({len(ROUTE_RESPONSE_FIELDS)})")

    _check_billable_tools(BILLABLE_TOOLS)
    _check_admin_settings_keys()

    print("Контракт согласован.")


if __name__ == "__main__":
    main()
