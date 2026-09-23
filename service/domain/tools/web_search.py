"""Web search and URL parsing service using DuckDuckGo and httpx."""

import asyncio
import base64
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

_MAX_URL_REDIRECTS = 5


# SSRF-защита переехала в gpthub_core: её используют и веб-поиск (здесь), и скачивание
# репозитория (backend). Копия неизбежно отстала бы — кто-то добавит приватный диапазон
# в одну и забудет в другой, — и отставшая половина станет дырой.
from service.domain.tools.search_parsers import (  # noqa: E402
    _Hit,
    _parse_bing,
    _parse_brave,
    _parse_duckduckgo,
    _parse_duckduckgo_lite,
    _parse_external_anchors,
    _parse_yandex,
    _strip_html,
)
from service.shared.net_guard import UnsafeUrlError, assert_public_host  # noqa: E402

_assert_public_host = assert_public_host


async def _fetch_url_safely(url: str, headers: dict, timeout: float) -> httpx.Response:
    """GET a URL while blocking SSRF: validates scheme/host before each hop, no auto-redirects."""
    current_url = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_URL_REDIRECTS + 1):
            parsed = urlparse(current_url)
            if parsed.scheme not in ("http", "https"):
                raise UnsafeUrlError(f"Unsupported URL scheme: {parsed.scheme}")
            await _assert_public_host(parsed.hostname or "")
            resp = await client.get(current_url, headers=headers)
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                # str(), а не human_repr(): у httpx.URL такого метода нет (он из yarl).
                # Из-за этого ЛЮБОЙ редирект ронял разбор ссылки с AttributeError вместо
                # того, чтобы за ним последовать.
                current_url = str(httpx.URL(current_url).join(resp.headers["location"]))
                continue
            resp.raise_for_status()
            return resp
    raise UnsafeUrlError("Too many redirects")


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.9",
}


def _is_external_result_url(url: str) -> bool:
    candidate = str(url or "").strip().lower()
    if not candidate.startswith(("http://", "https://")):
        return False
    blocked = (
        "duckduckgo.com",
        "duck.com",
        "bing.com",
        "bing.com/ck/a",
        "search.brave.com/search",
        "imgs.search.brave.com",
        "yandex.ru/search",
        "yandex.com/search",
        "yandex.ru/clck",
        "yandex.com/clck",
    )
    return not any(host in candidate for host in blocked)


def _normalize_result_url(raw_url: str) -> str:
    url = unescape(str(raw_url or "")).strip()

    # DuckDuckGo redirect format
    if "uddg=" in url:
        actual = re.search(r"uddg=([^&]+)", url)
        url = unquote(actual.group(1)) if actual else url

    # Protocol-relative URL
    if url.startswith("//"):
        url = "https:" + url

    # Bing redirect format: /ck/a?...&u=a1<base64url>
    if url.startswith("/"):
        url = f"https://www.bing.com{url}"
    if "bing.com/ck/a" in url:
        try:
            parsed = urlparse(url)
            u_val = (parse_qs(parsed.query).get("u") or [""])[0]
            if u_val.startswith("a1"):
                u_val = u_val[2:]
            if u_val:
                padding = "=" * ((4 - (len(u_val) % 4)) % 4)
                decoded = base64.urlsafe_b64decode((u_val + padding).encode("utf-8")).decode(
                    "utf-8", "ignore"
                )
                if decoded.startswith(("http://", "https://")):
                    url = decoded
        except Exception:
            logger.debug("search redirect decode failed", extra={"failure_code": "invalid"})

    # Yandex redirect/search formats
    try:
        parsed = urlparse(url)
        if parsed.netloc.endswith(("yandex.ru", "yandex.com")):
            qs = parse_qs(parsed.query)
            if qs.get("url"):
                target = unquote((qs.get("url") or [""])[0])
                if target.startswith(("http://", "https://")):
                    url = target
    except Exception:
        logger.debug("search URL normalization failed", extra={"failure_code": "invalid"})

    return url


