"""Russian support in memory extraction (GPTHub).

Why this exists: `detect_lang()` only ever returned "zh" or "en". Russian text has no
Han characters, so it fell into "en" and the extractor ran with the English prompt and
English few-shot examples — clean Russian facts came back as English summary blobs.
Migration 013_user_memory_facts in the GPTHub backend exists solely to work around it.

The dangerous part of adding "ru" is that prompt dictionaries are read by DIRECT
INDEXING (`PROMPT_DICT["chat"][lang]`), not `.get()` — so any dictionary that lacks a
"ru" entry turns into a runtime KeyError the moment detect_lang starts returning it.
These tests pin both halves: detection, and the absence of KeyErrors anywhere.
"""

import pytest

from memos.mem_reader.read_multi_modal.utils import detect_lang, pick_by_lang
from memos.mem_reader.utils import derive_key


RUSSIAN = (
    "Привет! Вчера в три часа дня у меня была встреча с командой по новому проекту. "
    "Переживаю, что бэкенд будет готов только 10 декабря."
)
ENGLISH = "Hi Jerry! Yesterday at 3 PM I had a meeting with my team about the new project."
CHINESE = "嗨Jerry！昨天下午3点我和团队开了个会，讨论新项目。"


# --------------------------------------------------------------------------- #
# detect_lang                                                                  #
# --------------------------------------------------------------------------- #
def test_detects_russian():
    assert detect_lang(RUSSIAN) == "ru"


def test_english_and_chinese_still_detected():
    """Регресс: добавление русского не должно ломать существующие языки."""
    assert detect_lang(ENGLISH) == "en"
    assert detect_lang(CHINESE) == "zh"


def test_russian_with_role_and_timestamp_prefixes():
    """Реальный вход — окно диалога с ролевыми и временными префиксами."""
    windowed = "user: [2026-07-14 12:37]: Меня зовут Денис, я работаю над GPTHub."
    assert detect_lang(windowed) == "ru"


@pytest.mark.parametrize("text", ["", None, "   ", "12345 !!! ???"])
def test_degenerate_input_falls_back_to_english(text):
    assert detect_lang(text) == "en"


def test_latin_technical_terms_do_not_flip_russian_to_english():
    """Русский текст с латинскими терминами всё равно русский."""
    mixed = "Пользователь развернул backend на Docker и настроил CI через GitHub Actions."
    assert detect_lang(mixed) == "ru"


# --------------------------------------------------------------------------- #
# Словари промптов: "ru" обязан быть ВЕЗДЕ (иначе KeyError в рантайме)         #
# --------------------------------------------------------------------------- #
def test_simple_struct_prompt_dict_has_russian_everywhere():
    from memos.mem_reader.simple_struct import PROMPT_DICT

    for section in ("chat", "doc", "general_string", "custom_tags"):
        assert "ru" in PROMPT_DICT[section], f"PROMPT_DICT[{section!r}] без 'ru' → KeyError"
    assert "ru_example" in PROMPT_DICT["chat"]


def test_strategy_prompt_dict_has_russian_everywhere():
    from memos.mem_reader.strategy_struct import STRATEGY_PROMPT_DICT

    for section in ("chat", "doc", "custom_tags"):
        assert "ru" in STRATEGY_PROMPT_DICT[section]
    assert "ru_example" in STRATEGY_PROMPT_DICT["chat"]


def test_doc_prompt_dict_has_russian_everywhere():
    from memos.mem_reader.read_multi_modal.file_content_parser import DOC_PROMPT_DICT

    for section in ("doc", "custom_tags"):
        assert "ru" in DOC_PROMPT_DICT[section]


def test_russian_prompts_keep_their_placeholders():
    """Промпт без плейсхолдера молча уедет в LLM с ${conversation} внутри."""
    from memos.templates.mem_reader_prompts import (
        CUSTOM_TAGS_INSTRUCTION_RU,
        GENERAL_STRUCT_STRING_READER_PROMPT_RU,
        SIMPLE_STRUCT_DOC_READER_PROMPT_RU,
        SIMPLE_STRUCT_MEM_READER_PROMPT_RU,
    )

    assert "${conversation}" in SIMPLE_STRUCT_MEM_READER_PROMPT_RU
    assert "${custom_tags_prompt}" in SIMPLE_STRUCT_MEM_READER_PROMPT_RU
    for placeholder in ("{chunk_text}", "{context}", "{custom_tags_prompt}"):
        assert placeholder in SIMPLE_STRUCT_DOC_READER_PROMPT_RU
    for placeholder in ("{chunk_text}", "{custom_tags_prompt}"):
        assert placeholder in GENERAL_STRUCT_STRING_READER_PROMPT_RU
    assert "{custom_tags}" in CUSTOM_TAGS_INSTRUCTION_RU


