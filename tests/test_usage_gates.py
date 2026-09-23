"""Гейты usage: что доезжает до счёта, а что молча исчезает.

## Как устроена цена (проверено чтением backend'а, а не по памяти)

`backend/.../pricing_service.py:87-102` считает цену ТОЛЬКО из `per_call_usage`, беря из
каждой записи `prompt` и `completion` по отдельности. Поле `total` в цене не участвует
нигде. `chat_worker_tasks.py:668` добавляет спасательный круг: если `total_tokens <= 0`
(то есть usage не пришёл вовсе) и ответ отдан — списывается резерв-флор.

Отсюда точная модель потери, и она у́же, чем кажется:

* usage не пришёл НИ ОТ ОДНОГО вызова → резерв-флор, запрос НЕ бесплатен;
* usage от части вызовов пришёл → `total_tokens > 0`, флор не включается, и **каждый
  вызов, не попавший в `per_call_usage`, достаётся даром**;
* usage вида `{prompt: 0, completion: 0, total: N}` не тарифицируется в любом случае —
  цена считается из prompt/completion, и запись с нулями дала бы ровно ноль.

Последний пункт важен как ОТРИЦАТЕЛЬНЫЙ результат: «total-only отбрасывается» само по
себе деньгами не является, сколько бы мест его ни отбрасывало. Тесты ниже это фиксируют,
чтобы за призраком не гонялись повторно.

## Что здесь ловится по-настоящему

⚠️ `accumulate_usage` (`usage_tracking.py:94`) складывает `total` НАПРЯМУЮ из
`total_tokens` провайдера, без фолбэка на `prompt + completion`. Провайдер, заполнивший
`prompt_tokens`/`completion_tokens`, но не `total_tokens`, оставляет `total` нулём — при
полностью тарифицируемом вызове.

И ровно по этому нулю `/route` решает, учитывать ли роутинг:
`model_routing_service.py:82` — `if routing_usage.get("total")`,
а `/run` для ТОГО ЖЕ вызова смотрит на другое:
`agent_execution_service.py:84` — `if routing_usage.get("prompt") or ...("completion")`.

Два пути одного вызова разошлись в противоположные стороны. Один из них неправ при любом
ответе провайдера — вопрос только, при каком именно.

⚠️ Почему это не поймали 803 теста: все денежные фикстуры репозитория строят ответ как
`total_tokens=prompt + completion` (см. `test_meta_call_billing.py:21`). Провайдер, не
заполняющий `total_tokens`, не встречается в тестах ни разу.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.application.reply_assembler import ReplyAssembler
from service.domain.legacy_usage import accumulate_usage
from service.domain.usage_tracking import build_token_usage_meta, is_billable


def _resp(*, prompt=40, completion=15, total=None):
    """Ответ провайдера. ``total=None`` — провайдер НЕ заполнил `total_tokens`."""
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
    )


def _price(per_call_usage) -> int:
    """Модель тарификации backend'а: сумма prompt+completion по записям.

    Не копия формулы (там ещё цены моделей и надбавки), а ответ на один вопрос: сколько
    токенов вообще ДОЙДЁТ до тарификатора. Ноль означает, что вызов бесплатен.
    """
    return sum(
        int(c.get("prompt", 0) or 0) + int(c.get("completion", 0) or 0) for c in per_call_usage
    )


# --------------------------------------------------------------------------- #
# accumulate_usage: total без фолбэка                                           #
# --------------------------------------------------------------------------- #
def test_total_is_filled_when_provider_reports_it():
    acc: dict = {}
    accumulate_usage(acc, _resp(prompt=40, completion=15, total=55), "m")

    assert {key: acc[key] for key in ("prompt", "completion", "total", "model")} == {
        "prompt": 40,
        "completion": 15,
        "total": 55,
        "model": "m",
    }
    assert len(acc["calls"]) == 1


def test_total_falls_back_to_the_sum_when_provider_omits_it():
    """⚠️ Провайдер не заполнил `total_tokens`, но вызов полностью тарифицируем.

    Без фолбэка `total` остаётся нулём — и по этому нулю `/route` выбрасывает usage
    целиком (см. следующий блок). Сам вызов при этом стоил денег и имеет и prompt, и
    completion.
    """
    acc: dict = {}
    accumulate_usage(acc, _resp(prompt=40, completion=15, total=None), "m")

    assert acc["prompt"] == 40
    assert acc["completion"] == 15
    assert acc["total"] == 55, (
        f"total={acc['total']} — провайдер не заполнил total_tokens, фолбэка на сумму нет"
    )


# --------------------------------------------------------------------------- #
# Гейт ровно один                                                               #
# --------------------------------------------------------------------------- #
# ⚠️ ЗДЕСЬ СТОЯЛИ ДВЕ ФУНКЦИИ-КОПИИ прод-условий (`usage.get("total")` для `/route` и
# `prompt or completion` для `/run`), и тест сравнивал их между собой. Как
# характеризация это работало: копии расходились ровно так же, как оригиналы. Но после
# починки прода тест продолжал падать — он воспроизводил правило вместо того, чтобы его
# ВЫЗЫВАТЬ, и о правке кода не знал ничего.
#
# Урок общий: тест, дублирующий проверяемое условие, проверяет свою копию. Поэтому ниже
# — структурный страж на инвариант «решение принимается в одном месте», а поведение
# проверяется вызовом самого канона.
def _usage_keys_read_by(test_node) -> set[str]:
    """Какие ключи usage читает выражение-условие: разбор по УЗЛАМ, не по тексту.

    ⚠️ Третья попытка написать эту проверку, и предыдущая тоже была фальшивой:
    сравнение шло с `ast.unparse(node.test)`, а `unparse` НОРМАЛИЗУЕТ кавычки в
    одинарные — искомое `.get("total")` в его выводе не встречается никогда. Страж
    молча не находил ничего и был зелёным на любом коде.

    Поэтому здесь ищется структура: вызов `<что-то>.get(<строковая константа>)`, где
    объект по имени похож на usage. Кавычки, переносы строк и форма условия на это не
    влияют вовсе.
    """
    import ast

    keys: set[str] = set()
    for node in ast.walk(test_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        key = node.args[0].value
        if key not in ("prompt", "completion", "total"):
            continue
        owner = func.value
        name = getattr(owner, "id", None) or getattr(owner, "attr", "")
        if "usage" in str(name).lower():
            keys.add(key)
    return keys


def _looks_like_a_billing_gate(test_node) -> bool:
    """Условие РЕШАЕТ «тарифицируемо ли», а не достаёт значение."""
    keys = _usage_keys_read_by(test_node)
    return {"prompt", "completion"}.issubset(keys) or "total" in keys


def test_nobody_reimplements_the_billing_gate():
    """Ни один потребитель не решает «тарифицируемо ли» сам.

    Копия условия — это не дублирование стиля, а вторая точка правды: именно так
    `/route` и `/run` разошлись в противоположные стороны для одного и того же вызова
    `route_model`, и заметить это было нечем — оба пути «работали».

    ⚠️ ОБХОД ПО AST, А НЕ ПО ТЕКСТУ СТРОК. Две предыдущие версии этого стража были
    фальшивыми, и обе поймала мутация, а не прогон:

    1. `.get("prompt") or` в любой строке — указывало на `int(x.get("prompt") or 0)`,
       где `or` это дефолт. Ложное срабатывание; страж с такими быстро обрастает
       исключениями и перестаёт значить что-либо.
    2. Сужение «строка начинается с `if`» — пропускало ТЕРНАРНИК, а именно им и был
       записан разошедшийся гейт `/route`:
       `routing_usage=dict(...) if routing_usage.get("total") else {}`.
       То есть страж не ловил ровно тот случай, ради которого написан: мутация
       «вернуть гейт по total» оставалась зелёной.

    AST снимает обе проблемы разом: смотрим ТОЛЬКО на выражение-условие (`ast.If.test`
    и `ast.IfExp.test`), в какой бы синтаксической форме оно ни было записано, а
    извлечение значений в тела условий не попадает вовсе.
    """
    import ast
    import pathlib

    offenders = []
    root = pathlib.Path(__file__).resolve().parent.parent / "service"
    for path in root.rglob("*.py"):
        if path.name == "usage_tracking.py":  # дом самого канона
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp)):
                continue
            if _looks_like_a_billing_gate(node.test):
                offenders.append(
                    f"{path.relative_to(root)}:{node.lineno}: {ast.unparse(node.test)}"
                )

    assert not offenders, "гейт биллинга продублирован вне is_billable:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    ("usage", "billable", "why"),
    [
        ({"prompt": 40, "completion": 15, "total": 0}, True, "провайдер не заполнил total"),
        ({"prompt": 0, "completion": 0, "total": 55}, False, "разбивки нет — цена ноль"),
        ({"prompt": 40, "completion": 0, "total": 40}, True, "только prompt тоже деньги"),
        ({}, False, "пусто"),
        (None, False, "не словарь"),
    ],
    ids=["без-total", "только-total", "только-prompt", "пусто", "не-словарь"],
)
def test_canonical_gate_classifies_by_priceability(usage, billable, why):
    """Канон решает по тому, что backend умеет тарифицировать: prompt и completion."""
    assert is_billable(usage) is billable, why


def test_priceable_routing_usage_is_not_dropped():
    """Деньги: у вызова есть prompt и completion — он обязан пройти гейт.

    Это не абстракция: так выглядит `accumulate_usage` для провайдера, не заполняющего
    `total_tokens`. Раньше `/route` выбрасывал такой вызов целиком.
    """
    acc: dict = {}
    accumulate_usage(acc, _resp(prompt=40, completion=15, total=None), "m")

    assert is_billable(acc), "тарифицируемый роутинг-вызов (40+15 токенов) выброшен"


# --------------------------------------------------------------------------- #
# ОТРИЦАТЕЛЬНЫЙ результат: total-only деньгами не является                      #
# --------------------------------------------------------------------------- #
def test_total_only_usage_is_worth_zero_even_if_kept():
    """⚠️ Не гоняться за призраком.

    Разведка предлагала «перестать отбрасывать total-only» как денежную починку. Но цена
    считается из prompt/completion: запись с нулями дала бы РОВНО НОЛЬ. Пропускать её
    дальше — не деньги, а шум в `per_call_usage`.

    Настоящий вопрос про такой ответ другой: он означает, что провайдер не дал разбивки,
    и тарифицировать вызов нечем в принципе.
    """
    assert _price([{"model": "m", "prompt": 0, "completion": 0}]) == 0


def test_provider_total_larger_than_the_sum_changes_nothing():
    """И `total > prompt+completion` (кэш/reasoning) на цену тоже не влияет — она берёт
    два поля по отдельности. Отбрасывание провайдерского `total` недобиллом не является.
    """
    assert _price([{"model": "m", "prompt": 40, "completion": 15}]) == 55


# --------------------------------------------------------------------------- #
# Согласованность канона и потребителя                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "usage",
    [
        {"prompt": 40, "completion": 15, "total": 55},
        {"prompt": 40, "completion": 0, "total": 40},
        {"prompt": 0, "completion": 15, "total": 15},
    ],
    ids=["оба", "только-prompt", "только-completion"],
)
def test_meta_builder_and_assembler_agree_on_billable_usage(usage):
    """Что канон счёл тарифицируемым, то ассемблер обязан учесть — и наоборот."""
    meta = build_token_usage_meta(usage)

    asm = ReplyAssembler()
    asm.add_usage(usage)

    assert (meta is not None) == bool(asm.per_call_usage), (
        f"{usage}: build_token_usage_meta -> {meta is not None}, "
        f"reply_assembler -> {bool(asm.per_call_usage)}"
    )
    assert _price(asm.per_call_usage) == usage["prompt"] + usage["completion"]
