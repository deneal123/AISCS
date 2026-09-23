"""Адаптивное сжатие крупных источников контекста под выделенный им бюджет.

Раньше большой документ просто резался по хвосту (``[:15000]`` символов на загрузке,
затем ``[:8000]`` на входе модального аналитика), то есть модель физически не видела
вторую половину файла. Здесь источник **сжимается целиком**: если он не влезает в
свою долю бюджета, он разбивается на куски, каждый пересказывается дешёвой моделью,
а затем сводка сводок ужимается под целевой размер (map-reduce).

Два свойства, ради которых это устроено именно так:

* **Целевой размер — адаптивный.** Не фиксированные 700 токенов, а ровно та доля,
  которую ассемблер выделил секции. На модели со 128k окном документ переживёт
  сжатие почти нетронутым, на 32k — ужмётся сильнее. Один протокол, разный масштаб.
* **Не платим, когда не нужно.** Влезает в бюджет — LLM не зовём вообще. Результат
  кэшируется по хэшу содержимого и целевому размеру, поэтому один и тот же файл не
  пересжимается на каждой реплике диалога.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext
from service.domain.usage_ledger import UsageKind
from service.shared.redis_client import get_redis
from service.shared.token_budget import (
    chars_for_tokens,
    estimate_tokens,
    trim_text_to_tokens,
)

logger = logging.getLogger(__name__)

# Сколько токенов исходника отдаём модели за один вызов при map-фазе.
_CHUNK_TOKENS = 6000
# Потолок на число кусков: защита от гигантского файла, который иначе сгенерил бы
# сотни LLM-вызовов. Что не влезло — досжимается обрезкой (честно помечается).
_MAX_CHUNKS = 12
# Одновременных map-вызовов к провайдеру. Не 12: дюжина параллельных запросов к одному
# провайдеру легко ловит 429, и выигрыш съедается ретраями.
_MAP_CONCURRENCY = 4
# Кэш сжатия живёт долго: содержимое адресуется хэшем, протухать нечему.
_CACHE_TTL_SEC = 7 * 24 * 3600

_PROMPTS = {
    "files": (
        "Ты сжимаешь содержимое документа для передачи другой модели. Сохрани ВСЕ факты, "
        "числа, имена, даты, выводы и структуру. Убери воду и повторы. Не выдумывай "
        "ничего, чего нет в тексте. Пиши по-русски, плотно."
    ),
    "memory": (
        "Ты сжимаешь выдержки из долговременной памяти о пользователе. Сохрани факты, "
        "предпочтения и решения. Только суть, без воды. Не выдумывай."
    ),
}
_DEFAULT_PROMPT = _PROMPTS["files"]


# Шаг квантования целевого бюджета в ключе кэша.
#
# ⚠️ Без него кэш промахивался по устройству: `target` — доля секции, и она плывёт на
# десятки токенов от того, какие ДРУГИЕ секции присутствуют. Каждый промах — до 13
# провайдерских вызовов. 500 съедает дрейф, но не склеивает заведомо разные бюджеты:
# пересказ на 500 и на 5000 токенов — разные тексты.
_TARGET_BUCKET_TOKENS = 500


def _cache_key(raw: str, target: int, kind: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:32]
    bucket = max(1, int(target) // _TARGET_BUCKET_TOKENS)
    return f"gpthub:agents:ctx_compress:{kind}:b{bucket}:{digest}"


def _split(text: str, chunk_tokens: int) -> list[str]:
    """Порезать текст на куски примерно по ``chunk_tokens``, стараясь рвать по абзацам."""
    chunk_chars = max(1, chars_for_tokens(chunk_tokens))
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= chunk_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
        # Абзац сам по себе длиннее куска — режем его жёстко.
        while len(para) > chunk_chars:
            chunks.append(para[:chunk_chars])
            para = para[chunk_chars:]
        buf = para
    if buf:
        chunks.append(buf)
    return chunks


async def _pick_model() -> str | None:
    """Модель для сжатия — ОДИН раз на весь map-reduce, а не на каждый кусок.

    ⚠️ Резолв стоял внутри `_summarize`, то есть выполнялся НА КАЖДЫЙ вызов: до 12 кусков
    на секцию, секций три, и все три сжимаются параллельно — до ~36 обращений к каталогу
    на один запрос пользователя. При тёплом кэше это дёшево, но `list_available_models`
    не имеет single-flight: в момент истечения TTL все они уходят в перестройку каталога
    одновременно, а перестройка — это `gather` по пяти провайдерам с таймаутом на каждого.
    То есть самый дорогой момент совпадал с самым многолюдным.

    Плюс `pick_text_model` — regex по трёмстам с лишним строкам каталога, синхронно, в
    том же цикле событий.
    """
    from service.domain.client import list_qualified_models
    from service.domain.subagents.utils import pick_text_model

    return pick_text_model(await list_qualified_models())


async def _summarize(
    text: str,
    target_tokens: int,
    kind: str,
    execution: RunExecutionContext | None = None,
    model: str = "",
    *,
    personalized: bool = False,
) -> str:
    """Один LLM-вызов: пересказать ``text`` не длиннее ``target_tokens``.

    Execution context обязателен: это настоящий провайдерский вызов, и он тут не
    один: map-reduce делает до 12 вызовов НА СЕКЦИЮ, а сжимаемых секций три — до 39 на
    один запрос пользователя. Все они были бесплатными для пользователя и платными для
    платформы, причём ровно на самых дорогих запросах (большое вложение).

    ``model`` пустая — резолвим сами (прямые вызовы и тесты); штатный путь передаёт
    выбранную заранее, см. :func:`_pick_model`.
    """
    from service.domain.client import create_chat_completion

    model = model or (await _pick_model() or "")
    if not model:
        return ""
    system = _PROMPTS.get(kind, _DEFAULT_PROMPT)
    if personalized:
        # 🔴 Только на REDUCE: `_summarize` зовётся на каждый map-кусок — до 39 вызовов на
        # запрос, и личность умножилась бы на 39 там, где и без того дороже всего. На
        # reduce вызов один, а решает он то же: что сохранить, когда места мало.
        from service.domain import persona

        system = persona.current().wrap(system, "compression")
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.META,
        execution=execution,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Уложись примерно в {target_tokens} токенов.\n\n"
                    f"Текст:\n{text}\n\nСжатое изложение:"
                ),
            },
        ],
        model=model,
        temperature=0.2,
        max_tokens=target_tokens,
    )
    resp = result.response
    return first_message_content(resp).strip()


async def _map_chunks(
    chunks: list[str], target: int, kind: str, execution: RunExecutionContext | None, model: str
) -> list[str]:
    """map-фаза: каждый кусок → выжимка, пропорциональная его доле в бюджете.

    ⚠️ ПАРАЛЛЕЛЬНО. Куски независимы по определению map-reduce, а шли строго по одному:
    до 12 полноценных LLM-вызовов подряд, каждый с ретраями и фейловером. На запросе с
    крупным вложением это десятки секунд ТИШИНЫ до первого токена — и это лишь одна
    секция из трёх сжимаемых.

    Семафор нужен: без него дюжина одновременных запросов к одному провайдеру легко
    ловит 429, и «ускорение» превращается в цепочку ретраев.

    ``model`` приходит СНАРУЖИ и одна на всю фазу: раньше каждый кусок резолвил её сам,
    то есть ходил за каталогом моделей — до ~36 обращений на запрос.
    """
    per_chunk = max(200, target // max(1, len(chunks)))
    gate = asyncio.Semaphore(_MAP_CONCURRENCY)

    async def _summarize_chunk(chunk: str) -> str:
        async with gate:
            try:
                return await _summarize(chunk, per_chunk, kind, execution, model=model)
            except Exception:
                logger.warning("context compression failed code=internal")
                return ""

    # `gather` сохраняет ПОРЯДОК результатов — для склейки пересказов это существенно.
    summaries = await asyncio.gather(*(_summarize_chunk(c) for c in chunks))
    return [s for s in summaries if s]


async def compress_to_budget(
    raw: str, target: int, kind: str = "files", *, execution: RunExecutionContext | None = None
) -> str:
    """Сжать источник до ``target`` токенов, обработав его ЦЕЛИКОМ (map-reduce).

    Возвращает пустую строку, если сжать не удалось — вызывающий (``_fit``
    ассемблера) тогда честно обрежет текст по хвосту.
    """
    text = str(raw or "").strip()
    if not text or target <= 0:
        return ""
    if estimate_tokens(text) <= target:
        return text  # влезает — LLM не трогаем

    key = _cache_key(text, target, kind)
    # Redis — СВОЙ, сайдкара. Раньше здесь импортировался RedisManager из backend'а,
    # которого в сайдкаре нет: импорт молча падал, кэш не работал НИКОГДА, и каждое
    # сжатие заново гоняло map-reduce по ЛЛМ — платили за одну и ту же работу повторно.
    redis_client = get_redis()
    if redis_client is not None:
        try:
            cached = await redis_client.get(key)
            if cached:
                return cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        except Exception:  # noqa: BLE001 — кэш необязателен, считаем заново
            logger.debug("compression cache unavailable", extra={"failure_code": "unavailable"})
            redis_client = None

    chunks = _split(text, _CHUNK_TOKENS)
    dropped = 0
    if len(chunks) > _MAX_CHUNKS:
        dropped = len(chunks) - _MAX_CHUNKS
        chunks = chunks[:_MAX_CHUNKS]
        # Хвост исходника до модели НЕ доедет. Пометка в промпте уже есть, но она
        # адресована модели, а не нам: в трейсе и логах это должно быть видно, иначе
        # «почему ответ не учитывает конец документа» нечем объяснить.
        logger.warning(
            "Документ (%s) длиннее %d кусков — отброшено %d фрагментов хвоста",
            kind,
            _MAX_CHUNKS,
            dropped,
        )

    model = await _pick_model()
    if not model:
        return ""
    parts = await _map_chunks(chunks, target, kind, execution, model)
    if not parts:
        return ""

    # ⚠️ Частичная потеря — самый коварный исход: всё «получилось», а в середине документа
    # дыра, и модель уверенно отвечает по тексту, часть которого не читала. Пропуск
    # помечаем в тексте: пусть лучше скажет «фрагмент недоступен».
    lost = len(chunks) - len(parts)
    if lost:
        logger.warning("Потеряно %d из %d кусков при сжатии (%s)", lost, len(chunks), kind)

    merged = "\n\n".join(parts)
    if lost:
        merged += f"\n\n[…{lost} фрагментов исходника не удалось обработать — они пропущены]"
    if dropped:
        merged += f"\n\n[…не поместилось {dropped} фрагментов исходника]"

    # reduce: если сводок много и вместе они всё ещё не влезают — сжимаем ещё раз.
    if estimate_tokens(merged) > target and len(parts) > 1:
        try:
            reduced = await _summarize(
                merged, target, kind, execution, model=model, personalized=True
            )
            if reduced:
                merged = reduced
        except Exception:
            logger.debug("compression reduce unavailable", extra={"failure_code": "unavailable"})

    # Модель должна видеть РЕАЛЬНОЕ содержимое, а не только пересказ — иначе на
    # «проанализируй файл» отвечает «не вижу прикреплённый файл». Пересказ выходит сильно
    # меньше бюджета, и простаивающее место заполняем сырой головой файла.
    if kind == "files":
        gap = target - estimate_tokens(merged)
        if gap > 300:
            head = trim_text_to_tokens(text, gap - 40)
            if head.strip():
                merged = (
                    f"### Содержимое приложенного файла (начало, как есть):\n{head}\n\n"
                    f"### Сжатый пересказ файла целиком:\n{merged}"
                )

    if redis_client is not None and merged:
        try:
            await redis_client.set(key, merged, ex=_CACHE_TTL_SEC)
        except Exception:
            # ⚠️ WARNING, а не `pass`: отказ ЗАПИСИ не виден ниоткуда — чтение просто
            # промахивается, ответ правильный, наружу только счёт от провайдера. Так этот
            # кэш уже был мёртв: до 39 вызовов на запрос и заметить нечем. Промах чтения
            # нормален (первый заход, протухание), неудачная запись — нет.
            logger.warning(
                "compression cache write unavailable",
                extra={"failure_code": "unavailable"},
            )

    return merged


def make_compressor(config, *, execution: RunExecutionContext | None = None):
    """Сжиматель для ассемблера — или ``None``, если сжатие выключено настройкой.

    ``None`` означает «умещать обрезкой», то есть прежнее поведение.

    ⚠️ Накопитель токенов захватывается ЗАМЫКАНИЕМ, а не добавляется в контракт
    `Compressor`. Так ассемблеру не нужно знать про биллинг: он про умещение в бюджет, а
    кто и как платит за сжатие — забота того, кто сжиматель создал.
    """
    try:
        from service.shared.agent_settings import runtime_settings

        enabled = runtime_settings.get_agents(
            "context_compression_enabled", config.agents.context_compression_enabled
        )
    except Exception:
        enabled = getattr(config.agents, "context_compression_enabled", True)

    if not enabled:
        return None

    async def _compressor(raw: str, target: int, kind: str) -> str:
        return await compress_to_budget(raw, target, kind, execution=execution)

    return _compressor
