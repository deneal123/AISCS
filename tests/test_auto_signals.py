"""Бесплатные короткие пути и вход оркестратора.

🔴 ПРИНЦИП, КОТОРЫЙ СТЕРЕГУТ ЭТИ ТЕСТЫ: regex может УДЕШЕВИТЬ решение, но не может
ПОТРАТИТЬ деньги. Эвристика вправе сказать «это точно обычный ответ» — это экономия. Она
не вправе включить поиск: за дорогое отвечает модель, у которой есть контекст, а не
список слов.
"""

from __future__ import annotations

import pytest

from service.domain.routing.auto_decision import SOURCE_SHORTCUT
from service.domain.routing.auto_signals import build_auto_input, shortcut_decision
from service.shared.token_estimate import estimate_tokens


# --------------------------------------------------------------------------- #
# Короткие пути                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text", ["привет", "Привет!", "спасибо", "спс", "добрый день", "ок", "thanks", "hi"]
)
def test_smalltalk_is_free(text):
    """«Привет» не должен стоить вызова модели — это самый частый класс сообщений."""
    decision = shortcut_decision(text)

    assert decision is not None and decision.route == "general"
    assert decision.source == SOURCE_SHORTCUT
    assert not (decision.needs_fresh_data or decision.needs_plan or decision.multi_step)


@pytest.mark.parametrize("text", ["продолжи", "дальше", "подробнее", "ещё", "continue"])
def test_pure_continuation_is_free(text):
    """Просьба «то же самое, но дальше» маршрут не меняет."""
    assert shortcut_decision(text).route == "general"


@pytest.mark.parametrize(
    "text",
    [
        "найди курс",
        "а теперь найди свежее",
        "поищи",
        "нарисуй кота",
        "сравни подходы",
        "составь презентацию",
    ],
)
def test_action_requests_reach_the_model(text):
    """🔴 ГЛАВНОЕ. Просьба действия обязана дойти до модели, даже если она короткая.

    «Найди курс» — два слова, по длине это смолток.
    """
    assert shortcut_decision(text) is None, "дешёвая ветка съела содержательную просьбу"


def test_vocabularies_cannot_contain_action_words():
    """🔴 СТРАЖ СЛОВАРЯ, а не поведения — и вот почему именно он.

    Первая версия держала «вето на глаголы действия» прямо в функции. Мутация показала,
    что вето НЕДОСТИЖИМО: проверка целой строки и так отбрасывала всё лишнее, то есть
    защита существовала только на бумаге.

    Реальный риск другой: кто-то расширит словарь вежливых слов и втащит туда «давай
    найдём» или «объясни». Тогда короткий путь начнёт молча съедать содержательные
    просьбы — без единой ошибки и без падения тестов. Стережём ровно это.
    """
    from service.domain.routing.auto_signals import (
        _ACTION_RE,
        _CONTINUE_WORDS,
        _SMALLTALK_WORDS,
    )

    guilty = sorted(w for w in (_SMALLTALK_WORDS | _CONTINUE_WORDS) if _ACTION_RE.search(w))

    assert not guilty, f"в словарь дешёвой ветки попали глаголы действия: {guilty}"


@pytest.mark.parametrize(
    "text", ["привет как дела", "привет, как дела!", "спасибо большое", "да, давай подробнее"]
)
def test_common_polite_phrases_are_free(text):
    """🔴 «Привет как дела» — самое частое приветствие вообще.

    Первая версия сверяла сообщение целиком и его НЕ ловила: любое второе слово рушило
    совпадение, и за самый частый класс сообщений мы платили вызовом модели.
    """
    assert shortcut_decision(text) is not None, f"{text!r} снова стоит вызова модели"


def test_shortcut_ignores_history_length():
    """🔴 Живой сценарий: «а теперь найди свежее» после долгой беседы.

    ⚠️ Короткий путь смотрит ТОЛЬКО на текущее сообщение — истории он не получает вовсе.
    Правило вида «короткое сообщение при непустой истории → обычный ответ» выглядит
    разумно и навсегда сломало бы этот случай: длинная беседа не должна топить новое
    намерение. Проверяем это как свойство сигнатуры, а не как поведение.
    """
    import inspect

    assert list(inspect.signature(shortcut_decision).parameters) == ["user_input"]
    assert shortcut_decision("а теперь найди свежее") is None


def test_content_beyond_the_word_limit_goes_to_the_model():
    assert shortcut_decision("объясни как работает индекс в постгресе") is None


def test_empty_input_is_free():
    assert shortcut_decision("   ").route == "general"


