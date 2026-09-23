import inspect
from types import SimpleNamespace

from service.domain.base import SimpleStreamingAgent
from service.domain.text_stream import iter_stream_chunks


def test_extract_text_from_sdk_event_supports_responses_delta_shape() -> None:
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="Привет"),
    )

    out = SimpleStreamingAgent._extract_text_from_sdk_event(event)

    assert out == "Привет"


def test_extract_text_from_sdk_event_ignores_completed_item_shape() -> None:
    """Сводка завершённого item'а — НЕ дельта, стримить её нельзя.

    `item.content` приходит в конце ответа и содержит текст целиком. Раньше он тоже
    извлекался, и уже отстримленные токены дублировались вторым проходом. Теперь
    извлекаются только delta-подтипы (см. _extract_text_from_sdk_event).
    """
    content_item = SimpleNamespace(text="Текст из item.content")
    raw = SimpleNamespace(item=SimpleNamespace(content=[content_item]))
    event = SimpleNamespace(type="raw_response_event", data=raw)

    assert SimpleStreamingAgent._extract_text_from_sdk_event(event) is None


def test_extract_text_from_sdk_event_ignores_non_delta_events() -> None:
    """Не-raw события (завершение run-item, смена агента) текста не несут."""
    event = SimpleNamespace(
        type="run_item_stream_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="дубль"),
    )

    assert SimpleStreamingAgent._extract_text_from_sdk_event(event) is None


def test_fallback_chunking_preserves_markdown_exactly() -> None:
    r"""⚠️ РЕГРЕССИЯ: у аварийного пути был СВОЙ чанкер, и он портил разметку.

    `SimpleStreamingAgent._split_text_chunks` резал строго по `chunk_size` и делал
    `strip()` на границах — то есть склейка чанков НЕ воспроизводила исходный текст.
    На практике: таблица рвалась посреди строки (`| a | b` + `|\n|---|`), а у кода
    терялись отступы (`    return 1` → `return` + `1`). Видел это пользователь: аварийный
    путь отдаёт ПОЛНЫЙ ответ модели — с кодом и таблицами.

    Рядом всё это время лежал `iter_stream_chunks` с ровно такими инвариантами (точная
    склейка, не режет внутри фенсов и табличных строк). Теперь аварийный путь пользуется
    им; здесь закреплено, ЧТО именно чинилось.
    """
    table = "Заголовок\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    code = "Вот код:\n\n```python\ndef f():\n    return 1\n```\n\nКонец.\n"

    for source in (table, code):
        assert "".join(iter_stream_chunks(source, chunk_size=20)) == source


def test_fallback_path_uses_the_shared_chunker() -> None:
    """⚠️ Проверка МЕСТА ВЫЗОВА, а не только самой функции.

    Первая версия соседнего теста дёргала `iter_stream_chunks` напрямую — и оставалась
    зелёной, если аварийный путь вернуть к своей нарезке. Мутация это показала: подменил
    вызов в `sdk_run.py` на резку по размеру со `strip()` — тесты не заметили.

    Проверка структурная, и это осознанно: разыграть аварийную ветку целиком означало бы
    поднять Agents SDK, заставить его отдать ноль чанков и подсунуть ответ провайдера —
    столько мокинга проверяло бы в основном сам мок. Здесь закреплено ровно то, что
    ломалось: у агента больше НЕТ своей нарезки, а аварийный путь зовёт общую.
    """
    from service.domain.runners import sdk_run

    assert not hasattr(SimpleStreamingAgent, "_split_text_chunks"), (
        "вернулась своя нарезка — она теряет пробелы и режет внутри фенсов"
    )
    assert "iter_stream_chunks(" in inspect.getsource(sdk_run.SdkRunMixin)
