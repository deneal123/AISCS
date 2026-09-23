"""Вход оркестратора и бесплатные короткие пути — без единого вызова модели.

Прежний роутер видел только текст сообщения, поэтому «а теперь найди свежее» выглядело
обрывком, а «что нового в 2026» не отличалось от исторического вопроса.

🔴 ПРИНЦИП КОРОТКИХ ПУТЕЙ: regex вправе УДЕШЕВИТЬ решение, но не ПОТРАТИТЬ деньги. Здесь
нет ни одной ветки, которая что-то включает: за дорогое отвечает модель, видящая
контекст, а не список слов.

Модуль чистый: ни клиента, ни SDK, ни настроек — всё проверяется прямым вызовом.
"""

from __future__ import annotations

import re
from typing import Any

from service.domain.routing.auto_decision import (
    REASON_SHORTCUT_CONTINUE,
    REASON_SHORTCUT_EMPTY,
    REASON_SHORTCUT_SMALLTALK,
    SOURCE_SHORTCUT,
    AutoDecision,
)

# Бюджет входа: за него платят КАЖДЫМ сообщением, поэтому обрезки несущие — без них
# длинный тред превращает дешёвое решение в дорогое.
MAX_MESSAGE_CHARS = 1200
MAX_TURN_CHARS = 200
MAX_SUMMARY_CHARS = 300
MAX_HISTORY_TURNS = 4
MAX_LISTED_FILES = 5

# 🔴 СЛОВАРЬ ЗАКРЫТЫЙ: путь срабатывает, только если КАЖДОЕ слово входит в список. Так
# «найди» не нужно вето — его тут просто нет, а появиться может лишь по ошибке, которую
# стережёт тест на непересечение с `_ACTION_RE`. Прежняя проверка целой строки не ловила
# даже «привет как дела».
_SMALLTALK_WORDS = frozenset(
    """привет здравствуй здравствуйте здравствуй добрый доброе доброго день дня утро утра
    вечер вечера ночи как дела дела твои у тебя спасибо спс благодарю пожалуйста пока
    ок окей ладно ясно понятно принято супер отлично класс хорошо большое огромное
    hi hello hey good morning evening thanks thank you bye ok okay nice cool great""".split()
)

# Чистое продолжение: человек просит то же самое, но дальше. Маршрут менять незачем.
_CONTINUE_WORDS = frozenset(
    """продолж продолжи продолжай дальше ещё еще подробнее подробней короче
    давай ага да нет угу верно го go on more continue next""".split()
)

