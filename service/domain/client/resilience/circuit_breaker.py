"""Circuit breaker провайдеров: кто сейчас «мёртв» и его не надо трогать.

Живёт отдельным модулем, потому что состояние нужно ДВУМ мирам:

* воркеру — чтобы фейловер не тратил дедлайн запроса на ретраи мёртвого провайдера
  (быстрый путь, in-memory: своё на каждый процесс);
* API-процессу — чтобы пикер моделей не показывал модели упавшего провайдера, а
  админ-панель говорила правду. API-процесс сам чат НЕ вызывает, поэтому его in-memory
  состояние всегда пусто — и «реактивность» до пикера долетает ТОЛЬКО через общий Redis.

Отсюда двухслойность: mark_down пишет и в память (быстрое чтение в фейловере), и в Redis
(кросс-процессная правда). Redis — мягкая зависимость: нет его → остаётся in-memory, и
всё деградирует до прежнего поведения, а не падает.

ВАЖНО про то, ЧТО считается падением. Раньше breaker срабатывал только на транспортные
ошибки (таймаут/обрыв). Но живой инцидент был иным: OpenRouter отдавал 403 «Key limit
exceeded», OpenAI — 429 «insufficient_quota». Это не сеть — это «денег нет», и провайдер
в таком состоянии бесполезен ровно так же. Теперь гасим и на 401/403/429. А вот 400/404/422
НЕ гасим: это ошибка КОНКРЕТНОГО запроса (кривой параметр, нет модели), а не провайдера —
погасив, мы бы выкинули рабочего провайдера из-за одного плохого запроса.
"""

from __future__ import annotations

import asyncio
import logging
import time

from service.settings import config

logger = logging.getLogger(__name__)

COOLDOWN_SEC = 90.0
_REDIS_KEY = "provider:down:{name}"

# Быстрый путь: своё на процесс. Значение — monotonic-дедлайн, до которого провайдер мёртв.
_DOWN_UNTIL: dict[str, float] = {}

# СИНХРОННЫЙ redis.Redis, а не redis.asyncio: async-клиент привязывается к event loop, на
# котором создан, а celery-воркер создаёт НОВЫЙ loop на каждую задачу — запись mark_down с
# loop-1 падала бы «attached to a different loop» на loop-2 и молча терялась, и кросс-
# процессный сигнал (воркер гасит → API-пикер видит через Redis) не работал вовсе. Sync-
# клиент не loop-bound, живёт весь процесс; блокирующие вызовы уводим в asyncio.to_thread.
_redis = None
_redis_ready = False


def _get_redis():
    """Лениво поднять СИНХРОННЫЙ Redis из конфига. None → работаем только на памяти."""
    global _redis, _redis_ready
    if _redis_ready:
        return _redis
    _redis_ready = True
    try:
        if not getattr(config.redis, "enabled", False):
            return None
        import redis

        _redis = redis.Redis.from_url(config.redis.dsn, decode_responses=True)
    except Exception:  # noqa: BLE001 - Redis необязателен, breaker деградирует до памяти
        logger.warning("circuit breaker: Redis недоступен, остаюсь на in-memory")
        _redis = None
    return _redis


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else None


def should_trip(exc: Exception) -> bool:
    """Считать ли эту ошибку падением ПРОВАЙДЕРА (а не отдельного запроса)."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # По коду — надёжнее строк. 401/403/429 = провайдер недоступен для нас (авторизация,
    # лимит, квота). 400/404/422 = плохой запрос, провайдер тут ни при чём — НЕ гасим.
    code = _status_code(exc)
    if code in (401, 403, 429):
        return True
    if code in (400, 404, 422):
        return False
    from service.domain.client.protocol import ProviderFailureCode, classify_provider_failure

    failure = classify_provider_failure(exc)
    return failure.code in {
        ProviderFailureCode.AUTH,
        ProviderFailureCode.QUOTA,
        ProviderFailureCode.RATE_LIMIT,
        ProviderFailureCode.TIMEOUT,
        ProviderFailureCode.TRANSPORT,
    } or bool(code and code >= 500)


async def mark_down(name: str, *, reason: str | None = None) -> None:
    """Пометить провайдера мёртвым на COOLDOWN_SEC — и в памяти, и в Redis."""
    _DOWN_UNTIL[name] = time.monotonic() + COOLDOWN_SEC
    r = _get_redis()
    if r is None:
        return
    try:
        from service.domain.client.protocol import ProviderFailureCode

        allowed = {item.value for item in ProviderFailureCode}
        bounded_reason = reason if reason in allowed else "internal"
        key, val, ttl = _REDIS_KEY.format(name=name), bounded_reason, int(COOLDOWN_SEC)
        await asyncio.to_thread(lambda: r.set(key, val, ex=ttl))
    except Exception:  # noqa: BLE001
        logger.debug("provider circuit persistence failed code=unavailable")


async def clear_down(name: str) -> None:
    """Провайдер снова ответил — снять метку немедленно (не ждать TTL).

    ⚠️ DEL УХОДИТ БЕЗУСЛОВНО, И ЭТО НАМЕРЕННО. Функция зовётся на КАЖДЫЙ успешный вызов
    провайдера, а он в норме не помечен — то есть почти все эти DEL заведомо ничего не
    удаляют, и на них тратятся round-trip и thread-hop (клиент синхронный).

    Напрашивающаяся оптимизация «слать DEL, только если метка была ЛОКАЛЬНО» ОТВЕРГНУТА:
    локальная метка не эквивалентна записи в Redis. Пометить провайдера мог один процесс,
    а увидеть его восстановление — другой; у второго локальной метки нет, DEL не уйдёт, и
    в Redis метка провисит до TTL. Наружу это «живой провайдер числится мёртвым в панели
    и обходится пикером».

    Сегодня сайдкар живёт в ОДНОМ воркере, и разницы не было бы. Но это незаписанное
    допущение и без того держит здесь слишком многое (ключи провайдеров, активный
    провайдер, снимок настроек); добавлять к нему ещё одно ради экономии round-trip'ов —
    плохой размен. Если эти вызовы станут заметны, чинить надо не здесь, а сделав
    состояние breaker'а по-настоящему кросс-процессным.
    """
    _DOWN_UNTIL.pop(name, None)
    r = _get_redis()
    if r is None:
        return
    try:
        await asyncio.to_thread(r.delete, _REDIS_KEY.format(name=name))
    except Exception:  # noqa: BLE001
        logger.debug("provider circuit persistence failed code=unavailable")


def drop_cooled_down_local(order: list[str]) -> list[str]:
    """Быстрый (in-memory) фильтр для ФЕЙЛОВЕРА: без Redis-раунда на каждый запрос.

    Если живых не осталось — вернуть исходный порядок: лучше попробовать хоть что-то.
    """
    now = time.monotonic()
    live = [n for n in order if _DOWN_UNTIL.get(n, 0.0) <= now]
    return live or order


async def down_providers(names: list[str]) -> set[str]:
    """Кросс-процессный список мёртвых: память + Redis. Для пикера и панели."""
    now = time.monotonic()
    down = {n for n in names if _DOWN_UNTIL.get(n, 0.0) > now}
    r = _get_redis()
    if r is None:
        return down
    try:
        vals = await asyncio.to_thread(r.mget, [_REDIS_KEY.format(name=n) for n in names])
        down |= {n for n, v in zip(names, vals, strict=True) if v is not None}
    except Exception:  # noqa: BLE001
        logger.debug("provider circuit read failed code=unavailable")
    return down
