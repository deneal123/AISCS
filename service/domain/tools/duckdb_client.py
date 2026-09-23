"""HTTP-клиент к сайдкару DuckDB + сбор табличных файлов пользователя.

Сайдкар грузит переданные файлы в таблицы и гоняет по ним SQL (см. duckdb/app.py).
Байты берём из объектного хранилища (MinIO) по метаданным UserFile. Файл-сервис
строим СВЕЖИМ на вызов (как воркер на задачу): модульный синглтон пула Postgres
сломался бы под celery loop-per-task («bound to a different event loop»).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from service.infrastructure.sidecar import SidecarClient
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)

# Что DuckDB-сайдкар читает НАПРЯМУЮ (синхронно с duckdb/app.py SUPPORTED_EXT).
DUCKDB_NATIVE_EXTENSIONS = (
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".pqt",
    ".json",
    ".jsonl",
    ".ndjson",
    ".xlsx",
)
# xls/ods DuckDB не читает (нет расширения без интернета) — конвертируем в xlsx через
# сайдкар opendataloader (там есть LibreOffice), уже потом отдаём в DuckDB.
CONVERT_EXTENSIONS = (".xls", ".ods", ".xlsm", ".fods")


async def _convert_to_xlsx(raw: bytes, filename: str) -> bytes | None:
    """xls/ods → xlsx-байты через сайдкар opendataloader (LibreOffice). None при сбое."""
    base = (config.agents.opendataloader_url or "").rstrip("/")
    enabled = runtime_settings.get_agents(
        "opendataloader_enabled", config.agents.opendataloader_enabled
    )
    if not base or not enabled:
        return None
    # ⚠️ Через overlay, а не из конфига напрямую: ключ ОБЪЯВЛЕН в админке, и чтение
    # мимо снимка означало бы, что админ меняет значение, а поведение прежнее —
    # молча. Ровно этот класс дефекта нашёл офлайн-страж ключей agents.*.
    timeout = float(
        runtime_settings.get_agents(
            "opendataloader_timeout_sec", config.agents.opendataloader_timeout_sec
        )
        or 180.0
    )
    try:
        converted = await SidecarClient(
            service="opendataloader", base_url=base, timeout=timeout
        ).request_bytes(
            "POST",
            "/convert",
            params={"filename": filename},
            content=raw,
            headers={"Content-Type": "application/octet-stream"},
        )
        return converted or None
    except Exception:
        logger.warning("opendataloader conversion failed code=unavailable")
        return None


# Потолки на один вызов: не тащить весь архив пользователя, не раздуть тело запроса.
MAX_FILES = 6
MAX_FILE_BYTES = 32 * 1024 * 1024


def _ext(name: str) -> str:
    return Path(str(name or "")).suffix.lower()


class DuckDBClient(SidecarClient):
    """Клиент сайдкара DuckDB: {sql, files} → результат SQL.

    ⚠️ ЧТО ИЗМЕНИЛОСЬ ПРИ ПЕРЕХОДЕ НА ОБЩУЮ БАЗУ. Раньше этот клиент вёл себя
    несимметрично: HTTP-ошибка превращалась в ЗНАЧЕНИЕ `{"error": "sidecar_http"}`, а
    сетевой сбой улетал исключением наверх — то есть один и тот же метод отвечал
    по-разному в зависимости от того, где именно сломалось. Теперь оба случая —
    исключения из общей таксономии, и вызывающий решает, как деградировать.

    `sql_error` при этом остаётся ЗНАЧЕНИЕМ с кодом 200: неверный SQL — не отказ
    сервиса, а нормальный ход диалога с моделью (см. `duckdb/service/contracts.py`).
    """

    def __init__(self) -> None:
        super().__init__(
            service="duckdb",
            base_url=config.agents.duckdb_url or "",
            timeout=float(config.agents.duckdb_timeout_sec or 60.0),
        )

    @property
    def enabled(self) -> bool:
        return bool(
            runtime_settings.get_agents("duckdb_enabled", config.agents.duckdb_enabled)
            and self.available
        )

    async def query(self, *, sql: str, files: list[dict], max_rows: int = 200) -> dict:
        """POST /query. files=[{name, content_b64}]. → dict ответа сайдкара.

        Поднимает `SidecarBadRequest` / `SidecarUnavailable` / `SidecarTimeout`.
        """
        return await self.request_json(
            "POST",
            "/query",
            json_body={"sql": sql or "", "files": files, "max_rows": max_rows},
        )


async def fetch_tabular_files_from_urls(files: list[dict]) -> tuple[list[dict], list[str]]:
    """Скачать табличные файлы по ПРЕЗАЙНЕД-ссылкам → ``[{name, content_b64}]``.

    Путь САЙДКАРА (Фаза 0b.4): у него нет PG/MinIO backend'а, зато бэкенд положил в
    запрос ссылки. Качаем ЛЕНИВО — только когда инструмент реально вызван, поэтому тело
    ``/run`` не раздувается мегабайтами на каждый чат. Потолки те же, что у сбора из
    хранилища. Fail-soft: недоступный/битый файл просто пропускаем.
    """
    max_total = int(config.agents.duckdb_max_bytes or 48 * 1024 * 1024)
    out: list[dict] = []
    total = 0
    # ⚠️ ПРОПУЩЕННЫЕ ФАЙЛЫ — НАРУЖУ, А НЕ ТОЛЬКО В ЛОГ. Лог видит инженер, а решение по
    # неполным данным принимает МОДЕЛЬ: без явной пометки она делает SQL по подмножеству
    # таблиц и уверенно отвечает, будто увидела всё. Копим причины и отдаём вызывающему.
    skipped: list[str] = []
    all_files = files or []
    if len(all_files) > MAX_FILES:
        skipped.append(
            f"ещё {len(all_files) - MAX_FILES} файлов сверх лимита {MAX_FILES} на запрос"
        )
    async with httpx.AsyncClient(timeout=60.0) as client:
        for item in all_files[:MAX_FILES]:
            name = str((item or {}).get("name") or "")
            url = str((item or {}).get("url") or "")
            if not url:
                continue
            ext = _ext(name)
            try:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    logger.warning(
                        "duckdb source rejected status_family=%sxx", resp.status_code // 100
                    )
                    continue
                data = resp.content
            except Exception:
                logger.warning("duckdb source download failed code=unavailable")
                continue
            # ⚠️ РАНЬШЕ ОТБРАСЫВАЛОСЬ БЕЗ ЕДИНОЙ СТРОКИ ЛОГА — при том что двумя строками
            # выше сетевые сбои логируются. Наружу это опаснее сбоя: модель делает SQL по
            # ПОДМНОЖЕСТВУ таблиц и уверенно отвечает по неполным данным, а признака нет
            # ни в трейсе, ни в метаданных, ни в логах.
            if not data:
                logger.warning("duckdb source empty code=invalid")
                skipped.append(f"«{name}» — пустой")
                continue
            if len(data) > MAX_FILE_BYTES:
                logger.warning(
                    "duckdb source exceeds size limit code=invalid",
                )
                skipped.append(f"«{name}» — больше {MAX_FILE_BYTES // 1024 // 1024} МБ")
                continue
            # xls/ods DuckDB не читает — конвертируем через opendataloader (он доступен
            # и сайдкару: адрес приходит в его конфиге).
            if ext in CONVERT_EXTENSIONS:
                data = await _convert_to_xlsx(data, Path(name).name)
                if not data:
                    continue
                ext = ".xlsx"
            if total + len(data) > max_total:
                # ⚠️ Это `break`, а не `continue`: обрывается ВЕСЬ остаток списка, то есть
                # тихо теряется больше, чем один файл.
                logger.warning(
                    "duckdb aggregate source limit reached code=invalid",
                )
                _mb = max_total // 1024 // 1024
                skipped.append(f"«{name}» и последующие — исчерпан суммарный лимит {_mb} МБ")
                break
            total += len(data)
            # 🔴 ИМЯ ФАЙЛА СОХРАНЯЕМ. Здесь стояло `f"t{N}{ext}"`, и модель получала схему
            # «### t1 — из «t1.csv»» — то есть промпт УТВЕРЖДАЛ несуществующее имя файла.
            # Замер: на вопрос «средняя длина лепестка» модель написала `FROM iris`, взяв
            # имя из списка вложений в промпте (`iris.csv`), и получила «Table with name
            # iris does not exist». Четыре вызова, ответ «произошла ошибка доступа к файлу».
            # Расхождение между тем, что видно в промпте, и тем, что есть у инструмента,
            # модель разрешить не может — она про него не знает.
            #
            # ⚠️ Идентификатор таблицы делает САЙДКАР (`table_name_for`): он вырезает всё,
            # кроме латиницы и цифр, и приписывает префикс к имени, начинающемуся с цифры.
            # Так что настоящее имя безопасно, а для кириллического («отчёт за май.csv»)
            # идентификатор всё равно выродится в служебный — зато в заголовке схемы будет
            # видно, ИЗ КАКОГО файла таблица, и при нескольких файлах их станет различимо.
            out.append(
                {
                    "name": Path(name).name or f"t{len(out) + 1}{ext}",
                    "content_b64": base64.b64encode(data).decode("ascii"),
                }
            )
    return out, skipped
