"""Карта репозитория объясняет агенту, что код читается через инструмент.

🔴 ЖИВАЯ ЖАЛОБА: пользователь приложил src.zip и попросил ревью кода. Zip разбирается в
ГРАФ-карту (узлы, связи, ключевые абстракции — БЕЗ тел функций), и агент, видя структуру,
просил «приложить код». Он не знал, что полный код за картой доступен через инструмент
search_knowledge_graph. Инструкция-обёртка закрывает разрыв: карта = навигация, код =
инструмент (который у general-агента ЕСТЬ в DEFAULT_FUNCTION_TOOLS).
"""

from __future__ import annotations

from types import SimpleNamespace

from service.application.processor_steps import _files_for_prompt
from service.application.repo_map import annotate_repo_map

# Как выглядит реальный GRAPH_REPORT (graphify): заголовок + характерные секции.
REPO_MAP = (
    "# Graph Report - /tmp/out (2026-07-23)\n\n"
    "## Summary\n- 509 nodes · 1042 edges · 28 communities\n\n"
    "## God Nodes (most connected)\n1. `AgentState` - 29 edges\n2. `process_message()` - 27 edges\n"
)


def _flat(text: str) -> str:
    """Текст со смятыми переносами и в нижнем регистре.

    ⚠️ Промпт свёрстан по ширине, и разрыв строки попадает внутрь фраз. Стражи этого файла
    уже дважды краснели на ВЁРСТКЕ вместо смысла — правило не должно зависеть от того, где
    редактор перенёс строку.
    """
    return " ".join(text.lower().split())


def test_repo_map_gets_tool_instruction():
    """⚠️ ГЛАВНОЕ. Карта получает инструкцию, а сама карта остаётся под ней целиком."""
    out = annotate_repo_map(REPO_MAP)

    assert out.endswith(REPO_MAP), "исходная карта должна остаться под инструкцией"
    assert "приложить код" in _flat(out), "нет прямого запрета просить код у пользователя"


def test_the_instruction_does_not_hang_on_one_tool():
    """🔴 ЗАМЕР НА ЖИВОМ СТЕНДЕ. Песочница выдана, исходники `requests` развёрнуты деревом,
    решатель поставил `files_tool: true`, инструменты `ws_*` выданы — и модель НЕ ПОЗВАЛА
    НИ ОДНОГО, ответив «объясню проект по этой карте» с рассуждением про «41 связь».

    Причина: инструкция называла ОДИН инструмент, `search_knowledge_graph`, а он выдаётся
    по своему гейту (`repo_graph_ids`) и в том прогоне был ОТКАЗАН. Названного средства
    модель не нашла и ответила тем, что было под рукой. Способ прочитать код обязан быть
    назван НЕ ОДИН.
    """
    out = annotate_repo_map(REPO_MAP)

    for tool in ("ws_list", "ws_read", "search_knowledge_graph"):
        assert tool in out, f"способ прочитать код не назван: {tool}"


def test_the_instruction_is_an_ordered_procedure_not_advice():
    """🔴 ЗАМЕРЕНО НА ПЯТИ ВОПРОСАХ. Совет «сначала прочитай файлы, потом отвечай» давал
    чтение лишь в 1 случае из 5: на «покажи код функции» — НОЛЬ вызовов файловых
    инструментов и один поход в интернет. Пронумерованный порядок действий с явным «первым
    вызови» модель исполняет, а пожелание в прозе — нет.
    """
    flat = _flat(annotate_repo_map(REPO_MAP))

    assert "порядок действий" in flat, "инструкция снова просьба, а не процедура"
    assert "первым" in flat, "не сказано, что делать ПЕРВЫМ"
    assert "только теперь отвечай" in flat, "нет запрета отвечать до чтения"


def test_the_first_step_depends_on_the_question():
    """🔴 ЗАМЕРЕНО ПОСЛЕ ПРЕДЫДУЩЕЙ РЕДАКЦИИ. Прежний порядок начинался с `ws_grep`, и на
    обзорном вопросе («изучи проект, что в нём») модель упиралась в него же: «без шаблона
    поиска я не могу получить содержимое файлов, уточните, что искать». Шаблона у неё нет и
    взяться ему неоткуда — вопрос обзорный.

    Для обзора первым идёт `ws_list`, для точечного поиска — `ws_grep`; выбор назван явно.
    """
    flat = _flat(annotate_repo_map(REPO_MAP))

    assert "обзорный" in flat and "ws_list" in flat, "обзорный путь не назван"
    assert "точечный" in flat and "ws_grep" in flat, "точечный путь не назван"
    assert "шаблон для поиска тут не нужен" in flat, "не снят повод требовать шаблон"
    assert "уточните, что именно искать" in flat, "отказ-переспрашивание не запрещён"


def test_the_instruction_says_the_map_has_no_code():
    """⚠️ Без этого «объясню по карте» выглядит для модели допустимым ответом."""
    flat = _flat(annotate_repo_map(REPO_MAP))

    assert "ни одной строки кода" in flat, "не сказано главное: кода в карте нет"
    assert "выдумка" in flat, "пересказ карты нигде не назван выдумкой"


