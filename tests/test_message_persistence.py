"""Метаданные сообщения переживают перезагрузку страницы.

Симптом был такой: после F5 у каждого сообщения пропадали токены и кредиты, исчезали
вложения, а сгенерированное изображение переставало отображаться.

Причина одна на все три: колонка `metadata` (JSONB) в `chat_messages` была с самой первой
миграции, но в неё НИКОГДА не писали. usage уходил только в WS-событие и в строку джоба;
история отдавала ровно sender/content/created_at. Всё остальное жило в стейте React и
умирало вместе с ним — пользователь терял то, за что заплатил.
"""

import json
from types import SimpleNamespace

import pytest

# ⚠️ Импорт из НАСТОЯЩЕГО места (`chat_worker/message_meta.py`), а не транзитом через
# воркер: транзитный импорт ломается при любом выносе, хотя правила не менялись.
from service.services.chat.infrastructure.chat_worker.message_meta import (
    build_public_usage_meta,
    persistable_meta,
    user_message_meta,
)
from service.services.chat.persistence.chat_persistence_service import ChatPersistenceService
from service.services.chat.persistence.chat_worker_repository import ChatWorkerRepository


# --------------------------------------------------------------------------- #
# usage: токены, кредиты, ВРЕМЯ ВЫПОЛНЕНИЯ                                     #
# --------------------------------------------------------------------------- #
def test_usage_meta_carries_duration():
    """Время выполнения не замерялось нигде: единственный perf_counter в проекте
    складывал результат в `_latency` и выбрасывал."""
    meta = build_public_usage_meta(
        {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        charged_credits=7,
        model="gpt-4o-mini",
        duration_ms=3400,
    )
    assert meta == {
        "prompt": 100,
        "completion": 20,
        "total": 120,
        "model": "gpt-4o-mini",
        "credits": 7,
        "duration_ms": 3400,
    }


def test_usage_meta_reports_duration_even_without_tokens():
    """«Сколько это заняло» — законный вопрос сам по себе (кэш, сбой провайдера)."""
    meta = build_public_usage_meta({}, charged_credits=0, model="m", duration_ms=1200)
    assert meta["duration_ms"] == 1200


def test_usage_meta_is_none_when_there_is_nothing_to_show():
    assert build_public_usage_meta({}, charged_credits=0, model="m") is None


# --------------------------------------------------------------------------- #
# Что именно кладём в БД                                                       #
# --------------------------------------------------------------------------- #
def test_persistable_meta_keeps_what_ui_renders():
    meta = persistable_meta(
        {
            "usage": {"total": 120, "credits": 7},
            "selected_model": "GigaChat-3-Lightning",
            "generated_files": [
                {"file_key": "k1", "file_url": "https://presigned", "kind": "image"}
            ],
            "model_routing": {"tool": "image_gen"},
            "internal_junk": "не нужно",
        },
        "https://presigned",
    )
    assert meta["usage"]["credits"] == 7
    assert meta["selected_model"] == "GigaChat-3-Lightning"
    assert meta["generated_files"][0]["file_key"] == "k1"
    assert meta["file_url"] == "https://presigned"
    assert "internal_junk" not in meta


def test_persistable_meta_drops_heavy_blobs():
    """b64 картинки/презентации в БД не нужны — файл уже лежит в сторе."""
    meta = persistable_meta({"pptx_b64": "A" * 10_000, "usage": {"total": 1}}, None)
    assert "pptx_b64" not in meta


def test_user_message_meta_keeps_names_not_content():
    """Текст вложения уже разобран и уехал в контекст и граф — копия в каждом
    сообщении раздувала бы таблицу ради того, что и так есть."""
    meta = user_message_meta(
        [
            {"name": "dogovor.pdf", "kind": "document", "content": "огромный текст" * 1000},
            {"name": "", "kind": "document"},  # без имени — мусор, пропускаем
        ]
    )
    assert meta == {"attachments": [{"filename": "dogovor.pdf", "file_type": "document"}]}
    assert "content" not in json.dumps(meta)


def test_user_message_meta_empty_when_no_attachments():
    assert user_message_meta(None) == {}
    assert user_message_meta([]) == {}


# --------------------------------------------------------------------------- #
# Запись: metadata реально уходит в INSERT                                     #
# --------------------------------------------------------------------------- #
class _FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        if "chat_threads" in str(statement):
            return SimpleNamespace(first=lambda: (42,))
        return SimpleNamespace(first=lambda: None)


@pytest.mark.asyncio
async def test_persist_turn_writes_metadata_column():
    session = _FakeSession()
    ok = await ChatWorkerRepository().persist_turn(
        db_session=session,
        thread_id="t1",
        user_text="привет",
        assistant_text="ответ",
        user_id=None,
        user_metadata={"attachments": [{"filename": "a.pdf", "file_type": "document"}]},
        assistant_metadata={"usage": {"total": 120, "credits": 7, "duration_ms": 3400}},
    )
    assert ok

    inserts = [(sql, p) for sql, p in session.calls if "chat_messages" in sql]
    assert len(inserts) == 2

    user_sql, user_params = inserts[0]
    assert "metadata" in user_sql
    assert json.loads(user_params["meta"])["attachments"][0]["filename"] == "a.pdf"

    _, assistant_params = inserts[1]
    saved = json.loads(assistant_params["meta"])
    assert saved["usage"]["credits"] == 7
    assert saved["usage"]["duration_ms"] == 3400
    # content_tokens — тоже была и тоже не заполнялась.
    assert assistant_params["tokens"] == 120


# --------------------------------------------------------------------------- #
# Чтение: пресайн-ссылка ПЕРЕВЫПУСКАЕТСЯ                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_history_reissues_expired_presigned_url():
    """Сохранённая намертво ссылка протухает и отдаёт 403 — для пользователя это
    выглядело бы как «картинка опять пропала». Якорь — file_key."""

    class _Files:
        async def get_presigned_url_by_key(self, *, file_key):
            return f"https://fresh/{file_key}"

    service = ChatPersistenceService(repository=None, file_service=_Files())
    meta = await service._refresh_artifact_links(
        {
            "generated_files": [{"file_key": "k1", "file_url": "https://stale"}],
            "file_url": "https://stale",
        }
    )

    assert meta["generated_files"][0]["file_url"] == "https://fresh/k1"
    assert meta["file_url"] == "https://fresh/k1"


@pytest.mark.asyncio
async def test_history_survives_storage_failure():
    """Стор недоступен — отдаём что сохранено, а не роняем историю."""

    class _Files:
        async def get_presigned_url_by_key(self, *, file_key):
            raise RuntimeError("S3 недоступен")

    service = ChatPersistenceService(repository=None, file_service=_Files())
    meta = await service._refresh_artifact_links(
        {"generated_files": [{"file_key": "k1", "file_url": "https://stale"}]}
    )
    assert meta["generated_files"][0]["file_url"] == "https://stale"


@pytest.mark.asyncio
async def test_history_without_artifacts_is_untouched():
    service = ChatPersistenceService(repository=None, file_service=None)
    meta = {"usage": {"total": 10}}
    assert await service._refresh_artifact_links(meta) == meta


def test_mode_offer_survives_reload_without_duplicating_the_request_text():
    """🔴 Кнопка «запустить дорогой режим» обязана пережить перезагрузку страницы.

    Предложение — это решение о тысячах кредитов, отложенное до клика человека. Без
    персиста оно исчезает после F5, и человек даже не узнает, что «Авто» что-то
    предлагал: тот же класс дефекта, что уже чинили для кольца контекста.
    """
    meta = persistable_meta(
        {"mode_offer": {"mode": "deep_research", "prompt": "изучи рынок", "label": "иссл."}},
        None,
    )

    assert meta["mode_offer"]["mode"] == "deep_research"
    assert "prompt" not in meta["mode_offer"]


def test_auto_mode_metadata_redacts_legacy_reason_and_unknown_codes():
    marker = "synthetic-model-rationale-must-not-persist"
    meta = persistable_meta(
        {
            "mode_offer": {
                "mode": "deep_research",
                "reason": marker,
                "reason_code": "not-a-policy-code",
            }
        },
        None,
    )

    assert meta["mode_offer"] == {"mode": "deep_research"}
    assert marker not in str(meta)
