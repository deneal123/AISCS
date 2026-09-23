from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import uuid
from pathlib import Path

from service.infrastructure.agents_client.ports import resolve_user_uuid
from service.models.key_value import ServiceType
from service.services.chat.application.ports.document_parsing_port import DocumentParsingPort
from service.services.chat.application.ports.media_analysis_port import MediaAnalysisPort
from service.services.files.application.file_saver_service import UploadIntentConflict
from service.settings import config
from service.shared.tabular_shape import HEAD_BYTES, looks_tabular

logger = logging.getLogger(__name__)


class AttachmentPersistenceError(RuntimeError):
    """The upload cannot be used when its durable library source is absent."""


class AttachmentIntentConflict(RuntimeError):
    """The same opaque upload intent was reused for different bytes or a name."""


# Ниже этой доли «символов в словах» извлечённый текст считаем мусором. Эмпирика живого
# инцидента: двухколоночная статья прошла через opendataloader в кашу из ≥±−+ и подписей
# к осям (0.20), PyPDF2 на том же файле дал связный текст (0.60).
_MIN_TEXT_QUALITY = 0.35
# Короче этого текст не судим: на паре десятков символов метрика шумит, а короткий
# документ («Итого: 42 ₽») легитимен и без «слов».
_MIN_LEN_TO_JUDGE = 200
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)  # последовательности ≥3 буквенных


_CYRILLIC_WORD_RE = re.compile(r"[Ѐ-ӿ]{3,}")


def _cyrillic_word_chars(text: str) -> int:
    """Символы в кириллических СЛОВАХ (≥3 подряд). Одиночные буквы не считаем.

    Ключ к отличию mojibake от западного текста: mojibake кириллицы даёт связные слова
    («Возраст»), а recode латиницы с диакритиками — лишь ОДИНОЧНЫЕ буквы среди латиницы
    («cafй»), которые в слова не складываются.
    """
    return sum(len(m.group()) for m in _CYRILLIC_WORD_RE.finditer(text))


def _fix_cp1251_mojibake(text: str) -> str:
    """Починить кириллицу, которую PyPDF2 вернул как cp1251-байты в latin-1 обёртке.

    Живой инцидент: русская статья извлеклась как «Âîçðàñò-èíâàðèàíòíîå» — это байты
    cp1251, прочитанные как latin-1. Побайтовая перекодировка через cp1251 возвращает
    «Возраст-инвариантное»; английский (ASCII) при этом не меняется. Применяем ТОЛЬКО
    если кандидаты сложились в кириллические СЛОВА — иначе (уже валидный юникод, или
    западноевропейский текст с диакритиками) оставляем как есть.
    """
    # Кандидаты на перекодировку — символы latin-1-extended (0x80–0xFF): в mojibake это
    # одиночные cp1251-байты кириллицы.
    candidates = sum(1 for c in text if 0x80 <= ord(c) <= 0xFF)
    if not candidates:
        return text

    # ПОСИМВОЛЬНО: ASCII и настоящий юникод (формулы «≥», тире) оставляем как есть — иначе
    # `encode("latin-1")` на всём тексте падает об первый же математический символ (статья
    # полна формул) и починка не срабатывает вовсе.
    def _ch(c: str) -> str:
        o = ord(c)
        if 0x80 <= o <= 0xFF:
            try:
                return bytes([o]).decode("cp1251")
            except UnicodeDecodeError:
                return c
        return c

    recoded = "".join(_ch(c) for c in text)
    # Применяем, только если кандидаты сложились в кириллические СЛОВА (а не рассыпались
    # одиночными буквами): первое — mojibake, второе — латиница с диакритиками.
    became_words = _cyrillic_word_chars(recoded) - _cyrillic_word_chars(text)
    return recoded if became_words >= candidates * 0.5 else text


def _text_quality(text: str) -> float:
    """Доля символов, попавших в «слова» (≥3 буквы подряд). 1.0 для коротких — не судим.

    Отличает связный текст (много букв и слов) от символьной каши, которую сложные PDF
    иногда отдают экстрактору. Не про язык: ``\\w``-класс с ``re.UNICODE`` берёт и
    кириллицу, и латиницу, и иероглифы.
    """
    text = text or ""
    if len(text) < _MIN_LEN_TO_JUDGE:
        return 1.0
    word_chars = sum(len(m) for m in _WORD_RE.findall(text))
    return word_chars / len(text)


