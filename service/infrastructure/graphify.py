from __future__ import annotations

import io
import logging
import tarfile
import zipfile

from service.infrastructure.sidecar import SidecarBadRequest, SidecarClient, SidecarError
from service.settings import config
from service.shared.agent_settings_port import runtime_settings

logger = logging.getLogger(__name__)

# Потолки распаковки zip — защита от zip-бомбы ДО того, как байты уедут в сайдкар.
_MAX_ENTRIES = 20_000
_MAX_UNPACKED_BYTES = 500 * 1024 * 1024


class GraphifyClient(SidecarClient):
    """HTTP-клиент к сайдкару графа знаний. Fail-open: любая ошибка → пустой результат.

    Два режима разной цены:
      * ``code``  — tree-sitter AST, БЕЗ вызовов LLM (graphify сам пишет в отчёте
        «Token cost: 0 input · 0 output»);
      * ``docs``  — семантический проход LLM через наш шлюз, стоит денег.
    """

    def __init__(self) -> None:
        """⚠️ ТАЙМАУТЫ БЫЛИ РАЗНЫМИ В ОДНОМ КЛАССЕ: `build` брал значение из конфига
        (900), а `summary`/`delete`/`query` — литералы 30/30/60 прямо в вызове. Три
        источника на один сервис: правка конфига меняла поведение одного метода из
        четырёх, а остальные требовали правки кода.

        Теперь источник один — конфиг. Короткие операции получают per-request override,
        и он ВИДЕН в сигнатуре вызова, а не спрятан в теле метода.
        """
        super().__init__(
            service="graphify",
            base_url=config.agents.graphify_url or "",
            timeout=float(config.agents.graphify_timeout_sec or 900.0),
        )
        self._max_bytes = int(config.agents.graphify_max_bytes or 50 * 1024 * 1024)
        # Короткие ручки: чтение готового артефакта, а не сборка. Держать на них
        # 900 с бессмысленно — пользователь ждёт панель.
        self._short = min(60.0, float(config.agents.graphify_timeout_sec or 900.0))

    @property
    def enabled(self) -> bool:
        return bool(
            runtime_settings.get_agents("graphify_enabled", config.agents.graphify_enabled)
            and self.available
        )

    # ------------------------------------------------------------------ build --
    async def build(
        self,
        tar_gz: bytes,
        *,
        graph_id: str,
        mode: str = "code",
        merge: bool = False,
        label: bool | None = None,
    ) -> dict:
        if not self.enabled or not tar_gz:
            return {}
        if len(tar_gz) > self._max_bytes:
            logger.info("graphify: корпус больше лимита сайдкара — пропускаем")
            return {}
        params: dict[str, str] = {"graph_id": graph_id, "mode": mode}
        if merge:
            params["merge"] = "1"
        if label is not None:
            params["label"] = "1" if label else "0"
        try:
            return await self.request_json(
                "POST",
                "/graph/build",
                params=params,
                content=tar_gz,
                headers={"Content-Type": "application/octet-stream"},
            )
        except SidecarBadRequest as exc:
            # 413 «архив велик» и 400 «неизвестный режим» вызывающий может исправить.
            logger.info("graphify отклонил сборку (%s): %s", exc.code, exc.detail)
            return {}
        except SidecarError:
            logger.warning("graphify build failed", exc_info=True)
            return {}

    # ---------------------------------------------------------------- summary --
    async def summary(self, *, graph_id: str) -> dict:
        """Структурная сводка графа для панели: источники, ключевые узлы, размеры.

        Пустой dict — «графа нет», а не ошибка: у нового пользователя его и не должно быть.
        """
        if not self.enabled or not graph_id:
            return {}
        try:
            return await self.request_json("GET", f"/graph/{graph_id}/summary", timeout=self._short)
        except SidecarBadRequest as exc:
            # 404 здесь — норма: у нового пользователя графа ещё нет.
            if exc.code != "not_found":
                logger.info("graphify отклонил сводку (%s)", exc.code)
            return {}
        except SidecarError:
            logger.warning("graphify summary failed", exc_info=True)
            return {}

    async def delete(self, *, graph_id: str) -> bool:
        if not self.enabled or not graph_id:
            return False
        try:
            await self.request("DELETE", f"/graph/{graph_id}", timeout=self._short)
            return True
        except SidecarError:
            logger.warning("graphify delete failed", exc_info=True)
            return False

    async def html(self, *, graph_id: str) -> bytes | None:
        """Готовая интерактивная страница графа. ``None`` = графа ещё нет.

        ⚠️ Ответ НЕ JSON, и раньше это было поводом ходить мимо клиента: вызывающий
        (`graph_api`) поднимал свой `httpx.AsyncClient` с литералом `timeout=30.0`.
        Получался ТРЕТИЙ источник срока на один сервис — при том что комментарий выше
        объявляет, что источник теперь один. Общая база отдаёт сырой `Response`, так что
        не-JSON ей не мешает.

        ⚠️ И различие исходов: там ЛЮБОЙ `>=400` превращался в «граф ещё не построен»,
        включая 500 и 502. Пользователь получал «постройте граф» на упавший сайдкар и
        строил бы его снова. Здесь «нет графа» отделено от «сервис сломался».
        """
        if not self.enabled or not graph_id:
            return None
        try:
            resp = await self.request("GET", f"/graph/{graph_id}/html", timeout=self._short)
        except SidecarBadRequest as exc:
            if exc.code != "not_found":
                logger.info("graphify отклонил страницу графа (%s)", exc.code)
            return None
        return resp.content

    # ------------------------------------------------------------------ query --
    async def query(
        self, question: str, *, graph_id: str, depth: int = 3, token_budget: int = 2000
    ) -> str:
        if not self.enabled or not question.strip():
            return ""
        try:
            data = await self.request_json(
                "POST",
                "/graph/query",
                params={"graph_id": graph_id},
                json_body={
                    "question": question,
                    "depth": depth,
                    "token_budget": token_budget,
                },
                timeout=self._short,
            )
            return str(data.get("context") or "").strip()
        except SidecarBadRequest as exc:
            # 404 — у пользователя ещё нет графа, это не ошибка.
            if exc.code != "not_found":
                logger.info("graphify отклонил запрос (%s)", exc.code)
            return ""
        except SidecarError:
            logger.warning("graphify query failed", exc_info=True)
            return ""


