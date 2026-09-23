"""Выбор модели для субагентов.

⚠️ Нарезка текста на чанки уехала отсюда в `service/domain/text_stream.py`. Она нужна
не только субагентам, но и аварийному пути `runners/sdk_run.py`, а импорт из `runners/`
сюда замыкал КОЛЬЦО: `base` → `runners` → `subagents.utils` → пакет `subagents` (его
`__init__` тянет всех агентов) → снова `base`.
"""

import re

# Известно-надёжные дешёвые текстовые модели по убыванию предпочтения. Берём
# первую, что реально есть в списке провайдера — иначе агрегаторы (RouterAI/
# OpenRouter) на 300+ моделей отдают алфавитно-первую (часто битую/BYOK-only).
_PREFERRED_TEXT_MODELS = (
    "openai/gpt-4o-mini",
    "gpt-4o-mini",
    "deepseek/deepseek-chat",
    "openai/gpt-4o",
    "gpt-4o",
    "qwen/qwen-2.5-72b-instruct",
    "mws-gpt-alpha",
)


def pick_text_model(models: list[str]) -> str | None:
    if not models:
        return None
    available = set(models)
    for pref in _PREFERRED_TEXT_MODELS:
        if pref in available:
            return pref
    text_re = re.compile(r"(gpt|claude|gemini|deepseek|qwen|llama|mistral|instruct|chat)", re.I)
    return next((m for m in models if text_re.search(m)), models[0])


# Картиночные модели, ПРОВЕРЕННЫЕ на нашем транспорте, в порядке предпочтения.
#
# ⚠️ БЕЗ ЭТОГО СПИСКА КАРТИНКИ НЕ ГЕНЕРИРОВАЛИСЬ ВОВСЕ. Выбор шёл первой моделью, чьё имя
# совпало с регуляркой, — на живом каталоге из 422 моделей это `black-forest-labs/
# flux.2-flex`. Она НАСТОЯЩИЙ генератор изображений, но не отвечает на то, чем мы её
# зовём: chat/completions с `modalities: ["image","text"]`. Провайдер возвращает 503
# «No endpoints found that support the requested output modalities», и это выглядит как
# «картинки почему-то не работают».
#
# Список составлен ПЕРЕБОРОМ НА ЖИВОМ СТЕНДЕ, а не по названиям:
#   google/gemini-2.5-flash-image  — отдала картинку (1.4 МБ);
#   openai/gpt-image-1-mini        — 503, модальности не поддержаны;
#   black-forest-labs/flux.2-flex  — 503, модальности не поддержаны.
# Имя вида «*-image» само по себе НИЧЕГО не гарантирует — проверяйте перед добавлением.
_PREFERRED_IMAGE_MODELS = (
    "google/gemini-2.5-flash-image",
    "google/gemini-3.1-flash-image",
    "google/gemini-3-pro-image",
)


def pick_image_model(models: list[str]) -> str | None:
    """Модель для генерации изображений: проверенные — первыми.

    Регулярка оставлена ЗАПАСНЫМ путём: у другого провайдера каталог иной, и полное
    отсутствие выбора хуже, чем выбор, который может не сработать (сбой обрабатывается
    и виден пользователю).
    """
    if not models:
        return None
    available = set(models)
    for pref in _PREFERRED_IMAGE_MODELS:
        if pref in available:
            return pref
    image_re = re.compile(r"(image|dall|stable|flux|kandinsky|sdxl)", re.I)
    return next((m for m in models if image_re.search(m)), None)


def _prefer_or_default(models: list[str], preferred: str | None) -> str | None:
    """Keep an admitted explicit model immutable; only Auto may choose a default.

    ``preferred`` is no longer a soft hint here: orchestration has already resolved
    the user's selection against the immutable provider snapshot for this run. A
    fallback at this stage makes the UI claim one model while a subagent executes
    and bills another one.
    """
    if preferred:
        return preferred if preferred in set(models) else None
    return pick_text_model(models)


def pick_meta_model(models: list[str], preferred: str | None = None) -> str | None:
    """Модель для СЛУЖЕБНЫХ мета-вызовов (декомпозиция/план/оценка сложности).

    ВЫБРАННАЯ пользователем модель уже квалифицирована на границе run и потому
    неизменяема. Если она отсутствует в snapshot, вызов не выполняется другой моделью.
    Только Auto без явного выбора использует дешёвый текстовый дефолт.
    """
    return _prefer_or_default(models, preferred)


def pick_answer_model(models: list[str], preferred: str | None = None) -> str | None:
    """Модель, которая пишет ТЕКСТ, ЧИТАЕМЫЙ ПОЛЬЗОВАТЕЛЕМ.

    ⚠️ ОТДЕЛЬНОЕ ИМЯ, ХОТЯ ЛОГИКА ТА ЖЕ, ЧТО У ``pick_meta_model``. Разница не
    техническая, а смысловая, и именно на ней тут ошибались: субагенты звали
    ``pick_text_model`` — функцию БЕЗ параметра предпочтения, — и синтез веб-поиска,
    отчёт ресёрча, содержимое презентации писала дешёвая модель по умолчанию. Человек
    выбирал Opus, платил за ответ по прайсу gpt-4o-mini и получал текст от gpt-4o-mini,
    нигде об этом не узнавая: учёт токенов при этом был корректен, расходилось только
    ожидание с реальностью.

    Служебное (сжатие контекста, конденсация промпта картинки, разбор вложений в
    контекст) по-прежнему идёт на дешёвой: пользователь этот текст не читает, а сжатие
    — до 13 вызовов на секцию, и на дорогой модели счёт вырос бы заметно.
    """
    return _prefer_or_default(models, preferred)