# --------------------------------------------------------------------------- #
# Вход оркестратора                                                            #
# --------------------------------------------------------------------------- #
def test_input_carries_what_changes_the_decision():
    prompt = build_auto_input(
        user_input="а теперь найди свежее",
        today="2026-07-26",
        history_messages=[
            {"role": "user", "content": "расскажи про курс биткоина"},
            {"role": "assistant", "content": "исторически он рос"},
        ],
        compact_summary="обсуждали криптовалюты",
        attachments=[{"kind": "data", "filename": "База форума.xlsx"}],
        has_tables=True,
        persona_labels=["Аналитик"],
        prior_route="general",
    )

    assert "2026-07-26" in prompt, "без даты «что нового» неотличимо от исторического вопроса"
    assert "курс биткоина" in prompt, "история не доехала — follow-up непонятен"
    assert "База форума.xlsx" in prompt
    assert "табличные данные" in prompt
    assert "Аналитик" in prompt
    assert "а теперь найди свежее" in prompt


def test_input_is_bounded_on_pathological_data():
    """🔴 Вход оплачивается КАЖДЫМ сообщением — обрезки несущие, а не «на всякий случай»."""
    prompt = build_auto_input(
        user_input="ф" * 100_000,
        today="2026-07-26",
        history_messages=[{"role": "user", "content": "я" * 10_000} for _ in range(50)],
        compact_summary="с" * 50_000,
        attachments=[{"kind": "data", "filename": "и" * 500} for _ in range(30)],
        has_tables=True,
        has_repo_graph=True,
        persona_labels=["Аналитик", "Инженер"],
    )

    assert estimate_tokens(prompt) < 900, f"вход раздулся до {estimate_tokens(prompt)} токенов"


def test_attachment_content_never_leaks_into_the_prompt():
    """Берём ФОРМУ вложений, не содержимое: содержимое стоит десятки тысяч токенов."""
    prompt = build_auto_input(
        user_input="что тут",
        today="2026-07-26",
        attachments=[{"kind": "doc", "filename": "t.pdf", "extracted_text": "СЕКРЕТНЫЙ ТЕКСТ"}],
    )

    assert "t.pdf" in prompt
    assert "СЕКРЕТНЫЙ ТЕКСТ" not in prompt


def test_empty_context_gives_a_minimal_prompt():
    """Пустой тред не должен тащить пустые заголовки секций — за них тоже платят."""
    prompt = build_auto_input(user_input="привет", today="2026-07-26")

    assert "ДИАЛОГ" not in prompt and "ВЛОЖЕНИЯ" not in prompt and "КОНТЕКСТ" not in prompt
    assert estimate_tokens(prompt) < 60


# --------------------------------------------------------------------------- #
# Посылка «текст вложения уже в контексте»                                     #
# --------------------------------------------------------------------------- #
def test_missing_attachment_text_is_stated_out_loud():
    """🔴 ГЛАВНОЕ. Файл приложен, а текста в промпте нет — решателю это говорят прямо.

    Молчание он читает как подтверждение посылки «текст уже в контексте» и на просьбу
    «прочитай десятую строку» отвечает «инструменты не нужны» — при том что читать нечем.
    """
    prompt = build_auto_input(
        user_input="вычитай 10 строку",
        today="2026-07-28",
        attachments=[{"kind": "document", "filename": "А - рассылка.json"}],
        attachment_text_in_prompt=False,
    )

    assert "текста вложения в контексте НЕТ" in prompt, (
        "решатель не узнает, что файл ему не показали"
    )


def test_present_attachment_text_is_stated_too():
    prompt = build_auto_input(
        user_input="сделай саммери",
        today="2026-07-28",
        attachments=[{"kind": "document", "filename": "тз.pdf"}],
        attachment_text_in_prompt=True,
    )

    assert "текст вложения В КОНТЕКСТЕ ЕСТЬ" in prompt


def test_media_only_message_says_nothing_about_file_text():
    """⚠️ Картинку модель получает описанием аналитика — «текста нет» было бы неправдой."""
    prompt = build_auto_input(
        user_input="что на фото",
        today="2026-07-28",
        attachments=[{"kind": "image", "filename": "photo.png"}],
        attachment_text_in_prompt=False,
    )

    assert "текста вложения" not in prompt


def test_rule_in_prompt_is_conditional_on_the_fact():
    """Правило «читать инструментами не нужно» не должно быть БЕЗУСЛОВНЫМ.

    Мутация «вернуть прежнюю формулировку» красит этот тест: прежняя объявляла посылку
    вечной истиной («его текст УЖЕ в контексте»), и случай «читать нечем» в неё не влезал.
    """
    from service.domain.routing.auto_prompt import auto_prompt

    text = auto_prompt()
    assert "текста вложения в контексте НЕТ" in text, (
        "в правиле нет случая «файл приложен, но модель его не видит»"
    )
    assert "текст УЖЕ в контексте, читать его инструментами не нужно" not in text, (
        "посылка снова объявлена безусловной"
    )


