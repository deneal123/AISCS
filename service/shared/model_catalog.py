"""Каталог моделей OpenRouter: окна контекста, возможности, поддержка tools.

Копия есть у обеих сторон — намеренно. Это клиент ТРЕТЬЕЙ стороны (openrouter.ai), а
не контракт между нами: гонять backend за каталогом через сайдкар значило бы превратить
независимое чтение в жёсткую зависимость — перезапуск сайдкара гасил бы список моделей
в интерфейсе. По тому же принципу, по которому дублируются клиенты соседних сервисов.

Кэш здесь и так процессный: у каждого celery-воркера он свой уже сегодня, так что
вторая копия ничего не удваивает.

🔴 Файл ОБЯЗАН быть самодостаточным: только stdlib, httpx и `service.settings` (поля с
одинаковыми именами есть у обеих сторон). Побайтовая сверка копий — единственное, что
держит их вместе; импорт чего-то своего сделал бы её невыполнимой, и копии разошлись бы
молча. Так уже случилось: прокси добавили в сайдкар через `providers._http`, сверка стала
неисполнимой, и backend полгода ходил за каталогом мимо прокси.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL_SECONDS = 3600
_cache: dict[str, Any] = {"ts": 0.0, "data": {}}

# Single-flight на перестройку каталога: N промахов кэша не должны давать N запросов к
# openrouter.ai. Каталог на критическом пути (бюджет контекста на каждом запросе).
# ⚠️ Храним вместе с ПЕТЛЁЙ: Lock привязан к event loop, а модуль работает и там, где
# петля своя на задачу (celery). Сменилась петля → новый замок: вырождается, но не ломает.
_FETCH_LOCK: tuple[Any, asyncio.Lock] | None = None


def _fetch_lock() -> asyncio.Lock:
    global _FETCH_LOCK
    loop = asyncio.get_running_loop()
    if _FETCH_LOCK is None or _FETCH_LOCK[0] is not loop:
        _FETCH_LOCK = (loop, asyncio.Lock())
    return _FETCH_LOCK[1]


# Курируемый allowlist tool-capable моделей у провайдеров БЕЗ capability-метаданных
# (routerai/gigachat не отдают supported_parameters; OpenRouter — отдаёт). id — как в
# каталоге (без префикса провайдера). Расширяйте по мере проверки function-calling.
TOOL_CAPABLE_ALLOWLIST: set[str] = {
    "qwen/qwen3-max",  # routerai — проверено, tool_calls работают
}

# Семейства, где function-calling умеет вся линейка. ⚠️ GigaChat вызывает функции только
# на СТАРОМ диалекте (`functions` вместо `tools`): поле `tools` он молча игнорирует, и
# «не падает» тут ничего не доказывает — модель просто отвечает «нет доступа».
TOOL_CAPABLE_PREFIXES: tuple[str, ...] = ("gigachat",)

# --- контекстные окна ------------------------------------------------------- #
# Окно отдаёт только каталог OpenRouter; у остальных провайдеров его не было вовсе —
# 247 моделей из 590 с `context_window=None` и бюджетом контекста «вслепую».
# ⚠️ Значения из документации. ЗАНИЖАТЬ безопасно (бюджет консервативнее), ЗАВЫШАТЬ —
# нет: переполним окно и получим ошибку провайдера.
STATIC_CONTEXT_WINDOWS: dict[str, int] = {
    "mws-gpt-alpha": 32768,
    # routerai-нативные (в OpenRouter их нет даже без суффикса)
    "yandex/gpt-lite-5": 32768,
    "yandex/gpt-pro-5": 32768,
    "yandex/gpt-pro-5.1": 32768,
    "yandex/aliceai-llm": 32768,
    "reka/reka-edge": 8192,
    # Легаси OpenAI: окно МЕНЬШЕ дефолтного — без явной записи дефолт завысил бы его
    # и мы переполнили бы реальное окно.
    "gpt-3.5-turbo-instruct": 4096,
    "gpt-3.5-turbo-instruct-0914": 4096,
    "babbage-002": 16384,
    "davinci-002": 16384,
}

# Снапшоты моделей: OpenAI даёт датированные алиасы (``gpt-5-2025-08-07``,
# ``gpt-4-0613``, ``gpt-3.5-turbo-0125``) с тем же окном, что и базовая модель, но в
# каталоге лежит только базовая. Отбрасываем хвост-дату и пробуем ещё раз.
_SNAPSHOT_SUFFIX_RE = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{4})$")

# Семейства моделей, где окно одинаково у всех вариантов (-preview, -Pro, …).
# Порядок важен: проверяется сверху вниз, первый совпавший префикс выигрывает,
# поэтому более длинные/специфичные префиксы идут раньше.
_STATIC_WINDOW_PREFIXES: tuple[tuple[str, int], ...] = (
    # GigaChat 2 — 128k. Префикс должен идти ДО общего "GigaChat".
    ("GigaChat-2", 131072),
    # GigaChat 1-го поколения (GigaChat, -Plus, -Pro, -Max и их -preview) — 32k.
    ("GigaChat", 32768),
)

# Окно для модели, которую не удалось разрешить ничем. Консервативное: завышенный
# дефолт привёл бы к переполнению реального окна у мелкой модели.
DEFAULT_CONTEXT_WINDOW = 32768


def resolve_model_meta(model_id: str, catalog: dict[str, dict] | None = None) -> dict:
    """Метаданные модели из каталога OpenRouter с восстановлением по вариантам id.

    Провайдеры называют одну и ту же модель по-разному, поэтому пробуем несколько
    ключей (первое попадание выигрывает):
      1. как есть — ``openai/gpt-4o`` (модели самого OpenRouter);
      2. без суффикса-варианта — ``deepseek/…:exacto`` → ``deepseek/…`` (так живут
         почти все routerai-модели: ``:exacto``/``:extended``);
      3. без хвоста-даты — ``gpt-5-2025-08-07`` → ``gpt-5`` (снапшоты OpenAI);
      4. с префиксом ``openai/`` — нативный OpenAI отдаёт голые id (``gpt-4o``), а в
         каталоге они лежат как ``openai/gpt-4o`` (комбинируется с п.3).

    Возвращает ``{}``, если модель не восстановилась (gigachat/mws — их в каталоге нет).
    """
    mid = str(model_id or "").strip()
    if not mid:
        return {}
    cat = catalog if catalog is not None else _cache["data"]

    base = mid.split(":", 1)[0]
    undated = _SNAPSHOT_SUFFIX_RE.sub("", base)
    for key in (mid, base, undated, f"openai/{base}", f"openai/{undated}"):
        meta = cat.get(key)
        if meta:
            return meta
    return {}


def resolve_context_window_ex(
    model_id: str, catalog: dict[str, dict] | None = None
) -> tuple[int, bool]:
    """(окно, known). known=False → окно ПОДТВЕРДИТЬ не удалось ничем, значение =
    консервативный дефолт (для proxy-моделей вроде ``openai/gpt-5.6-*``, которых нет
    ни в каталоге OpenRouter, ни в статических картах). Пикер помечает такие «~»,
    чтобы дефолт не выглядел как реальное окно модели (жалоба: «у всех 33K»)."""
    mid = str(model_id or "").strip()
    if not mid:
        return DEFAULT_CONTEXT_WINDOW, False

    win = resolve_model_meta(mid, catalog).get("context_window")
    if win:
        return int(win), True

    static = STATIC_CONTEXT_WINDOWS.get(mid)
    if static:
        return static, True

    for prefix, prefix_win in _STATIC_WINDOW_PREFIXES:
        if mid.startswith(prefix):
            return prefix_win, True

    return DEFAULT_CONTEXT_WINDOW, False


def resolve_context_window(model_id: str, catalog: dict[str, dict] | None = None) -> int:
    """Реальное контекстное окно модели. Единый источник истины для пикера и бюджета.

    Каталог OpenRouter (с восстановлением по вариантам id) → статическая карта /
    префиксы семейств (GigaChat, MWS, яндекс) → консервативный дефолт.
    """
    return resolve_context_window_ex(model_id, catalog)[0]


def derive_capabilities(
    architecture: dict | None, supported_parameters: list | None = None
) -> list[str]:
    """Из architecture.*_modalities + supported_parameters → ярлыки возможностей.
    `tools` — модель поддерживает OpenAI function-calling (нужно для агентного LDR)."""
    arch = architecture or {}
    inp = arch.get("input_modalities") or []
    out = arch.get("output_modalities") or []
    caps: list[str] = []
    if "image" in inp:
        caps.append("vision")
    if "audio" in inp:
        caps.append("audio")
    if "file" in inp:
        caps.append("files")
    if "image" in out:
        caps.append("image_out")
    if supported_parameters and "tools" in supported_parameters:
        caps.append("tools")
    return caps


def model_has_capability(
    model_id: str, capability: str, catalog: dict[str, dict] | None = None
) -> bool:
    """Подтверждена ли КАТАЛОГОМ способность модели (`vision`/`audio`/`files`/`tools`).

    🔴 ОТБОР ПО ФАКТУ, А НЕ ПО ИМЕНИ. Имя о способностях не говорит, и это ИЗМЕРЕНО на
    живом стенде: 468 моделей у провайдера, зрение подтверждено у 187, а привычный отбор
    именем (`vision|vl|vlm|multimodal|image|llava|pixtral`) даёт 37 совпадений — из них
    10 БЕЗ зрения (`openai/gpt-image-1`, `gpt-4o-transcribe`, `gpt-4o-search-preview`,
    `microsoft/mai-image-2.5`), и мимо него проходят 160 зрячих: вся линейка Claude,
    Gemini, Amazon Nova. То есть имя ошибается в ОБЕ стороны сразу.

    ⚠️ НЕИЗВЕСТНАЯ модель = способности НЕТ, и это НЕ то же решение, что у
    `model_supports_tools`. Там незнание стоит снятых инструментов — деградация ответа;
    здесь оно стоило бы показа картинки модели, которая её не видит, а это оплаченный
    вызов, возвращающий отказ или выдумку. Провайдеров вне каталога (GigaChat, MWS) это
    отсекает намеренно: их приём `image_url` не подтверждён ничем.
    """
    if not capability:
        return False
    return capability in (resolve_model_meta(model_id, catalog).get("capabilities") or [])


def catalog_proxy_url() -> str:
    """http-proxy для openrouter.ai или ``""``.

    ⚠️ Повторяет `build_proxy_url("openrouter")` провайдерских клиентов НАМЕРЕННО: тот
    живёт в домене сайдкара, а этот файл обязан оставаться самодостаточным (см. модульный
    докстринг). Расхождение двух реализаций стережёт тест.
    """
    from service.settings import config

    raw = config.agents.proxy_providers or ""
    allow = {p.strip().lower() for p in raw.split(",") if p.strip()}
    if "openrouter" not in allow:
        return ""
    host = (config.agents.proxy_host or "").strip()
    if not host or not config.agents.proxy_port:
        return ""
    user = (config.agents.proxy_user or "").strip()
    password = (config.agents.proxy_pass or "").strip()
    if user or password:
        return f"http://{user}:{password}@{host}:{config.agents.proxy_port}"
    return f"http://{host}:{config.agents.proxy_port}"


async def _fetch_openrouter() -> dict[str, dict]:
    # ⚠️ ЧЕРЕЗ ПРОКСИ, как провайдерские клиенты: openrouter.ai заблокирован в РФ. Каталог
    # тянулся голым httpx мимо прокси — в dev незаметно, а в проде запрос падал, каталог
    # оставался пуст, и инструменты снимались со ВСЕХ моделей.
    proxy_url = catalog_proxy_url()
    kwargs: dict = {"timeout": 12.0}
    if proxy_url:
        kwargs["proxy"] = proxy_url
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.get(_OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        rows = resp.json().get("data", []) or []
    out: dict[str, dict] = {}
    for m in rows:
        mid = m.get("id")
        if not mid:
            continue
        out[str(mid)] = {
            "context_window": m.get("context_length"),
            "capabilities": derive_capabilities(
                m.get("architecture"), m.get("supported_parameters")
            ),
            "name": m.get("name") or str(mid),
        }
    return out


async def get_openrouter_catalog() -> dict[str, dict]:
    """{model_id: {context_window, capabilities, name}} с TTL-кэшем; без ключа."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]
    async with _fetch_lock():
        # Повторная проверка ПОД локом: пока ждали, другой корутин мог уже перестроить
        # кэш — тогда не бьём в сеть повторно (это и есть single-flight).
        now = time.time()
        if _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL_SECONDS:
            return _cache["data"]
        return await _fetch_and_cache(now)