@dataclass(frozen=True)
class _Engine:
    """Поисковый движок: куда сходить и чем разобрать ответ.

    ``parsers`` — по порядку: следующий пробуется, только если предыдущий ничего не
    дал (у Brave так устроен запасной разбор по якорям). ``urls`` — то же самое для
    зеркал одного движка.
    """

    name: str
    urls: tuple[str, ...]
    parsers: tuple[Callable[[str], list[_Hit]], ...]
    # DDG — основной движок, а не рядовой фолбэк: её сбой логируем громко.
    loud: bool = False


_ENGINES: tuple[_Engine, ...] = (
    _Engine(
        "duckduckgo",
        ("https://html.duckduckgo.com/html/?q={q}", "https://duckduckgo.com/html/?q={q}"),
        (_parse_duckduckgo,),
        loud=True,
    ),
    _Engine(
        "duckduckgo-lite", ("https://lite.duckduckgo.com/lite/?q={q}",), (_parse_duckduckgo_lite,)
    ),
    _Engine("bing", ("https://www.bing.com/search?q={q}",), (_parse_bing,)),
    _Engine(
        "brave",
        ("https://search.brave.com/search?q={q}",),
        (_parse_brave, _parse_external_anchors),
    ),
    _Engine("yandex", ("https://yandex.ru/search/?text={q}",), (_parse_yandex,)),
)


# ⚠️ ЗАЧЕМ ЭТО ЗДЕСЬ, А НЕ КОНСТАНТОЙ 15, КАК БЫЛО.
#
# Бюджет поиска складывается из ДВУХ чисел в РАЗНЫХ файлах: сколько даём одному движку
# (здесь) и сколько всего готовы ждать (`wait_for` у вызывающих). Они разъехались:
# движку давали 15 с, а всему поиску — 16 с. Когда первый движок тормозит (типичный
# anti-bot: соединение живо, ответ не идёт), он съедал весь бюджет целиком, и ЧЕТЫРЕ
# движка из пяти не запускались НИКОГДА. Отказоустойчивость была написана, оплачена
# кодом и тестами — и не работала ни разу.
#
# Замерено: первый движок держит 16.0 с, до bing/brave/yandex очередь не доходит.
#
# Оба числа теперь выводятся из одного места и связаны формулой, а не совпадением:
# внешний бюджет ДОЛЖЕН вмещать всю цепочку. Настройкой, а не константой, потому что
# подкручивать это будут по живым логам, а не пересборкой образа.
_DEFAULT_SEARCH_TIMEOUT = 5.0


def _search_timeout() -> float:
    """Сколько секунд даём ОДНОМУ движку."""
    try:
        from service.settings import config
        from service.shared.agent_settings import runtime_settings

        value = runtime_settings.get_agents(
            "search_engine_timeout_sec",
            getattr(config.agents, "search_engine_timeout_sec", _DEFAULT_SEARCH_TIMEOUT),
        )
        return max(1.0, float(value))
    except Exception:  # noqa: BLE001 — поиск не должен падать из-за настройки
        return _DEFAULT_SEARCH_TIMEOUT


def search_budget_sec() -> float:
    """Сколько ждать ВЕСЬ поиск: цепочка движков плюс запас на разбор.

    Единственный источник правды для внешнего `wait_for`. Раньше это число жило
    константой у каждого вызывающего и разъезжалось с внутренним — так и получилось,
    что фолбэки стали недостижимы.
    """
    return _search_timeout() * len(_ENGINES) + 1.0


def _collect(results: list[dict], hits: Iterable[_Hit], limit: int) -> None:
    """Досыпать находки в ``results``: нормализация, внешность, дедуп, потолок."""
    for raw_url, title, snippet in hits:
        if len(results) >= limit:
            return
        normalized = _normalize_result_url(raw_url)
        if not _is_external_result_url(normalized):
            continue
        normalized = normalized.strip()
        if any((r.get("url") or "") == normalized for r in results):
            continue
        results.append(
            {
                "title": (title or "").strip(),
                "url": normalized,
                "snippet": (snippet or "").strip(),
            }
        )


async def _query_engine(
    client: httpx.AsyncClient,
    engine: _Engine,
    encoded_query: str,
    results: list[dict],
    num_results: int,
) -> None:
    """Обойти зеркала движка и его парсеры, пока не наберётся хоть что-то."""
    for template in engine.urls:
        resp = await client.get(template.format(q=encoded_query), headers=_HEADERS)
        resp.raise_for_status()
        for parse in engine.parsers:
            _collect(results, parse(resp.text), num_results)
            if results:
                return