def user_graph_id(user_id: str) -> str:
    """Личный граф пользователя. Копится между тредами — в отличие от файла в Redis,
    который живёт один на тред и умирает по TTL."""
    safe = "".join(c for c in str(user_id or "") if c.isalnum() or c in "-_")
    return f"user-{safe}" if safe else ""


def zip_to_targz(content: bytes) -> bytes:
    """zip (от пользователя) → tar.gz (формат сайдкара), с проверками по пути.

    Гарды здесь, а не только в сайдкаре: путь вида ``../../etc/passwd`` внутри архива
    не должен доехать даже до границы сервиса. Плюс потолки на число файлов и на
    распакованный размер — защита от zip-бомбы.
    """
    out = io.BytesIO()
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(content)) as zf, tarfile.open(fileobj=out, mode="w:gz") as tf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError(f"path traversal in archive: {name!r}")
            count += 1
            total += info.file_size
            if count > _MAX_ENTRIES:
                raise ValueError(f"archive has more than {_MAX_ENTRIES} entries")
            if total > _MAX_UNPACKED_BYTES:
                raise ValueError("archive expands beyond the size cap")
            payload = zf.read(info)
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            tf.addfile(member, io.BytesIO(payload))
    return out.getvalue()


# Сколько файлов перечислять в дереве архива. Больше — и перечень начнёт вытеснять из
# промпта то, ради чего его и читают; меньше — не поместится обычный проект.
MAX_LISTED_ENTRIES = 200


def archive_listing(content: bytes) -> str:
    """Перечень файлов архива — ФАКТ о вложении, не зависящий от разбора кода.

    🔴 ЗАМЕРЕНО. Архив стилей TMLR (LaTeX, девять файлов): graphify отвечает 500 «graph is
    empty — extraction produced no nodes», путь fail-open молча отдавал пусто, и о
    вложении у агента не оставалось НИ ОДНОГО факта. Человек получил ответ «в проекте три
    файла» — перечисленные по догадке. Оглавление zip читается за один разбор и верно для
    любого содержимого: код, вёрстка, датасет.

    ⚠️ Общий корневой каталог (так упакованы архивы с GitHub) срезается: он ничего не
    сообщает о проекте, а в каждой строке съедает место.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            entries = [
                (info.filename.replace("\\", "/"), info.file_size)
                for info in zf.infolist()
                if not info.is_dir()
            ]
    except Exception:
        return ""
    if not entries:
        return ""

    roots = {name.split("/", 1)[0] for name, _ in entries if "/" in name}
    strip = len(roots) == 1 and all("/" in name for name, _ in entries)
    shown = entries[:MAX_LISTED_ENTRIES]
    lines = [f"# Файлы архива ({len(entries)})", ""]
    lines += [f"- {(name.split('/', 1)[1] if strip else name)} · {size} Б" for name, size in shown]
    if len(entries) > len(shown):
        # ⚠️ Обрезку НАЗЫВАЕМ: молча укороченный перечень неотличим от полного, и агент
        # уверенно скажет, что остальных файлов в проекте нет.
        lines.append(f"- …и ещё {len(entries) - len(shown)} файлов (перечень сокращён)")
    return "\n".join(lines)


def text_to_targz(filename: str, text: str) -> bytes:
    """Один документ (markdown от opendataloader) → tar.gz для индексации в граф.

    Имя файла становится источником узлов и видно пользователю в панели графа, поэтому
    исходное расширение снимаем: иначе `отчёт.pdf` превращался бы в `отчёт.pdf.md`.
    """
    out = io.BytesIO()
    payload = text.encode("utf-8")
    stem = str(filename or "doc").rsplit(".", 1)[0] or "doc"
    safe = "".join(c for c in stem if c.isalnum() or c in "-_. ").strip() or "doc"
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        member = tarfile.TarInfo(f"{safe}.md")
        member.size = len(payload)
        tf.addfile(member, io.BytesIO(payload))
    return out.getvalue()
