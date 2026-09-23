"""Каждый вид вызова, который эмитит домен, обязан быть КЛАССИФИЦИРОВАН.

🔴 Зачем страж. Потребитель строит признак «ответила не та модель, которую ты выбрал»,
исключая служебные вызовы (`SERVICE_USAGE_KINDS`). Вид, забытый в классификации,
автоматически считается ОТВЕТОМ — и возвращает ровно тот ложный бейдж, ради которого
разделение и заводилось: в живом диалоге он горел на трёх ответах из четырёх, хотя
отвечала выбранная модель, а рядом просто работала декомпозиция на мета-модели.

Заметить это по поведению почти невозможно: ошибок нет ни на одной стороне, признак
просто врёт. Поэтому полнота проверяется СКАНОМ ИСХОДНИКОВ, а не договорённостью —
тот же приём, что у закрытого словаря слотов личности (`persona/slots.py`).
"""

from __future__ import annotations

import ast
import pathlib

from service.contracts import ANSWER_USAGE_KINDS, NON_USAGE_KINDS, SERVICE_USAGE_KINDS

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "service"


def _emitted_kinds() -> dict[str, set[str]]:
    """Literal event kinds plus typed UsageKind values used by receipt calls."""
    from service.domain.usage_ledger import UsageKind

    found: dict[str, set[str]] = {}
    for path in SERVICE_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — синтаксис ловит ruff, не этот страж
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    value = keyword.value
                    if keyword.arg not in {"kind", "usage_kind"}:
                        continue
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        found.setdefault(value.value, set()).add(
                            str(path.relative_to(SERVICE_ROOT.parent))
                        )
                        continue
                    if (
                        isinstance(value, ast.Attribute)
                        and isinstance(value.value, ast.Name)
                        and value.value.id == "UsageKind"
                        and value.attr in UsageKind.__members__
                    ):
                        kind = UsageKind[value.attr].value
                        found.setdefault(kind, set()).add(
                            str(path.relative_to(SERVICE_ROOT.parent))
                        )
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=False):
                if not (isinstance(key, ast.Constant) and key.value == "kind"):
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.setdefault(value.value, set()).add(
                        str(path.relative_to(SERVICE_ROOT.parent))
                    )
    return found


def test_every_emitted_kind_is_classified():
    """🔴 Неклассифицированный вид молча становится «ответом» и возвращает ложный бейдж."""
    classified = SERVICE_USAGE_KINDS | ANSWER_USAGE_KINDS | NON_USAGE_KINDS
    emitted = _emitted_kinds()

    assert emitted, "скан не нашёл ни одного `kind` — страж ослеп, а не код чистый"

    unknown = {k: sorted(v) for k, v in emitted.items() if k not in classified}
    assert not unknown, (
        "виды вызова не классифицированы в `service/contracts.py` — они будут считаться "
        f"ОТВЕТОМ и вернут ложную «замену модели»: {unknown}"
    )


def test_kind_reaches_per_call_usage():
    """🔴 Метка обязана ДОЕХАТЬ до потребителя, а не остаться в метаданных события.

    `per_call_usage` — единственное, что видит воркер; вид, потерянный здесь, снова
    делает служебный вызов неотличимым от ответа.
    """
    from service.application.reply_assembler import ReplyAssembler
    from service.events import AgentEvent, EventType

    assembler = ReplyAssembler()
    assembler.add_usage({"prompt": 10, "completion": 2, "model": "meta", "kind": "route_model"})
    assembler.consume(
        event=AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name="planner",
            data="",
            metadata={
                "token_usage": {"prompt": 5, "completion": 1, "model": "meta"},
                "kind": "meta_usage",
            },
        ),
        stream_chunk_type=EventType.STREAM_CHUNK,
        error_type=EventType.ERROR,
        structured_output_type=EventType.STRUCTURED_OUTPUT,
    )
    assembler.consume(
        event=AgentEvent(
            type=EventType.AGENT_COMPLETE,
            agent_name="general",
            data="",
            metadata={"token_usage": {"prompt": 100, "completion": 20, "model": "выбранная"}},
        ),
        stream_chunk_type=EventType.STREAM_CHUNK,
        error_type=EventType.ERROR,
        structured_output_type=EventType.STRUCTURED_OUTPUT,
    )

    kinds = [call.get("kind") for call in assembler.per_call_usage]
    assert kinds == ["route_model", "meta_usage", None], f"метка не доехала: {kinds}"


def test_answer_call_carries_no_kind():
    """Основной ответ метки НЕ несёт: иначе пришлось бы помечать каждую дельту стрима."""
    from service.application.reply_assembler import ReplyAssembler

    assembler = ReplyAssembler()
    assembler.add_usage({"prompt": 100, "completion": 20, "model": "выбранная"})

    assert "kind" not in assembler.per_call_usage[0]


def test_classification_sets_do_not_overlap():
    """Вид ровно в одном наборе: пересечение — это два разных ответа на один вопрос."""
    assert not (SERVICE_USAGE_KINDS & ANSWER_USAGE_KINDS)
    assert not (SERVICE_USAGE_KINDS & NON_USAGE_KINDS)
    assert not (ANSWER_USAGE_KINDS & NON_USAGE_KINDS)


def test_classification_has_no_dead_entries():
    """Классифицировано то, что реально эмитится: мёртвая запись вводит в заблуждение."""
    emitted = set(_emitted_kinds())
    declared = SERVICE_USAGE_KINDS | ANSWER_USAGE_KINDS | NON_USAGE_KINDS

    assert declared - emitted == set(), (
        f"объявлены виды, которых нет в коде: {sorted(declared - emitted)}"
    )


def test_money_events_never_carry_a_computed_kind():
    """🔴 На денежном событии `kind` обязан быть ЛИТЕРАЛОМ.

    Классификация статическая: вычисляемое значение (`"kind": att.kind`) обошло бы её
    целиком и попало бы в `per_call_usage` неизвестным видом — то есть снова считалось
    бы ответом. Сегодня вычисляемый `kind` есть только на статус-событии разбора
    вложений, где `token_usage` нет; страж держит это раздельным и дальше.
    """
    offenders: list[str] = []
    for path in SERVICE_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if "token_usage" not in keys:
                continue
            for key, value in zip(node.keys, node.values, strict=False):
                if isinstance(key, ast.Constant) and key.value == "kind":
                    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                        offenders.append(f"{path.relative_to(SERVICE_ROOT.parent)}:{node.lineno}")

    assert not offenders, f"вычисляемый `kind` на событии с token_usage: {offenders}"