def test_russian_prompt_examples_are_actually_in_russian():
    """Few-shot примеры тянут язык вывода сильнее, чем строка-инструкция. Английские
    примеры в русском промпте свели бы всю правку на нет."""
    from memos.templates.mem_reader_prompts import SIMPLE_STRUCT_MEM_READER_EXAMPLE_RU

    assert detect_lang(SIMPLE_STRUCT_MEM_READER_EXAMPLE_RU) == "ru"


# --------------------------------------------------------------------------- #
# pick_by_lang — осознанная деградация второстепенных подсистем в английский   #
# --------------------------------------------------------------------------- #
def test_pick_by_lang_uses_exact_language_when_present():
    assert pick_by_lang({"en": "E", "zh": "Z", "ru": "R"}, "ru") == "R"


def test_pick_by_lang_degrades_to_english_when_language_missing():
    """Второстепенные подсистемы (feedback, preference, chain-of-thought) русских
    промптов не имеют — они обязаны падать в английский, а НЕ в KeyError."""
    assert pick_by_lang({"en": "E", "zh": "Z"}, "ru") == "E"


def test_search_path_never_keyerrors_on_russian():
    """Самое опасное место: COT_DICT на пути ПОИСКА. KeyError здесь убил бы recall
    для всех русских запросов целиком."""
    from memos.memories.textual.tree_text_memory.retrieve.searcher import COT_DICT

    lang = detect_lang(RUSSIAN)
    for mode in ("fine", "fast"):
        assert pick_by_lang(COT_DICT[mode], lang), f"COT_DICT[{mode}] упал на lang={lang}"


# --------------------------------------------------------------------------- #
# derive_key — сплиттер предложений не знал русской точки                      #
# --------------------------------------------------------------------------- #
def test_derive_key_splits_russian_sentence():
    """Раньше терминаторами были только [。！？!?] — русская точка отсутствовала, и
    «первым предложением» становился весь абзац до перевода строки."""
    text = "Пользователя зовут Денис. Он работает над проектом GPTHub и живёт в Москве."
    assert derive_key(text) == "Пользователя зовут Денис"


def test_derive_key_still_splits_english_and_chinese():
    assert derive_key("The user is Denis. He works on GPTHub.") == "The user is Denis"
    assert derive_key("用户叫Denis。他在做GPTHub项目。") == "用户叫Denis"


# --------------------------------------------------------------------------- #
# Salvage-путь: главный источник мусора, описанного в миграции 013             #
# --------------------------------------------------------------------------- #
RAW_WINDOW = (
    "user: [2026-07-14 12:37]: Меня зовут Денис. Я работаю над GPTHub.\n"
    "assistant: [2026-07-14 12:38]: Понял, записал."
)


def test_window_prefixes_are_stripped():
    """`role: [timestamp]: ` — это формат ТРАНСПОРТА, а не слова пользователя."""
    from memos.mem_reader.simple_struct import _strip_window_prefixes

    cleaned = _strip_window_prefixes(RAW_WINDOW)
    assert "user:" not in cleaned
    assert "[2026-07-14" not in cleaned
    assert cleaned.startswith("Меня зовут Денис")


def test_salvage_key_is_a_phrase_not_transport_junk():
    """Когда JSON от модели не распарсился, salvage раньше писал key = mem_str[:10] по
    СЫРОМУ окну → получался ключ «user: [20». Это ровно те «служебные префиксы вроде
    «37»», на которые жалуется миграция 013_user_memory_facts."""
    from memos.mem_reader.simple_struct import _strip_window_prefixes

    old_style_key = RAW_WINDOW[:10]
    assert old_style_key == "user: [202"  # как было — мусор из формата транспорта

    new_key = derive_key(_strip_window_prefixes(RAW_WINDOW))
    assert new_key == "Меня зовут Денис"
    assert "user" not in new_key and "[" not in new_key
