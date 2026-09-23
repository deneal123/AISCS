"""`POST /run` — прогон движка: стрим ``AgentEvent`` (NDJSON) + терминальный result-dict.

Главная ручка сервиса и самое тонкое место транспорта: движок отдаёт события
СИНХРОННЫМ колбэком, а отдавать их нужно по мере появления.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from service.application.reply_assembler import ReplyAssembler
from service.events import EventSerializer, EventType
from service.infrastructure.mcp import current_health_event, open_mcp_tools
from service.infrastructure.sidecar import set_correlation_id
from service.presentation import runtime
from service.presentation.deps import internal_auth
from service.presentation.errors import error
from service.presentation.routers.agent.run_recovery import build_timeout_result
from service.protocol_manifest import load_protocol_manifest
from service.schemas.run import AgentRunInput
from service.shared.agent_settings import remember_settings, use_settings
from service.shared.deadline import RunDeadline, use_deadline
from service.shared.provider_policy_context import remember_snapshot, use_snapshot

logger = logging.getLogger(__name__)
router = APIRouter()

# Дискриминаторы терминальных строк NDJSON-потока: всё остальное — события.
RESULT_KEY = "__result__"
ERROR_KEY = "__error__"
_PROTOCOL = load_protocol_manifest()

if {RESULT_KEY, ERROR_KEY} != _PROTOCOL.terminal_keys:
    raise RuntimeError("terminal protocol manifest mismatch")

# Запас внешнего стопа поверх мягкого дедлайна. Мягкий останавливает прогон изнутри и
# успевает отдать собранное; жёсткий нужен только на случай провайдера, который держит
# соединение и не отдаёт ни дельты — там останавливать изнутри нечему.
_HARD_STOP_GRACE_SEC = 60.0


def _run_deadline_sec() -> float | None:
    """Общий дедлайн прогона: overlay админки поверх конфига.

    ⚠️ Читается ЧЕРЕЗ `runtime_settings`, а не напрямую из конфига: иначе тумблер в
    админке не действовал бы — ровно та ошибка, которой в этом сервисе уже несколько
    (`subtask_synthesis_max_tokens`, основной эмбеддер).
    """
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    try:
        value = float(runtime_settings.get_agents("run_timeout_sec", config.agents.run_timeout_sec))
    except (TypeError, ValueError):
        value = float(config.agents.run_timeout_sec)
    # ⚠️ Ноль/отрицательное — «без дедлайна», и вернуть надо ИМЕННО None: `wait_for` с
    # timeout=0 сработал бы мгновенно и убивал бы каждый прогон. Это аварийный
    # выключатель на случай, если дедлайн окажется вреднее зависаний.
    return value if value > 0 else None


@router.post("/run")
async def run(
    payload: AgentRunInput,
    authorization: str | None = Header(default=None),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
):
    # ⚠️ Ключ проверяем ДО всего остального: ручка несёт полный пользовательский
    # контекст и деньги, и до сих пор была открыта — в отличие от /tools/web-search.
    internal_auth(authorization)
    # Подхватываем сквозной идентификатор от backend: дальше его понесут наши
    # собственные клиенты (duckdb и др.), и цепочка «вопрос пользователя →
    # воркер → сайдкар → сайдкар сайдкара» становится собираемой из логов.
    set_correlation_id(correlation_id)
    logger.info("/run accepted [cid=%s]", correlation_id or "-")
    if runtime.DefaultAgentExecutionService is None:
        return error("engine_unavailable", "unavailable", 503)

    engine = runtime.DefaultAgentExecutionService()
    serializer = EventSerializer()
    job_id = payload.thread_id

    async def ndjson() -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()
        done = object()
        recovery = ReplyAssembler()
        recovery_metadata: dict = {}
        terminal_emitted = False

        def emit_terminal(key: str, value: object) -> None:
            """A single run may expose only one billing envelope."""
            nonlocal terminal_emitted
            if terminal_emitted:
                logger.error("/run attempted a duplicate terminal [cid=%s]", correlation_id or "-")
                return
            terminal_emitted = True
            queue.put_nowait((key, value))

        def on_event(event) -> None:
            # Пайплайн зовёт колбэк СИНХРОННО — кладём без await.
            # Жёсткий стоп может отменить движок до его собственного result-dict. Копим
            # ровно тот минимум, который уже видел клиент: текст, usage и metadata —
            # чтобы оплаченные вызовы не исчезали вместе с отменённой корутиной.
            recovery_metadata.update(
                {
                    key: value
                    for key, value in (getattr(event, "metadata", None) or {}).items()
                    if key != "token_usage"
                }
            )
            recovery.consume(
                event=event,
                stream_chunk_type=EventType.STREAM_CHUNK,
                error_type=EventType.ERROR,
                structured_output_type=EventType.STRUCTURED_OUTPUT,
            )
            queue.put_nowait(event)

        async def runner() -> None:
            try:
                # Снимок провайдерной политики (кого выключил админ / заблокировала
                # health-проверка) живёт в БД+Redis backend'а, которых у сайдкара нет.
                # Разворачиваем его в окружение прогона — иначе мультипровайдерный слой
                # МОЛЧА решил бы, что не выключен никто, и пошёл бы в снятого провайдера.
                # Ставим ВНУТРИ задачи: у неё свой контекст, и снимок не протечёт в чужой
                # параллельный прогон.
                # Запоминаем снимок на процесс: `/v1`-шлюз зовут по OpenAI-протоколу,
                # где места под политику нет, и без этого он остался бы fail-open.
                remember_snapshot(payload.provider_policy)
                remember_settings(payload.agent_settings)
                # 🔴 МЯГКИЙ дедлайн ставится в окружение прогона, ЖЁСТКИЙ остаётся снаружи
                # с запасом. Раньше был только жёсткий: он обрывал задачу в произвольной
                # точке, и вместе с ней отменялся накопленный `per_call_usage` — вызовы, за
                # которые платформа уже заплатила провайдеру, в счёт не попадали. Мягкий
                # даёт прогону закончиться самому и отдать частичный результат; жёсткий
                # срабатывает только если провайдер завис и не отдаёт вообще ничего.
                limit = _run_deadline_sec()
                with (
                    use_snapshot(payload.provider_policy),
                    use_settings(payload.agent_settings),
                    use_deadline(RunDeadline.start(limit)),
                ):
                    # Подключение к разрешённым MCP-серверам — ВНУТРИ снимка настроек: их
                    # объявление приезжает тем же админ-снимком, снаружи оно ещё не видно.
                    # Пустой список разрешённых — мгновенный no-op, обычный чат в сеть не
                    # ходит. Соединения закрываются вместе с прогоном.
                    async with open_mcp_tools(payload.mcp_server_ids):
                        if event := current_health_event():
                            on_event(event)
                        # ⚠️ ОБЩЕГО ДЕДЛАЙНА У ПРОГОНА НЕ БЫЛО ВОВСЕ. `run_timeout_sec` был
                        # объявлен в настройках и не читался нигде, а единственной верхней
                        # границей оставался таймаут httpx конкретного провайдера — который
                        # умножается на ретраи (`llm_retry_attempts`) и на длину цепочки
                        # фейловера, и ничем не ограничен сверху. Мета-вызовы (декомпозиция,
                        # сложность, план, сжатие) шли вообще без `wait_for`. Провайдер,
                        # держащий соединение открытым и не отдающий дельт, держал задачу
                        # столько, сколько backend готов ждать, — то есть 10 минут.
                        result = await asyncio.wait_for(
                            engine.execute(**payload.to_execute_kwargs(), on_event=on_event),
                            timeout=(limit + _HARD_STOP_GRACE_SEC) if limit else None,
                        )
                emit_terminal(RESULT_KEY, result)
            except TimeoutError:
                # Отдельно от прочих ошибок: это НАШ дедлайн, а не сбой провайдера, и
                # называть его надо своим именем — иначе он неотличим от «модель молчит».
                limit = _run_deadline_sec() or 0
                logger.warning(
                    "/run deadline exceeded %.0f s [cid=%s]",
                    limit,
                    correlation_id or "-",
                )
                emit_terminal(
                    RESULT_KEY,
                    build_timeout_result(
                        recovery,
                        recovery_metadata,
                        payload,
                    ),
                )
            except Exception:  # noqa: BLE001
                emit_terminal(ERROR_KEY, "internal")
            finally:
                queue.put_nowait(done)

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is done:
                    break
                if isinstance(item, tuple):
                    key, value = item
                    # default=str — в result могут попасть не-JSON типы (datetime и пр.).
                    yield (
                        json.dumps({key: value}, ensure_ascii=False, default=lambda _value: None)
                        + "\n"
                    )
                else:
                    payload_line = serializer.serialize(event=item, job_id=job_id)
                    yield (
                        json.dumps(payload_line, ensure_ascii=False, default=lambda _value: None)
                        + "\n"
                    )
        finally:
            # Клиент отвалился/поток закрыт — не оставляем прогон висеть.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(ndjson(), media_type="application/x-ndjson")
