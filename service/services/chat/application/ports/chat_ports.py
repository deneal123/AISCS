from __future__ import annotations

from typing import Protocol

from service.services.chat.domain.chat_contracts import (
    ChatReplyResult,
    ChatRequestContext,
    JobExecutionResult,
)


class ChatMessageProcessorPort(Protocol):
    async def execute(self, context: ChatRequestContext) -> ChatReplyResult: ...


class ChatPersistencePort(Protocol):
    async def create_thread(
        self, user_id: str | int | None, title: str | None, thread_id: str | None = None
    ) -> dict: ...
    async def persist_messages(
        self,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        user_id: str | int | None = None,
        # Вложения реплики пользователя: без них фолбэк-путь терял файл при перезагрузке.
        user_metadata: dict | None = None,
    ) -> None: ...
    async def get_messages(self, thread_id: str, page: int = 1, per_page: int = 50) -> dict: ...
    async def list_threads(
        self, user_id: str | int | None = None, page: int = 1, per_page: int = 50
    ) -> dict: ...
    async def delete_thread(self, thread_id: str) -> bool: ...
    async def update_thread_title(self, thread_id: str, title: str) -> bool: ...
    async def get_thread_owner(self, thread_id: str) -> str | int | None: ...


# ⚠️ Порты ниже РАСХОДИЛИСЬ с реализациями: `attachments` и `routing_usage`
# передаются вызывающим (`chat_service.py`) и принимаются обеими реализациями, но в
# протоколах объявлены не были. Работало это лишь потому, что Protocol не проверяется
# в рантайме, а mypy в pre-commit ни разу не выполнялся.
#
# Важнее самой ошибки то, во что она превращала страж: `test_ports_contracts.py`
# заявлен как защита от молчаливого изменения портов — а сверялся с описанием,
# которое уже не соответствовало коду.


class ChatStreamingPort(Protocol):
    async def execute(
        self,
        thread_id: str,
        text: str,
        user_id: str | int | None,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        file_context: str,
        route_override: str | None,
        attachments: list | None = None,
        # 🔴 ФАЙЛЫ И СОГЛАСИЕ НА ДОРОГОЕ — В КОНТРАКТЕ, а не только в реализации.
        # Схема HTTP-ручки их принимала, а до воркера они не доезжали: замер сквозным
        # прогоном дал «пришлите код функции» на приложенный `.py`. Пропажа `file_ids`
        # гасит признак «новый файл» — а с ним песочницу, восстановление текста и
        # память треда; пропажа `watch_video` делает способность недоступной по HTTP.
        file_ids: list[str] | None = None,
        watch_video: bool = False,
        confirm_expensive_run: bool = False,
    ) -> ChatReplyResult: ...


class ChatOrchestrationPort(Protocol):
    async def execute(
        self,
        thread_id: str,
        text: str,
        user_id: str | int | None,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        file_context: str,
        route_override: str | None,
        attachments: list | None = None,
        # 🔴 ФАЙЛЫ И СОГЛАСИЕ НА ДОРОГОЕ — В КОНТРАКТЕ, а не только в реализации.
        # Схема HTTP-ручки их принимала, а до воркера они не доезжали: замер сквозным
        # прогоном дал «пришлите код функции» на приложенный `.py`. Пропажа `file_ids`
        # гасит признак «новый файл» — а с ним песочницу, восстановление текста и
        # память треда; пропажа `watch_video` делает способность недоступной по HTTP.
        file_ids: list[str] | None = None,
        watch_video: bool = False,
        confirm_expensive_run: bool = False,
        confirmed_offer_id: str | None = None,
        # usage LLM-роутера, посчитанный в веб-процессе: воркер тарифицирует его
        # отдельным billing_event. Пропажа поля = недобилл, поэтому оно в контракте.
        routing_usage: dict | None = None,
        # Категория, уже выбранная авто-роутером сайдкара. Пропажа поля = сайдкар роутит
        # тот же текст вторым LLM-вызовом, то есть лишний вызов провайдера и 300-1500 мс
        # на каждом сообщении. Поэтому тоже в контракте, а не «просто аргумент».
        resolved_category: str | None = None,
    ) -> JobExecutionResult: ...
