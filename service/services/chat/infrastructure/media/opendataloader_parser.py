from __future__ import annotations

import logging

from service.infrastructure.sidecar import SidecarBadRequest, SidecarClient, SidecarError
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.chat.application.ports.document_parsing_port import DocumentParsingPort
from service.settings import config

logger = logging.getLogger(__name__)

# Форматы, которые сайдкар доводит до markdown: PDF напрямую, остальное — через
# LibreOffice → PDF. Текстовые (txt/md/csv/json/код) сюда НЕ входят: бэкенд читает их
# сам, круг через PDF только потерял бы качество и время.
SIDECAR_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".xlsx",
    ".xls",
    ".ods",
    ".pptx",
    ".ppt",
    ".odp",
    ".html",
    ".htm",
)


class OpenDataLoaderParser(SidecarClient, DocumentParsingPort):
    """HTTP-клиент к сайдкару opendataloader (документ → структурный markdown).

    Fail-open сохранён СНАРУЖИ: не разобрали документ — читаем его прежним путём, а не
    роняем сообщение. Но решение это принимается здесь явно, а не прячется в транспорте,
    и «формат не поддержан» больше не выглядит как «сервис лёг».
    """

    def __init__(self) -> None:
        super().__init__(
            service="opendataloader",
            base_url=config.agents.opendataloader_url or "",
            timeout=float(config.agents.opendataloader_timeout_sec or 180.0),
        )
        self._max_bytes = int(config.agents.opendataloader_max_bytes or 20 * 1024 * 1024)
        # Метаданные последнего разбора (engine/chars/duration) — для трейса и телеметрии.
        self.last_parse: dict | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            runtime_settings.get_agents(
                "opendataloader_enabled", config.agents.opendataloader_enabled
            )
            and self.available
        )

    def supports(self, filename: str) -> bool:
        return bool(filename) and str(filename).lower().endswith(SIDECAR_EXTENSIONS)

    async def parse(self, content_bytes: bytes, filename: str) -> str:
        if not self.enabled or not content_bytes or not self.supports(filename):
            return ""
        if len(content_bytes) > self._max_bytes:
            logger.info("opendataloader: %s больше лимита сайдкара — старый путь", filename)
            return ""

        self.last_parse = None
        try:
            data = await self.request_json(
                "POST",
                "/parse",
                params={"filename": filename},
                content=content_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            markdown = str(data.get("markdown") or "").strip()
            if not markdown:
                return ""
            self.last_parse = {
                "engine": data.get("engine"),
                "chars": data.get("chars"),
                "duration_sec": data.get("duration_sec"),
            }
            return markdown
        except SidecarBadRequest as exc:
            # 415 «формат не поддержан» — это НЕ сбой сервиса: значит документ идёт
            # прежним путём, и знать причину полезно. Раньше сводилось к общему warning.
            logger.info("opendataloader отклонил %s (%s)", filename, exc.code)
            return ""
        except SidecarError:
            logger.warning("opendataloader sidecar parse failed", exc_info=True)
            return ""
