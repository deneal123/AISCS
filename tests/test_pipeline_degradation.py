"""Деградация конвейера ВИДНА, а не проглатывается.

⚠️ Общая беда трёх случаев ниже: наружу они выглядят как успех. Прогресс-бар зелёный,
шаги «выполнены», статус «Разобрано» — а ответ собран без половины входных данных.
Отличить это от нормальной работы было нечем: ни лога, ни отметки в событии.

Именно поэтому проверки смотрят на ЛОГИ и МЕТАДАННЫЕ, а не только на возвращаемое
значение: возвращаемое значение при деградации как раз правдоподобное.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from service.domain.pipeline import decomposition, execution_plan, multimodal
from service.schemas.agents import ModalityAttachment


# --------------------------------------------------------------------------- #
# Контекст предыдущих шагов                                                     #
# --------------------------------------------------------------------------- #
def test_failed_augment_is_logged(caplog):
    """⚠️ Шаг N не увидел шаг N-1 — об этом обязан быть след.

    Возврат исходного контекста означает, что последовательная ветка потеряла ровно то,
    ради чего она существует. Наружу — связный прогресс и бессвязный ответ.
    """

    class _Broken:
        system_context = "БАЗА"

        def model_copy(self, **_kw):
            raise RuntimeError("копия не удалась")

    original = _Broken()
    with caplog.at_level(logging.WARNING):
        result = execution_plan._augment_context(original, [("web_search", "нашёл X")])

    assert result is original, "поведение прежнее: работаем без контекста предыдущих шагов"
    assert any("execution context unavailable" in r.message for r in caplog.records), (
        "сбой не попал в логи"
    )


def test_successful_augment_says_nothing(caplog):
    """⚠️ Штатный путь молчит — иначе предупреждение станет фоновым шумом."""

    class _Ctx:
        system_context = "БАЗА"

        def model_copy(self, *, update):
            new = _Ctx()
            new.system_context = update["system_context"]
            return new

    with caplog.at_level(logging.WARNING):
        result = execution_plan._augment_context(_Ctx(), [("web_search", "нашёл X")])

    assert "нашёл X" in result.system_context
    assert not caplog.records


# --------------------------------------------------------------------------- #
# Декомпозиция мульти-интента                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_decomposition_failure_is_visible(monkeypatch, caplog):
    """⚠️ Сбой уровня WARNING, а не DEBUG.

    На типовом INFO постоянно ломающаяся декомпозиция не оставляла НИ ОДНОЙ записи, а
    пользователь видел «включил тумблер мульти-интента — получил обычный ответ».
    """
    import service.domain.client as client_mod

    async def _boom():
        raise RuntimeError("список моделей недоступен")

    monkeypatch.setattr(client_mod, "list_qualified_models", _boom)

    with caplog.at_level(logging.WARNING):
        out = await decomposition.decompose_intents("найди X, затем сделай презентацию")

    assert out is None, "fail-open сохранён: идём одиночным маршрутом"
    assert any("decomposition unavailable" in r.message for r in caplog.records), (
        "сбой декомпозиции не виден в логах — жалоба «кнопка не работает» неотличима"
    )


@pytest.mark.asyncio
async def test_single_intent_is_not_an_error(caplog):
    """Одиночный запрос отсекается пре-фильтром БЕЗ шума: это не сбой."""
    with caplog.at_level(logging.WARNING):
        assert await decomposition.decompose_intents("просто ответь на вопрос") is None

    assert not caplog.records


# --------------------------------------------------------------------------- #
# Веер по модальностям                                                          #
# --------------------------------------------------------------------------- #
def _attachments():
    return [
        ModalityAttachment(kind="document", name="a.md", content="содержимое А " * 50),
        ModalityAttachment(kind="code", name="b.py", content="print(1)"),
    ]


@pytest.mark.asyncio
async def test_cancelled_analyst_does_not_kill_the_whole_request(monkeypatch, caplog):
    """⚠️ ГЛАВНОЕ: отмена ОДНОГО аналитика не роняет запрос.

    `gather(return_exceptions=True)` кладёт в результаты и `CancelledError`, а она
    наследует BaseException, не Exception. Прежняя проверка `isinstance(res, Exception)`
    её пропускала, распаковка падала с TypeError — и весь запрос умирал вместе с уже
    оплаченными разборами остальных вложений.
    """

    class _Analyst:
        def __init__(self, kind):
            self.kind = kind

        async def analyze(self, *, user_input, name, content, execution=None):
            if name == "a.md":
                raise asyncio.CancelledError
            if execution is not None:
                execution.usage.record_usage(
                    {"prompt": 10, "completion": 5}, model="m", kind="multimodal_usage"
                )
            return f"разбор {name}"

    monkeypatch.setattr(multimodal, "get_modality_analyst", lambda kind: _Analyst(kind))

    with caplog.at_level(logging.WARNING):
        aggregated, events = await multimodal.run_modality_fanout(
            attachments=_attachments(), user_input="вопрос"
        )

    assert "разбор b.py" in aggregated, "уцелевший разбор потерян"
    assert "содержимое А" in aggregated, "для отменённого не подставлен сырой текст"
    assert any("CancelledError" in r.message or "не удался" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_degraded_attachment_is_marked_in_the_event(monkeypatch):
    """⚠️ Статус не врёт: при сыром тексте это НЕ «Разобрано».

    Раньше писалось «Разобрано» безусловно — пользователь видел галочку, качество
    ответа падало, и связать одно с другим было нечем.
    """

    class _Analyst:
        def __init__(self, kind):
            self.kind = kind

        async def analyze(self, *, user_input, name, content, execution=None):
            if name == "a.md":
                raise RuntimeError("аналитик упал")
            return f"разбор {name}"

    monkeypatch.setattr(multimodal, "get_modality_analyst", lambda kind: _Analyst(kind))

    _, events = await multimodal.run_modality_fanout(
        attachments=_attachments(), user_input="вопрос"
    )

    per_file = {e.metadata.get("name"): e for e in events if (e.metadata or {}).get("name")}
    assert per_file["a.md"].metadata.get("degraded") == "analyst_failed"
    assert "Разобрано" not in str(per_file["a.md"].data)
    assert per_file["b.py"].metadata.get("degraded") is None
    assert "Разобрано" in str(per_file["b.py"].data), "успешный разбор помечен как сбой"


@pytest.mark.asyncio
async def test_raw_fallback_is_trimmed(monkeypatch):
    """⚠️ Сырой файл обрезается: иначе дамп вытеснит из окна остальные вложения."""

    class _Analyst:
        def __init__(self, kind):
            self.kind = kind

        async def analyze(self, *, user_input, name, content, execution=None):
            raise RuntimeError("упал")

    monkeypatch.setattr(multimodal, "get_modality_analyst", lambda kind: _Analyst(kind))
    huge = ModalityAttachment(kind="document", name="big.md", content="слово " * 20000)

    aggregated, _ = await multimodal.run_modality_fanout(
        attachments=[huge, huge], user_input="вопрос"
    )

    from service.shared.token_budget import estimate_tokens

    assert estimate_tokens(aggregated) < 2 * multimodal._RAW_FALLBACK_TOKENS + 500, (
        "сырой фолбэк не обрезан — окно забьётся дампом файла"
    )