async def web_search(query: str, num_results: int = 5, *, stats: dict | None = None) -> list[dict]:
    """Search the web using DuckDuckGo HTML and return results.

    Движки — именно ФОЛБЭКИ: следующий пробуется, только если предыдущие не дали
    вообще ничего. Это дороже по латентности, но иначе один упавший движок означал бы
    пустую выдачу.

    🔴 ``stats`` РАЗЛИЧАЕТ ДВА ПУСТЫХ ОТВЕТА, которые прежде выглядели одинаково:
    «движки ответили, находок нет» и «не ответил НИ ОДИН». Первое — законный результат
    поиска, второе — неоказанная услуга, и брать за неё надбавку нельзя. Замерено: все
    движки отвалились по таймауту, вызывающий увидел пустой список, счёл его ответом
    «ничего не найдено» — и с человека взяли 833 кредита сверх токенов.

    Returns list of {title, url, snippet}.
    """
    results: list[dict] = []
    answered = 0
    encoded_query = quote_plus(query)
    per_engine = _search_timeout()

    for engine in _ENGINES:
        if results:
            break
        try:
            async with httpx.AsyncClient(timeout=per_engine, follow_redirects=True) as client:
                # ⚠️ ТАЙМАУТ ЖЁСТКИЙ, А НЕ ТОЛЬКО У КЛИЕНТА. `httpx` отмеряет его на
                # операцию (соединение, чтение), а движок может тянуть ответ порциями и
                # держать нас дольше собственного лимита. Внешний бюджет тогда истекал
                # на первом же движке — см. историю в `_search_timeout`.
                await asyncio.wait_for(
                    _query_engine(client, engine, encoded_query, results, num_results),
                    timeout=per_engine,
                )
                answered += 1
        except Exception:
            if engine.loud:
                logger.warning("web search engine failed code=unavailable")
            else:
                logger.debug("web search fallback failed code=unavailable")

    if not results:
        logger.warning("web search returned no results code=empty")
    if stats is not None:
        stats["engines_answered"] = answered

    return results


async def parse_url(url: str, max_chars: int = 5000) -> dict:
    """Fetch and extract text content from a URL.

    Returns {url, title, content, error}.
    """
    normalized_url = str(url or "").strip()
    if normalized_url and not re.match(r"^https?://", normalized_url, re.I):
        normalized_url = f"https://{normalized_url}"

    try:
        resp = await _fetch_url_safely(normalized_url, headers=_HEADERS, timeout=20)
        html = resp.text

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = _strip_html(title_match.group(1)) if title_match else ""

        content = ""
        for selector in [
            r"<article[^>]*>(.*?)</article>",
            r"<main[^>]*>(.*?)</main>",
            r'class="content"[^>]*>(.*?)</div>',
            r'class="post-content"[^>]*>(.*?)</div>',
            r"<body[^>]*>(.*?)</body>",
        ]:
            match = re.search(selector, html, re.S | re.I)
            if match:
                content = _strip_html(match.group(1))
                if len(content) > 100:
                    break

        # Fallback: извлекаем текст из параграфов, если «большие» блоки не помогли.
        if not content or len(content) < 100:
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I)
            if paragraphs:
                joined = "\n".join(_strip_html(p) for p in paragraphs)
                joined = re.sub(r"\s+", " ", joined).strip()
                if len(joined) > len(content):
                    content = joined

        # Fallback для тяжёлых JS-страниц/anti-bot: берём description из head.
        if not content:
            desc_match = re.search(
                r'<meta[^>]+(?:name="description"|property="og:description")[^>]+content="([^"]+)"',
                html,
                re.I,
            )
            if desc_match:
                content = _strip_html(desc_match.group(1))

        if not content:
            content = _strip_html(html)

        if len(content) > max_chars:
            content = content[:max_chars] + "..."

        return {"url": normalized_url, "title": title, "content": content, "error": None}

    except Exception:
        logger.warning("web page parsing failed code=unavailable")
        return {"url": normalized_url, "title": "", "content": "", "error": "unavailable"}
