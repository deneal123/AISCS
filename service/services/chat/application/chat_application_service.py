from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import HTTPException

from service.services.chat.application.error_handling import (
    map_to_http_exception,
    normalize_response_metadata,
)
from service.services.chat.application.use_cases.chat_use_cases import (
    CreateThreadUseCase,
    PostMessageUseCase,
)
from service.services.chat.domain.chat_service import ChatService
from service.services.chat.domain.confirmation_offer import ConfirmationOfferError
from service.settings import config

logger = logging.getLogger(__name__)


class ChatApplicationService:
    DEFAULT_STORAGE_ROOT = "/var/lib/app/storage"

    def __init__(self, chat_service: ChatService, file_service, redis_client=None) -> None:
        self.chat_service = chat_service
        self.file_service = file_service
        self.redis_client = redis_client

    async def _ensure_thread_owner(self, thread_id: str, requester_id: str) -> None:
        owner = await self.chat_service.persistence_service.get_thread_owner(thread_id)
        if owner is not None and str(owner) != str(requester_id):
            raise HTTPException(status_code=404, detail="Thread not found")

    async def ensure_thread_owner(self, thread_id: str, requester_id: str) -> None:
        """Публичная проверка владельца треда (для роутов вроде фидбэка)."""
        await self._ensure_thread_owner(thread_id, requester_id)

    async def post_message(self, thread_id: str, payload, requester_id: str) -> dict:
        await self._ensure_thread_owner(thread_id, requester_id)
        try:
            confirm_offer_id = str(getattr(payload, "confirm_offer_id", None) or "").strip()
            if confirm_offer_id:
                from service.services.chat.domain.confirmation_offer import read_confirmation_offer

                anchor = await read_confirmation_offer(
                    self.redis_client,
                    confirm_offer_id,
                    thread_id=thread_id,
                    user_id=requester_id,
                )
                payload = payload.model_copy(
                    update={
                        "text": anchor.text,
                        "user_id": requester_id,
                        "model": anchor.selected_model,
                        "route_override": anchor.route_override,
                        "input_type": anchor.input_type,
                        "attachments": list(anchor.attachments),
                        "file_ids": list(anchor.file_ids),
                        "confirm_expensive_run": True,
                        "confirm_offer_id": anchor.offer_id,
                        "confirmed_resolved_category": anchor.resolved_category,
                    }
                )
            else:
                if not str(getattr(payload, "text", "") or "").strip():
                    raise HTTPException(status_code=422, detail="Message text is required")
                payload.user_id = requester_id
            use_case = PostMessageUseCase(self.chat_service)
            result = await use_case.execute(thread_id=thread_id, payload=payload)
        except ConfirmationOfferError as exc:
            raise map_to_http_exception(exc) from exc
        except Exception as exc:
            logger.error(
                "chat message handling failed",
                extra={"component": "chat", "failure_code": "unavailable"},
            )
            raise map_to_http_exception(exc) from exc
        return {
            "reply": result.reply,
            "thread_id": result.thread_id,
            "metadata": normalize_response_metadata(
                result.metadata.data, selected_model=payload.model
            ),
        }

    async def create_thread(self, requester_id: str, title: str | None) -> dict:
        res = await CreateThreadUseCase(self.chat_service).execute(
            user_id=requester_id, title=title
        )
        return {
            "thread_id": res["thread_id"],
            "title": res["title"],
            "created_at": res.get("created_at"),
        }

    async def get_models(self) -> list[str]:
        """Список моделей для пикера — его знает САЙДКАР, он владеет провайдерами.

        ``chat_only=True`` обязателен: без фильтра в каталоге лежат ещё и эмбеддеры
        (замер: 422 против 335), и пользователь увидел бы в выборе ``Embeddings``.
        Фильтрация переехала туда же — чтобы список выбора и авто-подбор модели
        считались ОДНИМ критерием, а не двумя похожими.
        """
        from service.infrastructure.agents_client.sidecar_providers import (
            fetch_chat_model_catalog,
        )
        from service.settings import config as _cfg

        fetched = await fetch_chat_model_catalog(_cfg, chat_only=True)
        if fetched is None:
            # Пустой список хуже ошибки: пользователь решит, что моделей нет, и будет
            # ждать. Честный 503 говорит, что сломан сервис, а не выбор моделей.
            raise HTTPException(
                status_code=503, detail="Каталог моделей недоступен: сервис агентов не отвечает"
            )
        return list(fetched[0])

    async def get_personas(self) -> list[dict]:
        """Личности для селектора — их знает САЙДКАР, он владеет реестром и схемой.

        В отличие от каталога моделей, недоступный сайдкар здесь НЕ повод для 503:
        отсутствие личностей — рабочее состояние (их могло не быть объявлено вовсе),
        и ронять из-за него чат нельзя. Селектор просто не покажется.
        """
        from service.infrastructure.agents_client.sidecar_providers import fetch_persona_catalog
        from service.settings import config as _cfg

        return await fetch_persona_catalog(_cfg)

    async def get_models_catalog(self) -> list[dict]:
        """Наши модели, обогащённые публичными метаданными OpenRouter (контекст +
        возможности). Без цен.

        Метаданные ищутся с восстановлением по вариантам id (см. resolve_model_meta):
        нативный OpenAI отдаёт голые id, routerai — с суффиксом ``:exacto``, поэтому
        прямое совпадение с каталогом ловило только сам OpenRouter. Окно резолвится
        всегда (каталог → статическая карта → дефолт), иначе фронт не может показать
        заполнение контекста для gigachat/mws.
        """
        from service.services.chat.infrastructure.model_catalog import (
            TOOL_CAPABLE_ALLOWLIST,
            get_openrouter_catalog,
            resolve_context_window_ex,
            resolve_model_meta,
        )
        from service.shared.model_class import cost_rank

        models = await self.get_models()
        catalog = await get_openrouter_catalog()
        out: list[dict] = []
        for mid in models:
            meta = resolve_model_meta(mid, catalog)
            caps = list(meta.get("capabilities") or [])
            # tool-capability у провайдеров без метаданных — по курируемому allowlist.
            if mid in TOOL_CAPABLE_ALLOWLIST and "tools" not in caps:
                caps.append("tools")
            # known=False → окно = дефолт (не подтверждено); пикер покажет «~».
            window, window_known = resolve_context_window_ex(mid, catalog)
            out.append(
                {
                    "id": mid,
                    "label": meta.get("name") or mid,
                    "context_window": window,
                    # Пикер помечает «~» неподтверждённое окно (жалоба «у всех 33K»).
                    "context_estimated": not window_known,
                    # Тир дороговизны по имени модели (0 эконом / 1 стандарт / 2 дорого).
                    # Это тот же публичный name-эвристик, что и у фейловер-гарда
                    # (shared.model_class) — НЕ раскрывает реальные цены/маржу.
                    # Предупреждает о дорогих моделях в пикере (жалоба: pro слила все
                    # кредиты за один вопрос без предупреждения).
                    "cost_tier": cost_rank(mid),
                    "capabilities": caps,
                }
            )
        return out

    async def get_thread_messages(
        self, thread_id: str, page: int, per_page: int, requester_id: str
    ) -> dict:
        await self._ensure_thread_owner(thread_id, requester_id)
        try:
            return await self.chat_service.get_messages(
                thread_id=thread_id, page=page, per_page=per_page
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination parameters") from exc
        except Exception as exc:
            from service.shared.repositories.exceptions import RepositoryNotFoundError

            if isinstance(exc, RepositoryNotFoundError):
                raise HTTPException(status_code=404, detail="Thread not found") from exc
            logger.error(
                "chat message fetch failed",
                extra={"component": "chat", "failure_code": "persistence"},
            )
            raise HTTPException(status_code=503, detail="DB unavailable") from exc

    async def list_threads(self, requester_id: str, page: int, per_page: int) -> dict:
        try:
            return await self.chat_service.list_threads(
                user_id=requester_id, page=page, per_page=per_page
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination parameters") from exc
        except Exception as exc:
            logger.error(
                "chat thread listing failed",
                extra={"component": "chat", "failure_code": "persistence"},
            )
            raise HTTPException(status_code=503, detail="DB unavailable") from exc

    async def delete_thread(self, thread_id: str, requester_id: str) -> None:
        await self._ensure_thread_owner(thread_id, requester_id)
        try:
            ok = await self.chat_service.delete_thread(thread_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Thread not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "chat thread deletion failed",
                extra={"component": "chat", "failure_code": "persistence"},
            )
            raise HTTPException(status_code=503, detail="DB unavailable") from exc

    async def rename_thread(self, thread_id: str, title: str, requester_id: str) -> dict:
        await self._ensure_thread_owner(thread_id, requester_id)
        clean = (title or "").strip()
        if not clean:
            raise HTTPException(status_code=400, detail="Title must not be empty")
        clean = clean[:200]
        try:
            ok = await self.chat_service.rename_thread(thread_id, clean)
            if not ok:
                raise HTTPException(status_code=404, detail="Thread not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "chat thread rename failed",
                extra={"component": "chat", "failure_code": "persistence"},
            )
            raise HTTPException(status_code=503, detail="DB unavailable") from exc
        return {"thread_id": thread_id, "title": clean}

    async def download_generated_file(self, file_key: str, filename: str | None) -> dict:
        normalized_key = self._normalize_download_file_key(file_key)
        file_service = self.file_service

        try:
            download_url = await file_service.get_presigned_url_by_key(file_key=normalized_key)
        except Exception:
            download_url = None

        if isinstance(download_url, str) and download_url.startswith(("http://", "https://")):
            return {"redirect_url": download_url}

        payload = await file_service.get_file_by_key(file_key=normalized_key)
        if payload is None:
            raise HTTPException(status_code=404, detail="File not found")

        suggested_name = (filename or Path(normalized_key).name or "download.bin").strip()
        return {"payload": payload, "filename": suggested_name}

    @staticmethod
    def _normalize_download_file_key(file_key: str) -> str:
        raw = str(file_key or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="file_key is required")
        # s3://<bucket>/<key> → <key> (артефакты хранятся с полным s3-URI в file_url).
        if raw.startswith("s3://"):
            without_scheme = raw[len("s3://") :]
            bucket_key = without_scheme.split("/", 1)
            raw = bucket_key[1] if len(bucket_key) == 2 else ""
            if not raw:
                raise HTTPException(status_code=400, detail="Invalid file_key")
        storage_root = (config.storage.root or ChatApplicationService.DEFAULT_STORAGE_ROOT).rstrip(
            "/"
        )
        if raw.startswith(f"{storage_root}/"):
            raw = raw[len(storage_root) + 1 :]
        elif raw.startswith(f"{ChatApplicationService.DEFAULT_STORAGE_ROOT}/"):
            raw = raw[len(ChatApplicationService.DEFAULT_STORAGE_ROOT) + 1 :]
        raw = raw.lstrip("/")
        path_obj = Path(raw)
        if ".." in path_obj.parts:
            raise HTTPException(status_code=400, detail="Invalid file_key")
        if not raw:
            raise HTTPException(status_code=400, detail="Invalid file_key")
        return raw

    async def run_web_search(self, query: str, num_results: int = 5) -> dict:
        query_value = query.strip()
        if not query_value:
            raise HTTPException(status_code=400, detail="Query is required")
        # Инструментами владеет сайдкар: поиск в панели и поиск агента обязаны быть
        # ОДНОЙ реализацией, иначе пользователь видит не то, чем пользуется ассистент.
        from service.infrastructure.agents_client import sidecar_tools
        from service.settings import config as _cfg

        # ⚠️ Зажимаем С ОБЕИХ сторон. `num_results` приезжает query-параметром от
        # пользователя, и верх был обрезан, а низ — нет: ноль и минус доезжали до
        # поиска и давали пустой список (условие набора `len(results) >= -5` истинно
        # сразу), то есть «ничего не нашлось» вместо «параметр бессмысленный». Теперь
        # сайдкар такое ещё и отвергает схемой (`ge=1`), а его отказ здесь превращается
        # в 503 «поиск недоступен» — ошибка ввода выглядела бы аварией сервиса.
        results = await sidecar_tools.web_search(_cfg, query_value, max(1, min(num_results, 10)))
        if results is None:
            raise HTTPException(
                status_code=503, detail="Поиск недоступен: сервис агентов не отвечает"
            )
        return {"query": query_value, "results": results, "count": len(results)}

    async def parse_url_content(self, url: str) -> dict:
        url_value = url.strip()
        if not url_value:
            raise HTTPException(status_code=400, detail="URL is required")

        # Ссылка на репозиторий → карта архитектуры, а не соскоб HTML-страницы. Раньше
        # github.com/owner/repo парсился как обычный сайт: модель получала вёрстку
        # страницы вместо кода.
        repo = await self._parse_repo_url(url_value)
        if repo is not None:
            return repo

        try:
            from service.infrastructure.agents_client import sidecar_tools
            from service.settings import config as _cfg

            remote = await sidecar_tools.parse_url(_cfg, url_value)
            if remote is None:
                raise HTTPException(
                    status_code=503, detail="Разбор ссылки недоступен: сервис агентов не отвечает"
                )
            # ⚠️ Форма ответа ОБЯЗАНА совпадать с веткой репозитория выше. Здесь
            # возвращалась голая строка (`sidecar_tools.parse_url` отдаёт `str`), хотя
            # метод объявлен как `-> dict`, и фронт читает `r.value?.content`
            # (useChatMessageSender.js:285). То есть для ОБЫЧНОЙ ссылки страница
            # успешно скачивалась и разбиралась, а пользователь видел «не удалось
            # прочитать: пустой ответ», и модель не получала текст вовсе — работали
            # только ссылки на GitHub. Сайдкар title не отдаёт, поэтому подставляем
            # URL: фронт всё равно берёт `title || url`.
            return {"url": url_value, "title": url_value, "content": remote, "kind": "page"}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "URL parsing failed",
                extra={"component": "chat", "failure_code": "remote"},
            )
            raise HTTPException(
                status_code=502,
                detail="Unable to fetch or parse URL content",
            ) from exc

    async def _parse_repo_url(self, url: str) -> dict | None:
        """→ карта репозитория, либо None (это не репозиторий / не смогли).

        Fail-open по замыслу: не получилось разобрать как репозиторий — пусть ссылка
        пройдёт обычным путём, а не превратится в ошибку.
        """
        from service.infrastructure.graphify import GraphifyClient
        from service.infrastructure.repo_fetcher import (
            fetch_repo_tarball,
            is_repo_url,
            strip_archive_root,
        )

        if not is_repo_url(url):
            return None
        client = GraphifyClient()
        if not client.enabled:
            return None

        try:
            tar_gz, slug = await fetch_repo_tarball(url)
            tar_gz = strip_archive_root(tar_gz)
        except Exception:  # noqa: BLE001
            logger.info(
                "репозиторий не скачался — обычный путь",
                extra={"component": "chat", "failure_code": "remote"},
            )
            return None

        import uuid

        graph_id = f"repo-{uuid.uuid4().hex[:12]}"
        built = await client.build(tar_gz, graph_id=graph_id, mode="code")
        report = str(built.get("report") or "").strip()
        if not report:
            return None

        header = (
            f"# Карта репозитория: {slug}\n"
            f"_{built.get('nodes', 0)} узлов · {built.get('edges', 0)} связей · "
            f"разбор AST без обращений к LLM_\n\n"
        )
        return {
            "url": url,
            "title": f"Репозиторий {slug}",
            "content": header + report,
            "kind": "repo",
            "graph_id": graph_id,
        }

    async def generate_topic_pptx(self, topic: str) -> dict:
        topic_value = topic.strip()
        if not topic_value:
            raise HTTPException(status_code=400, detail="Topic is required")

        # Генерация — ЛЛМ-вызов, поэтому её исполняет владелец провайдеров. Он же и
        # ВЫБИРАЕТ модель: backend не знает, кто из провайдеров сейчас жив.
        from service.infrastructure.agents_client import sidecar_tools
        from service.settings import config as _cfg

        pptx_bytes = await sidecar_tools.generate_pptx(_cfg, topic_value)
        if pptx_bytes is None:
            raise HTTPException(
                status_code=503,
                detail="Генерация презентации недоступна: сервис агентов не отвечает",
            )

        filename = (
            re.sub(r"[^\w\s-]", "", topic_value)[:40].strip().replace(" ", "_") or "presentation"
        )
        return {"payload": pptx_bytes, "filename": f"{filename}.pptx"}