def test_fact_is_computed_from_the_prompt_not_guessed():
    """⚠️ ТОЧКА ВЫЗОВА. Факт считается тем же правилом, что решает состав промпта."""
    import inspect

    from service.application import processor_steps as ps

    src = inspect.getsource(ps.ProcessorStepsMixin._resolve_route_and_plan)
    assert "attachment_text_in_prompt=attachment_text_reaches_prompt(" in src, (
        "решателю снова едет догадка вместо факта"
    )
    rule = inspect.getsource(ps.attachment_text_reaches_prompt)
    assert "_tabular_text_is_dropped" in rule, (
        "факт считается не тем правилом, по которому собирается промпт — они разойдутся"
    )


# --- карта репозитория ≠ содержимое ---------------------------------------------------- #
#
# 🔴 ЖИВАЯ ЖАЛОБА, СТОИВШАЯ ЧЕЛОВЕКУ ВСЕЙ РАБОТЫ С АРХИВОМ. Он загрузил `src.zip`, получил
# песочницу и не смог с ней ничего сделать: «ни посмотреть что внутри, ничего, никакого
# интерактива». Причина — здесь, а не в песочнице: для архива в контексте лежит КАРТА
# репозитория, признак «текст вложения есть» был ИСТИНОЙ, и решатель по правилу «читать
# инструментами не нужно» снимал все девять `ws_*` ДО прогона. Агент отвечал общими
# рассуждениями об архитектуре, потому что посмотреть код ему было нечем.

REPO_MAP = "# Graph Report\n\n## God Nodes\n- foo.py: 12 связей\n"


def test_a_repo_map_is_not_reported_as_attachment_text():
    """🔴 ГЛАВНОЕ. Карта непуста, но кода в ней нет — и решателю говорят именно это."""
    prompt = build_auto_input(
        user_input="отревьюй этот код",
        today="2026-07-30",
        attachments=[{"kind": "document", "filename": "src.zip"}],
        attachment_text_in_prompt=True,
        attachment_text_in_prompt_is_a_map=True,
    )

    assert "только КАРТА репозитория" in prompt, "решателю не сказали, что кода он не увидит"
    assert "текст вложения В КОНТЕКСТЕ ЕСТЬ" not in prompt, (
        "признак снова утверждает, что содержимое в контексте — по нему инструменты снимут"
    )


def test_an_ordinary_document_still_reports_its_text():
    """🔴 ГРАНИЦА. «Починка», после которой файловые инструменты выдаются на КАЖДЫЙ pdf,
    стоит денег в каждом запросе — ровно то, от чего гейт и заводили."""
    prompt = build_auto_input(
        user_input="сделай саммери",
        today="2026-07-30",
        attachments=[{"kind": "document", "filename": "тз.pdf"}],
        attachment_text_in_prompt=True,
        attachment_text_in_prompt_is_a_map=False,
    )

    assert "текст вложения В КОНТЕКСТЕ ЕСТЬ" in prompt
    assert "КАРТА репозитория" not in prompt


def test_the_rule_for_a_map_is_in_the_prompt():
    """⚠️ Признак без правила бесполезен: решатель прочитает незнакомую строку и решит по
    прежним двум случаям, то есть как раньше."""
    from service.domain.routing.auto_prompt import auto_prompt

    text = auto_prompt()

    # ⚠️ Переносы сминаем: промпт свёрстан по ширине, и правило не должно зависеть от того,
    # где оказался разрыв. Проверка дважды краснела именно на вёрстке, а не на смысле.
    flat = " ".join(text.split())

    assert "только КАРТА репозитория" in text, "случая «виден лишь скелет кода» в правиле нет"
    assert "нет ни одной строки" in flat
    # 🔴 ПРИОРИТЕТ НАД СПИСКОМ `false` — ПРОВЕРЕН ЗАМЕРОМ, А НЕ ПРЕДПОЛОЖЕН. Правило про
    # карту стояло рядом со строкой «false: „объясни“», и на «покажи код функции и объясни
    # построчно» решатель выбирал СПИСОК: `files_tool: false`, инструментов у модели нет,
    # и она восемь раз полезла за кодом в интернет. Без явного «это правило сильнее» новый
    # случай просто проигрывает соседнему.
    assert "СИЛЬНЕЕ СПИСКА false" in text, (
        "правило про карту не объявлено сильнее списка «false» — на «объясни» решатель "
        "снова снимет файловые инструменты, и агент пойдёт искать код в сети"
    )