async def _fetch_and_cache(now: float) -> dict[str, dict]:
    """Перестроить каталог из сети и обновить кэш. Зовётся ТОЛЬКО под ``_fetch_lock``."""
    try:
        data = await _fetch_openrouter()
        if data:
            _cache["data"] = data
            _cache["ts"] = now
        return data or _cache["data"]
    except Exception:
        # ⚠️ WARNING, а не DEBUG: каталог — единственный источник и для
        # `model_supports_tools`, и для окна модели. Тихий отказ даёт две деградации,
        # выглядящие как норма: инструменты снимаются со всех моделей вне allowlist, а
        # окно падает до дефолтных 32k (компрессор жжёт до 39 вызовов впустую). Кэш
        # процессный и пустой при старте — при постоянном сбое это не эпизод, а состояние.
        stale = len(_cache["data"])
        logger.warning(
            "Каталог OpenRouter недоступен — инструменты и окно модели уходят в дефолт "
            "(в кэше моделей: %s)",
            stale,
            extra={"failure_code": "unavailable"},
        )
        return _cache["data"]


# Мемо «модель → умеет ли инструменты», ключ включает поколение каталога (см. ниже).
# Потолок держит память конечной: у агрегаторов 300+ моделей, а поколений за жизнь
# процесса накапливается сколько угодно.
_TOOL_SUPPORT_MEMO: dict[tuple[float, str], bool] = {}
_TOOL_SUPPORT_MEMO_MAX = 2048