# Глаголы действия. В решении не участвуют: они здесь ради стража, который не даст
# втащить такое слово в словари выше.
_ACTION_RE = re.compile(
    r"(найд|поищ|ищи|погугл|свеж|актуальн|нарисуй|сгенерир|презентац|слайд|исследуй"
    r"|источник|сравни|посчитай|проанализир|составь|разработай|объясни|напиши"
    r"|search|find|latest|draw|generate|explain|write)",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
# Фраза из десяти вежливых слов — уже не смолток, а вступление к просьбе.
_SHORTCUT_WORD_LIMIT = 6


def _clip(text: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def shortcut_decision(user_input: str) -> AutoDecision | None:
    """Решение БЕЗ вызова модели. `None` — «дёшево не вышло, спрашивай модель».

    Смотрим ТОЛЬКО на текущее сообщение. Длина истории сюда сознательно не входит: иначе
    появился бы соблазн правила «короткое сообщение при непустой истории → обычный
    ответ», и «а теперь найди свежее» после долгой беседы навсегда перестало бы искать.
    Длинная беседа не должна топить новое намерение.
    """
    words = _WORD_RE.findall(str(user_input or "").lower())
    if not words:
        # Пусто или одни знаки препинания — решать нечего, и платить за это тоже незачем.
        return AutoDecision(route="general", reason_code=REASON_SHORTCUT_EMPTY).with_source(
            SOURCE_SHORTCUT
        )
    if len(words) > _SHORTCUT_WORD_LIMIT:
        return None

    if all(w in _SMALLTALK_WORDS for w in words):
        return AutoDecision(route="general", reason_code=REASON_SHORTCUT_SMALLTALK).with_source(
            SOURCE_SHORTCUT
        )
    # Продолжение допускает вежливые слова рядом («да, давай подробнее»).
    if all(w in _CONTINUE_WORDS or w in _SMALLTALK_WORDS for w in words):
        return AutoDecision(route="general", reason_code=REASON_SHORTCUT_CONTINUE).with_source(
            SOURCE_SHORTCUT
        )
    return None


def _field(item: Any, key: str) -> Any:
    """Значение поля вложения, чем бы оно ни приехало — словарём или моделью."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _attachment_shapes(attachments: Any) -> tuple[list[str], list[str]]:
    """ФОРМА вложений: типы и имена. Содержимое не берём — оно стоит десятки тысяч
    токенов и для выбора режима бесполезно."""
    kinds: list[str] = []
    names: list[str] = []
    for item in list(attachments or [])[:MAX_LISTED_FILES]:
        # 🔴 ДВЕ ФОРМЫ И ДВА ИМЕНИ ПОЛЯ, И ПРЕЖНЯЯ СТРОКА ПАДАЛА НА ОБОИХ. Вложение
        # приезжает то словарём (тело `/run` не типизирует список), то моделью
        # `ModalityAttachment`, а имя файла в модели зовётся `name`, не `filename`.
        # Выражение `getattr(item, "filename", None) or item.get("filename")` на модели
        # доходило до второго операнда и роняло ВЕСЬ ход:
        #
        #     AttributeError: 'ModalityAttachment' object has no attribute 'get'
        #
        # Человек получал «Не удалось получить ответ от модели. Проверьте API-ключ» —
        # текст, который уводит от причины настолько далеко, насколько это возможно.
        kind = _field(item, "kind")
        name = _field(item, "name") or _field(item, "filename")
        if kind:
            kinds.append(str(kind))
        if name:
            names.append(_clip(name, 60))
    return sorted(set(kinds)), names


def build_auto_input(
    *,
    user_input: str,
    today: str,
    history_messages: Any = None,
    compact_summary: str = "",
    attachments: Any = None,
    has_tables: bool = False,
    has_repo_graph: bool = False,
    has_reference_image: bool = False,
    attachment_text_in_prompt: bool = False,
    attachment_text_in_prompt_is_a_map: bool = False,
    persona_labels: Any = None,
    prior_route: str | None = None,
) -> str:
    """Вход решателя. Компактно и по делу: цель — уложиться в сотни токенов.

    ⚠️ Каждая секция здесь стоит денег НА КАЖДОМ сообщении, поэтому попала сюда только
    та, что МЕНЯЕТ решение:

    * дата — «что нового» без неё неотличимо от исторического вопроса;
    * 4 последние реплики — ровно столько нужно для «а теперь найди свежее»; пятая и
      дальше намерение не уточняют, а платим за них всегда;
    * готовое сжатие треда — берём, раз бэкенд его уже посчитал, второй раз не платим;
    * форма вложений и булевы признаки — при таблице веб-поиск почти всегда не нужен,
      при графе репозитория тем более;
    * роль — «аналитик» и «таролог» по-разному отвечают на один вопрос.

    НЕ подаём: список моделей (это работа роутера моделей), тексты вложений, полную
    историю, память. Каждое — тысячи лишних токенов на каждом сообщении.
    """
    parts = [f"СЕГОДНЯ: {today}"]

    turns = [m for m in list(history_messages or []) if str((m or {}).get("content") or "").strip()]
    if turns:
        lines = [
            f"{'пользователь' if (m.get('role') or 'user') == 'user' else 'ассистент'}: "
            f"{_clip(m.get('content'), MAX_TURN_CHARS)}"
            for m in turns[-MAX_HISTORY_TURNS:]
        ]
        parts.append("ДИАЛОГ (последние реплики):\n" + "\n".join(lines))

    if summary := _clip(compact_summary, MAX_SUMMARY_CHARS):
        parts.append(f"ТЕМА ТРЕДА: {summary}")

    kinds, names = _attachment_shapes(attachments)
    if kinds or names:
        listed = ", ".join(names) if names else "без имён"
        parts.append(f"ВЛОЖЕНИЯ: типы [{', '.join(kinds) or '—'}], файлы: {listed}")

    flags = [
        name
        for name, on in (
            ("есть табличные данные", has_tables),
            ("разобран репозиторий", has_repo_graph),
            ("есть картинка-референс", has_reference_image),
        )
        if on
    ]
    # 🔴 Про текст вложения говорим В ОБЕ СТОРОНЫ, а не только когда он есть. Решатель
    # опирается на посылку «текст приложенного файла уже в контексте» — молчание он
    # прочитает как подтверждение, и на файле, которого не видно, снова ответит «читать
    # инструментами не нужно». Отсутствие признака среди перечисленных — не факт.
    #
    # ⚠️ Только про ФАЙЛЫ. Картинку и звук модель получает отдельным путём (описание
    # аналитика), и «текста в контексте нет» про них было бы неправдой.
    if set(kinds) - {"image", "audio"}:
        # 🔴 ТРИ СОСТОЯНИЯ, А НЕ ДВА. Для архива с кодом в контексте лежит КАРТА
        # репозитория: она непуста, поэтому признак был истинным, и решатель по правилу
        # «читать вложение инструментами не нужно» снимал файловые инструменты СО ВСЕХ
        # запросов про код. Человек загружал архив и получал общие рассуждения об
        # архитектуре — посмотреть файлы агенту было нечем.
        if attachment_text_in_prompt_is_a_map:
            flags.append(
                "🔴 в контексте только КАРТА репозитория (узлы и связи БЕЗ тел функций) — "
                "сам код читается ТОЛЬКО инструментами"
            )
        else:
            flags.append(
                "текст вложения В КОНТЕКСТЕ ЕСТЬ"
                if attachment_text_in_prompt
                else "🔴 текста вложения в контексте НЕТ — прочитать его можно только инструментом"
            )
    if flags:
        parts.append("КОНТЕКСТ: " + "; ".join(flags))

    labels = [str(x) for x in (persona_labels or []) if str(x).strip()]
    if labels:
        parts.append("РОЛЬ АССИСТЕНТА: " + ", ".join(labels))

    if prior_route:
        parts.append(f"ПОДСКАЗКА ПРЕДЫДУЩЕГО РОУТЕРА: {prior_route}")

    parts.append(f"ЗАПРОС: {_clip(user_input, MAX_MESSAGE_CHARS)}")
    return "\n\n".join(parts)