def test_the_known_wrong_moves_are_named():
    """🔴 КАЖДЫЙ ЗАПРЕТ ЗДЕСЬ — ЭТО СЛУЧИВШЕЕСЯ, а не гипотеза. Живые прогоны дали ровно
    эти четыре: ответ «судя по карте», восемь походов в интернет за локальным кодом,
    «могу открыть файл, продолжать?» и просьба приложить код."""
    flat = _flat(annotate_repo_map(REPO_MAP))

    for wrong in ("судя по карте", "интернете", "продолжать?", "приложить код", "с чего начнём?"):
        assert wrong in flat, f"известная ошибка не названа запрещённой: {wrong}"


def test_a_file_listing_is_not_an_answer():
    """🔴 ЗАМЕР НА «ОТРЕВЬЮЙ КАЧЕСТВО КОДА». Модель дважды позвала `ws_list`, получила 8 КБ
    дерева — и закончила ход словами «С чего начнем?», ни одного файла не открыв.

    Прежний запрет спрашивать разрешение был про фразу «могу открыть файл, продолжать?» и
    на «с чего начнём?» не распространялся: запрет КОНКРЕТНОЙ ФОРМУЛИРОВКИ всегда обходится
    другой. Правило теперь про действие — выбор файлов делает агент, а не человек.
    """
    flat = _flat(annotate_repo_map(REPO_MAP))

    assert "список файлов — не ответ" in flat, "остановка на перечне файлов не запрещена"
    assert "выбери" in flat, "не сказано, что выбирать файлы должен сам агент"


def test_the_map_stays_navigation_not_forbidden():
    """⚠️ ГРАНИЦА. Запретить карту целиком было бы вредно: по ней видно, какие файлы
    открывать первыми, и без неё агент читал бы дерево наугад."""
    assert "навигаци" in _flat(annotate_repo_map(REPO_MAP))


def test_an_empty_directory_has_one_named_fallback():
    """⚠️ Замена чтению обязана быть НАЗВАНА и ОДНА: «если инструментов нет» без имени —
    это лазейка, по которой модель уходит выдумывать (замерено)."""
    flat = _flat(annotate_repo_map(REPO_MAP))

    assert "search_knowledge_graph" in flat
    assert "выдумывать" in flat, "выдумывание вместо замены нигде не запрещено"


def test_plain_document_is_untouched():
    """Обычный документ (не карта репо) не получает инструкцию про граф."""
    doc = "# Техническое задание\n\nРеализовать функцию сортировки массива."
    assert annotate_repo_map(doc) == doc


def test_partial_marker_does_not_trigger():
    """Нужны ОБА маркера: случайный '# Graph Report' в тексте без 'God Nodes' — не карта."""
    text = "# Graph Report на доске обсудили, но кода нет."
    assert annotate_repo_map(text) == text


def test_empty_is_safe():
    assert annotate_repo_map("") == ""
    assert annotate_repo_map(None) == ""


def test_annotation_wired_through_files_for_prompt():
    """⚠️ Инструкция доезжает через _files_for_prompt (точка сборки промпта)."""
    ctx = SimpleNamespace(tabular_files=None)
    out, skipped = _files_for_prompt(ctx, REPO_MAP)

    assert "search_knowledge_graph" in out, "карта репо в промпте без инструкции про инструмент"
    assert skipped is False


# --- архив без графа: перечень файлов — тоже «карта» -------------------------------------- #


def test_a_bare_listing_counts_as_an_archive():
    """🔴 ЗАМЕРЕНО: на не-кодовом архиве (стили TMLR, LaTeX) graphify отвечает «graph is
    empty», и вложение приезжает ОДНИМ перечнем файлов, без отчёта графа.

    Для решателя это тот же случай, что и карта: содержимое лежит в песочнице, а не в
    контексте. Не узнай он перечень — инструменты `ws_*` снова снимутся до прогона, и агент
    ответит по одним именам файлов. Ровно с этой жалобы всё и началось.
    """
    from service.application.repo_map import is_repo_map

    listing = "# Файлы архива (9)\n\n- LICENSE · 1 Б\n- tmlr.sty · 37 Б"

    assert is_repo_map(listing)


def test_an_ordinary_markdown_is_not_an_archive():
    """🔴 ГРАНИЦА. Обычный документ картой не считается: иначе на каждый приложенный
    markdown агент полезет искать файлы, которых нет."""
    from service.application.repo_map import is_repo_map

    assert not is_repo_map("# Файлы проекта\n\nописание в свободной форме")
    assert not is_repo_map("# Отчёт\n\nтекст документа пользователя")


def test_the_listing_gets_the_same_reading_order():
    """⚠️ Перечень получает ТУ ЖЕ приписку с порядком действий: без неё «карта» есть, а
    указания прочитать файлы нет — и агент снова отвечает списком имён."""
    from service.application.repo_map import annotate_repo_map

    out = annotate_repo_map("# Файлы архива (9)\n\n- README.md · 79 Б")

    assert "ws_read" in out and "ПОРЯДОК ДЕЙСТВИЙ" in out