def test_the_map_is_recognised_by_its_own_markers():
    """⚠️ Признак считает ТОТ ЖЕ помощник, что приписывает инструкцию к карте: два
    независимых определения «это карта» однажды разошлись бы, и одно осталось бы врать."""
    from service.application.processor_steps import is_repo_map

    assert is_repo_map(REPO_MAP) is True
    assert is_repo_map("# Graph Report\nбез второй секции") is False
    assert is_repo_map("обычный текст документа") is False
    assert is_repo_map(None) is False


def test_a_repo_map_turns_on_file_tools_by_code_not_by_persuasion():
    """🔴 ГЛАВНОЕ, И ЭТО ОБОШЛОСЬ В ПЯТЬ ЗАМЕРОВ. Формулировку правила в промпте я правил
    трижды, включая явное «это правило сильнее списка false»; решатель на «покажи код
    функции Session.request и объясни построчно» ВСЁ РАВНО отвечал `files_tool: false`.
    Инструментов у модели не оставалось, и она восемь раз ходила за кодом в интернет,
    обещая «сейчас найду в локальных файлах». Человек ответа не получал.

    Если в контексте только карта — прочитать код можно ИСКЛЮЧИТЕЛЬНО инструментом. Это
    факт о наличии данных, а не оценка намерения, и решаться он обязан кодом.
    """
    from service.domain.pipeline.auto_mode import _code_is_unreadable_without_tools

    assert _code_is_unreadable_without_tools(True) is True
    assert _code_is_unreadable_without_tools(False) is False


def test_the_forced_flag_survives_a_refusing_decider():
    """🔴 ТОЧКА ВЫЗОВА, САМАЯ ВАЖНАЯ ЗДЕСЬ. Правило верно, а `files_tool` собирается из
    ответа решателя — и принудительное включение теряется ровно там, где нужно.

    Разбираем ДЕРЕВО: `decision.needs_files or explicit_files` — именно эта форма и
    означает «отказ решателя не отменяет факта».
    """
    import ast
    import inspect

    from service.domain.pipeline import auto_mode

    src = inspect.getsource(auto_mode.resolve_auto_plan)
    tree = ast.parse(src.strip())

    forced = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and any(getattr(v, "id", "") == "explicit_files" for v in node.values)
    ]

    assert forced, (
        "`files_tool` больше не объединяется с принудительным включением — отказ решателя "
        "снова оставит агента без единого способа прочитать код"
    )


def test_forcing_is_computed_from_the_map_fact():
    """⚠️ Признак карты обязан ДОЕЗЖАТЬ до правила: посчитанный и не использованный факт —
    это ровно то, что уже случалось у меня трижды."""
    import ast
    import inspect

    from service.domain.pipeline import auto_mode

    tree = ast.parse(inspect.getsource(auto_mode.resolve_auto_plan).strip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_code_is_unreadable_without_tools"
    ]

    assert calls, "правило объявлено, но не вызывается — карта снова ни на что не влияет"
    assert any(
        getattr(a, "id", "") == "attachment_text_in_prompt_is_a_map" for c in calls for a in c.args
    ), "правило зовётся не с признаком карты — оно будет отвечать про что-то другое"


def test_ordinary_chat_is_not_forced_into_file_tools():
    """🔴 ГРАНИЦА И ДЕНЬГИ. Девять схем `ws_*` в каждом запросе — не то, что нужно чату без
    вложений. Правило срабатывает ТОЛЬКО на карте репозитория."""
    from service.domain.pipeline.auto_mode import (
        _code_is_unreadable_without_tools,
        _explicitly_asks_for_files,
    )

    assert not _code_is_unreadable_without_tools(False)
    assert not _explicitly_asks_for_files("привет, как дела")


def test_the_map_fact_is_computed_at_the_call_site():
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а решателю уезжает `False` — и всё остаётся как было.
    Этот класс переживал мои мутации трижды, поэтому проверяется отдельно.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым я же и объяснил правку.
    """
    import ast
    import inspect

    from service.application import processor_steps as ps

    tree = ast.parse(inspect.getsource(ps.ProcessorStepsMixin._resolve_route_and_plan).strip())
    passed = [
        kw
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "attachment_text_in_prompt_is_a_map"
    ]

    assert passed, "признак карты решателю не уезжает вовсе — правило мертво"
    assert any(
        isinstance(kw.value, ast.Call) and getattr(kw.value.func, "id", "") == "is_repo_map"
        for kw in passed
    ), "признак считается не тем правилом (или захардкожен) — он разойдётся с промптом"