def _remember_tool_support(key: tuple[float, str], value: bool) -> bool:
    if len(_TOOL_SUPPORT_MEMO) >= _TOOL_SUPPORT_MEMO_MAX:
        # Записи прошлых поколений уже не совпадут ни с одним ключом — чистим целиком,
        # это дешевле и честнее, чем вытеснять по одной.
        _TOOL_SUPPORT_MEMO.clear()
    _TOOL_SUPPORT_MEMO[key] = value
    return value


async def model_supports_tools(model_id: str) -> bool:
    """Умеет ли модель function-calling. Гейт перед отправкой `tools` в запрос.

    Обязателен: провайдеры без поддержки (часть RouterAI/GigaChat) отвечают 400 на
    неизвестное поле `tools` — без гейта мы бы роняли ответ на половине каталога.

    Знание уже жило в каталоге, но исполнительный путь его не читал: capabilities
    использовались ТОЛЬКО витриной пикера моделей. Каталог — лениво прогреваемый
    TTL-кэш, поэтому греем его явно (иначе в свежем процессе всё выглядит как
    «tools не поддерживаются»).
    """
    mid = str(model_id or "").strip()
    if not mid:
        return False

    # ⚠️ Мемо привязано к ПОКОЛЕНИЮ каталога, а не ко времени: вечный кэш означал бы, что
    # модель, у которой появились инструменты, навсегда осталась без них.
    # Нужно потому, что на одном запросе проверка идёт до пяти раз (гейты и цикл
    # фейловера), а каждая — разбор строки, allowlist, префиксы и пять вариантов ключа.
    memo_key = (_cache["ts"], mid)
    cached = _TOOL_SUPPORT_MEMO.get(memo_key)
    if cached is not None:
        return cached

    base = mid.split(":", 1)[0]
    if mid in TOOL_CAPABLE_ALLOWLIST or base in TOOL_CAPABLE_ALLOWLIST:
        return _remember_tool_support(memo_key, True)
    # Провайдеры вне каталога OpenRouter: capability знаем сами, иначе resolve_model_meta
    # вернёт {} и вся линейка GigaChat навсегда останется «без инструментов».
    if base.lower().startswith(TOOL_CAPABLE_PREFIXES):
        return _remember_tool_support(memo_key, True)
    catalog = await get_openrouter_catalog()
    # Ключ берём ПОСЛЕ прогрева: `get_openrouter_catalog` мог обновить каталог, и запись
    # под старым поколением была бы протухшей в момент создания.
    memo_key = (_cache["ts"], mid)
    supported = "tools" in (resolve_model_meta(mid, catalog).get("capabilities") or [])
    return _remember_tool_support(memo_key, supported)