class UploadFileUseCase:
    def __init__(
        self,
        media_analysis_port: MediaAnalysisPort,
        file_service,
        document_parsing_port: DocumentParsingPort | None = None,
        graph_client=None,
    ) -> None:
        self.media_analysis_port = media_analysis_port
        self.file_service = file_service
        self.document_parsing_port = document_parsing_port
        self.graph_client = graph_client
        # Граф последнего разобранного репозитория (repo-{uuid}). Эндпоинт связывает его
        # с тредом в Redis, чтобы search_knowledge_graph искал КОД репо, а не только
        # личные документы юзера. None до первого репозитория.
        self.last_graph: dict | None = None

    async def execute(
        self,
        *,
        filename: str,
        content_type: str | None,
        content_bytes: bytes,
        thread_id: str,
        user_id: str | None,
        transcription_mode: str = "local",
        transcription_model: str | None = None,
        max_transcription_sec: float | None = None,
        upload_intent_id: str | None = None,
    ) -> dict:
        max_bytes = int(config.agents.upload_max_bytes or 20 * 1024 * 1024)
        if not filename:
            raise ValueError("No file provided")
        if len(content_bytes) > max_bytes:
            raise OverflowError(f"File too large (max {max_bytes // (1024 * 1024)}MB)")

        saved_file_id, saved_file_url, saved_file_key = await self._save_file(
            filename, content_bytes, user_id, upload_intent_id
        )
        extracted_text, file_type = await self._extract_text(
            filename,
            content_type,
            content_bytes,
            transcription_mode=transcription_mode,
            transcription_model=transcription_model,
            max_transcription_sec=max_transcription_sec,
        )

        # Потолок — страховка от патологии, а не рабочая обрезка: под окно модели текст
        # ужимает map-reduce компрессор, и ему нужен ВЕСЬ документ. ⚠️ Через overlay:
        # ключ объявлен в админке, и чтение мимо снимка означало «админ поднял потолок,
        # значение сохранилось, документы режутся по-прежнему».
        from service.services.admin.application.runtime_settings import runtime_settings

        limit = int(
            runtime_settings.get_agents(
                "attachment_text_max_chars", config.agents.attachment_text_max_chars
            )
            or 400_000
        )
        if len(extracted_text) > limit:
            extracted_text = extracted_text[:limit] + "\n...[содержимое обрезано]"

        return {
            "filename": filename,
            "file_type": file_type,
            # Таблица ли это ПО СОДЕРЖИМОМУ, а не по расширению. Клиент выбирает по
            # этому признаку модальность вложения: `.json`-словарь обязан ехать
            # документом, иначе его текст выбросят из промпта в пользу SQL, где строк нет.
            "is_tabular": looks_tabular(filename, content_bytes[:HEAD_BYTES]),
            "size": len(content_bytes),
            "extracted_text": extracted_text,
            "thread_id": thread_id,
            "file_id": saved_file_id,
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "mime_type": str(content_type or "application/octet-stream")[:120],
            "file_url": saved_file_url,
            "file_key": saved_file_key,
            "temp_file": True,
            # Метаданные локальной транскрипции (для тарификации на аплоаде) — эндпоинт
            # снимает этот ключ перед сборкой ответа. None для не-локальных путей.
            "transcription": getattr(self.media_analysis_port, "last_transcription", None),
            # Usage взгляда на пиксели: описание картинки — отдельный платный вызов VLM,
            # и его токены не попадают ни в один ход диалога. Эндпоинт снимает ключ и
            # тарифицирует. None — картинки не было или зрение отказало.
            "image_usage": getattr(self.media_analysis_port, "last_image_usage", None),
            # graph_id разобранного репозитория (repo-{uuid}) — эндпоинт привяжет его к
            # треду, чтобы инструмент искал код репо. None, если это не репозиторий.
            "repo_graph_id": (self.last_graph or {}).get("graph_id"),
        }

    async def _save_file(
        self,
        filename: str,
        content_bytes: bytes,
        user_id: str | None,
        upload_intent_id: str | None,
    ) -> tuple[str, str, str]:
        try:
            uploader_uuid = resolve_user_uuid(user_id, anonymous_fallback=True)
            if uploader_uuid is None:
                raise AttachmentPersistenceError("attachment owner is unavailable")
            kwargs = {
                "user_id": uploader_uuid,
                "mode": ServiceType.CHAT,
                "file_name": filename,
                "file_content": content_bytes,
            }
            if upload_intent_id:
                kwargs["upload_intent_id"] = uuid.UUID(str(upload_intent_id))
            saved = await self.file_service.save(**kwargs)
            return str(saved.file_id), saved.file_url, saved.file_key
        except UploadIntentConflict as exc:
            raise AttachmentIntentConflict("upload_intent_conflict") from exc
        except AttachmentPersistenceError:
            raise
        except Exception as exc:
            # The extracted bytes may be available in this request, but
            # accepting them without a durable UserFile creates a phantom
            # attachment that cannot appear in Library or be reused safely.
            logger.warning("chat attachment was not persisted", exc_info=True)
            raise AttachmentPersistenceError("attachment persistence failed") from exc

    # Исходный код: классифицируем отдельно, чтобы направить в код-аналитика.
    _CODE_EXTENSIONS = (
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".cpp",
        ".cc",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".sql",
        ".sh",
        ".bash",
        ".kt",
        ".swift",
        ".scala",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
    )

    async def _analyze_repository(self, filename: str, content_bytes: bytes) -> str:
        """zip с кодом → GRAPH_REPORT.md (ключевые узлы, сообщества, связи).

        Fail-open: сайдкар выключен/лежит/архив не разобрался → пусто, и вызывающий
        падает на прежний путь. Граф кладём под именем файла, чтобы по нему потом можно
        было спрашивать через инструмент.
        """
        if self.graph_client is None or not getattr(self.graph_client, "enabled", False):
            return ""
        from service.infrastructure.graphify import archive_listing, zip_to_targz

        try:
            tar_gz = zip_to_targz(content_bytes)
        except Exception:
            logger.info("graphify: архив %s не разобрался — обычный путь", filename, exc_info=True)
            return ""

        # 🔴 ПЕРЕЧЕНЬ ФАЙЛОВ — ФАКТ, И ОН НЕ ЗАВИСИТ ОТ ГРАФА. Замерено на архиве стилей
        # TMLR (LaTeX): graphify отвечает 500 «graph is empty — extraction produced no
        # nodes», карта выходит ПУСТОЙ, и агент, у которого не осталось ни одного факта о
        # вложении, перечисляет состав по догадке — человек увидел три файла вместо
        # девяти. Дерево берётся из самого архива, стоит одного разбора оглавления и верно
        # для любого содержимого: код, вёрстка, датасет.
        listing = archive_listing(content_bytes)

        graph_id = f"repo-{uuid.uuid4().hex[:12]}"
        try:
            result = await self.graph_client.build(tar_gz, graph_id=graph_id, mode="code")
        except Exception:
            # Не-кодовый архив — штатный случай, а не сбой: граф строить не из чего.
            logger.info("graphify: граф по архиву %s не построен — отдаём дерево", filename)
            return listing
        report = str(result.get("report") or "").strip()
        if not report:
            return listing
        self.last_graph = {
            "graph_id": graph_id,
            "nodes": result.get("nodes"),
            "edges": result.get("edges"),
        }
        header = (
            f"# Карта репозитория: {filename}\n"
            f"_{result.get('nodes', 0)} узлов · {result.get('edges', 0)} связей · "
            f"разбор AST без обращений к LLM_\n\n"
        )
        # ⚠️ Дерево идёт ВМЕСТЕ с картой, а не вместо: карта показывает связи разобранных
        # модулей, но молчит о файлах, которые AST не понимает (конфиги, данные, вёрстка),
        # — а вопрос «что в проекте» задают именно про состав.
        return header + listing + "\n\n" + report

    @staticmethod
    def _pypdf_text(content_bytes: bytes) -> str:
        """Плоский текст PDF через PyPDF2 (legacy-путь и фолбэк для сложной вёрстки)."""
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(content_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages[:30])
        return _fix_cp1251_mojibake(text)

    async def _extract_text(
        self,
        filename: str,
        content_type: str | None,
        content_bytes: bytes,
        *,
        transcription_mode: str = "local",
        transcription_model: str | None = None,
        max_transcription_sec: float | None = None,
    ) -> tuple[str, str]:
        lower_name = filename.lower()
        # Текстовые форматы читаем целиком: общий потолок применяет execute(), а под
        # окно модели их ужимает компрессор. Разнобой отсечек (15000/10000/15000)
        # обрезал CSV и код раньше, чем их успевал увидеть бюджет контекста.
        if lower_name.endswith((".txt", ".md")):
            return content_bytes.decode("utf-8", errors="replace"), "text"
        if lower_name.endswith(".csv"):
            return content_bytes.decode("utf-8", errors="replace"), "csv"
        if lower_name.endswith(".json"):
            data = json.loads(content_bytes)
            return json.dumps(data, indent=2, ensure_ascii=False), "json"
        if lower_name.endswith(self._CODE_EXTENSIONS):
            return content_bytes.decode("utf-8", errors="replace"), "code"

        # Документы (pdf/docx/xlsx/pptx/rtf/...) — через сайдкар opendataloader: он даёт
        # СТРУКТУРНЫЙ markdown с таблицами и заголовками, а не плоский текст. Fail-open:
        # пусто (сайдкар выключен, лежит, не осилил формат) → падаем в legacy-ветки ниже,
        # так что хуже, чем было, стать не может.
        parser = self.document_parsing_port
        if parser is not None and parser.supports(lower_name):
            markdown = await parser.parse(content_bytes, filename)
            if markdown and _text_quality(markdown) >= _MIN_TEXT_QUALITY:
                return markdown, Path(lower_name).suffix.lstrip(".")
            # ⚠️ ОЦЕНИВАЕМ КАЧЕСТВО, а не «непусто»: каша от opendataloader принималась как
            # успех, и PyPDF2-фолбэк не пробовался вовсе — агент получал 1924 знака мусора
            # и просил «вставьте текст», хотя статья лежала у него. Берём ЧИТАБЕЛЬНЕЕ.
            if lower_name.endswith(".pdf"):
                py_text = self._pypdf_text(content_bytes)
                if _text_quality(py_text) > _text_quality(markdown or ""):
                    return py_text, "pdf"
            # Не-PDF (или PyPDF2 не лучше): структурный markdown всё же лучше, чем ничего.
            if markdown:
                return markdown, Path(lower_name).suffix.lstrip(".")

        if lower_name.endswith(".pdf"):
            return self._pypdf_text(content_bytes), "pdf"
        if lower_name.endswith(".docx"):
            from docx import Document

            doc = Document(io.BytesIO(content_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs), "docx"
        # Архив с кодом → карта архитектуры (граф знаний). Сегодня zip уходит в ветку
        # `binary` и декодируется как utf-8 → мусор. Разбор чисто AST-овый: 36 языков,
        # НИ ОДНОГО обращения к LLM (graphify сам печатает «Token cost: 0 input · 0 output»).
        if lower_name.endswith(".zip"):
            report = await self._analyze_repository(filename, content_bytes)
            if report:
                return report, "repo"

        if lower_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return (
                await self.media_analysis_port.analyze_image(
                    content_bytes, content_type or "image/png", filename
                ),
                "image",
            )
        if lower_name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac", ".webm")):
            transcript = await self.media_analysis_port.transcribe_audio(
                content_bytes,
                filename,
                mode=transcription_mode,
                model=transcription_model,
                max_duration_sec=max_transcription_sec,
            )
            return transcript, "audio"
        try:
            return content_bytes.decode("utf-8", errors="replace")[:5000], "binary"
        except Exception:
            return f"[Файл {filename} загружен, но содержимое не удалось извлечь]", "binary"
