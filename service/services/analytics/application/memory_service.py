"""Фасад памяти для чат-пайплайна.

Докстринг раньше отсылал к слою `service.services.agents.integration`, которого
не существует: агентский домен уехал в сайдкар. Провайдеров памяти держит
`service.infrastructure.memory` (mem0 / MemOS / noop), выбор — по
`AGENTS__MEMORY_PROVIDER`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from typing import Any

from service.infrastructure.memory import get_memory_integration
from service.services.analytics.application import memory_cache
from service.services.analytics.application.ports.interfaces import MemoryIntegrationPort

# Модель для фоновой экстракции фактов. Фиксированная и надёжная — НЕ тянем
# каталог провайдера (list_available_models на 300+ моделях RouterAI подвисает на
# /models и валит экстракцию по таймауту). gpt-4o-mini есть у активного провайдера
# и отлично справляется с JSON-экстракцией.
_EXTRACTION_MODEL = "openai/gpt-4o-mini"
# Жёсткий потолок на весь LLM-вызов экстракции — фон не должен висеть вечно.
_EXTRACTION_TIMEOUT_SEC = 35.0

# Служебные/стоп-слова, не несущие смысла для сравнения фактов (RU+EN).
_FACT_STOPWORDS = frozenset(
    {
        "который",
        "которая",
        "пользователь",
        "помощник",
        "ассистент",
        "просил",
        "попросил",
        "хочет",
        "нужно",
        "также",
        "этот",
        "этой",
        "когда",
        "чтобы",
        "своей",
        "свою",
        "него",
        "user",
        "asked",
        "wants",
        "about",
        "that",
        "this",
        "with",
        "their",
        "them",
        "have",
        "assistant",
    }
)

# «Guardrails»-инструкция для извлечения долговременной памяти. Заменяет
# free-form экстракцию провайдера (которая писала англоязычный шум, разовые
# просьбы и служебные артефакты вроде ведущего «37») на строгий русскоязычный
# структурированный набор фактов о ПОЛЬЗОВАТЕЛЕ.
_FACT_EXTRACTION_SYSTEM = """\
Ты — экстрактор долговременной памяти GPTHub. Из диалога выдели ТОЛЬКО устойчивые
факты о ПОЛЬЗОВАТЕЛЕ, полезные в будущих разговорах.

Что сохранять (устойчивое):
- личность и контекст: имя, роль, профессия, компания, город, язык общения;
- предпочтения: стиль ответов, любимые технологии/инструменты, форматы;
- постоянные цели и ограничения пользователя.

🔴 ИСТОЧНИК ФАКТА — ТОЛЬКО РЕПЛИКИ «Пользователь:». Всё, что сказал «Ассистент:», фактом
не является НИКОГДА — даже когда сказано о пользователе. Ассистент предполагает, уточняет
и предлагает варианты; принимать это за свойство человека нельзя.
- «Ассистент: вы, похоже, начинающий программист» → НЕ факт (это догадка);
- «Ассистент: уточните уровень: новичок / средний / продвинутый?» → НЕ факт (это вопрос);
- «Ассистент: буду вашим терпеливым преподавателем» → НЕ факт (это про ассистента);
- но «Ассистент: вы новичок? / Пользователь: да» → факт ЕСТЬ, его подтвердил человек.

Что игнорировать (это НЕ факты о пользователе):
- разовые сиюминутные просьбы («проверь адрес», «напиши функцию», «переведи текст»);
- факты об ассистенте, о самой системе или о ходе диалога;
- догадки и домыслы — бери только явно сказанное или подтверждённое пользователем.

Строгие правила вывода:
- Пиши ТОЛЬКО на русском языке.
- Каждый факт — одно короткое утверждение в 3-м лице о пользователе.
- Без нумерации, без служебных префиксов, без markdown.
- Если устойчивых фактов нет — верни пустой список.

Верни РОВНО один JSON-объект, без пояснений и без markdown:
{"facts":[{"type":"identity|preference|context|constraint","key":"<1-3 слова>","value":"<факт одним предложением>"}]}
"""

logger = logging.getLogger(__name__)

_CONTEXT_HEADER = "## Контекст из памяти пользователя:"


def _build_facts_repo():
    """Свежий репозиторий фактов на общем (по циклу событий) движке PgConnector.

    Создаём per-call, а не кэшируем: PgConnector переиспользует class-level engine
    для текущего event loop и пересоздаёт его при смене цикла (важно для celery),
    поэтому кэширование инстанса связало бы нас со «старым» sessionmaker.
    """
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.analytics.persistence.memory_facts_repository import (
        MemoryFactsRepository,
    )
    from service.settings import config

    return MemoryFactsRepository(PgConnector(config.pg))


class MemoryService:
    """Facade for memory operations used by agent layer and background tasks."""

    def __init__(
        self,
        integration: MemoryIntegrationPort | None = None,
        facts_repo: Any | None = None,
    ) -> None:
        # integration (MemOS) остаётся как опциональный провайдер, но НЕ источник
        # истины для фактов — им владеет собственный реестр (facts_repo).
        self.integration = integration or get_memory_integration()
        self._facts_repo = facts_repo

    def _get_facts_repo(self) -> Any:
        if self._facts_repo is None:
            self._facts_repo = _build_facts_repo()
        return self._facts_repo

    @staticmethod
    def _content_hash(text: str) -> str:
        """Хэш нормализованного текста факта для дедупа на запись (upsert)."""
        norm = re.sub(r"[^0-9a-zа-яё ]", "", str(text or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    @classmethod
    def _dedupe_facts(cls, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Схлопнуть семантические near-duplicate факты.

        Два критерия «это один факт»:
        - Jaccard значимых слов ≥ 0.6 (разные формулировки одного факта);
        - вложенность множеств слов (одно ⊆ другого) — ловит «Данил» ⊆
          «Пользователь зовут Данил», где Jaccard всего 0.5 и не срабатывает.
        """
        out: list[dict[str, Any]] = []
        kept: list[set[str]] = []
        for fact in facts:
            words = cls._fact_signature_words(
                f"{fact.get('fact_key', '')} {fact.get('fact_value', '')}"
            )
            if words and any(
                words <= k or k <= words or len(words & k) / len(words | k) >= 0.6
                for k in kept
                if k
            ):
                continue
            if words:
                kept.append(words)
            out.append(fact)
        return out

    @staticmethod
    def _newest_per_key(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Один факт на ключ — САМЫЙ СВЕЖИЙ. Устаревшие в промпт не идут.

        🔴 Дедуп по хэшу и по Jaccard ловит ПОВТОР, но не ПРОТИВОРЕЧИЕ: «зовут Данил» и
        «зовут Мария Иванова» переживают оба фильтра. Замер по живой базе: пять значений
        ключа «имя» одновременно подмешивались в промпт, и модель выбирала между ними как
        придётся. Побеждает свежий: список приходит `ORDER BY updated_at DESC`.

        ⚠️ Отбрасываем ТОЛЬКО из промпта — в базе и панели остаются все: ключи из одного
        слова бывают законно множественными, и стирать данные по нашей эвристике нельзя.
        Пустой ключ не схлопывается: у безымянных фактов совпадение ключа ничего не значит.
        """
        out: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for fact in facts:
            key = str(fact.get("fact_key") or "").strip().lower()
            if key:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            out.append(fact)
        return out

    @classmethod
    def _rank_by_relevance(
        cls, facts: list[dict[str, Any]], query: str, top_k: int
    ) -> list[dict[str, Any]]:
        """Отобрать факты, ОТНОСЯЩИЕСЯ к текущему вопросу, а не просто свежие.

        🔴 Замер по живой базе: из 34 фактов в промпт уезжали 5 самых свежих — вопрос про
        Python получал «знак зодиака: близнец», а «язык: Python» не доезжал НИКОГДА.

        Оценка — доля значимых основ факта, встретившихся в запросе; значимые слова берём
        тем же `_fact_signature_words`, что и дедуп (два способа однажды разъедутся).

        ⚠️ `identity` получает НАДБАВКУ, а не безусловный пропуск: таких фактов 25 из 54,
        и «включать всегда» вытеснило бы всё остальное. При нулевой релевантности порядок
        остаётся по свежести — сортировка стабильна.
        """
        if not query or not str(query).strip():
            return facts[:top_k]
        query_stems = cls._stems(query)
        if not query_stems:
            return facts[:top_k]

        def _score(fact: dict[str, Any]) -> float:
            stems = cls._stems(f"{fact.get('fact_key', '')} {fact.get('fact_value', '')}")
            hit = len(stems & query_stems) / len(stems) if stems else 0.0
            # ⚠️ Надбавка МАЛЕНЬКАЯ намеренно. При 0.15 она перебивала любое совпадение
            # ниже 15%, и «знак зодиака» с «датой рождения» занимали места в ответе на
            # ЛЮБОЙ вопрос — тип `identity` не означает «полезно», он означает «про
            # человека». Разнимать равных — да, вытеснять попадание в тему — нет.
            bonus = 0.05 if str(fact.get("fact_type") or "") == "identity" else 0.0
            return hit + bonus

        return sorted(facts, key=_score, reverse=True)[:top_k]

    @classmethod
    def _stems(cls, text: str) -> set[str]:
        """Основы значимых слов — грубо, обрезкой хвоста.

        🔴 Без этого лексический отбор на русском почти не работает: «рефакторингА» в
        вопросе и «рефакторингОМ» в факте — РАЗНЫЕ токены, и факт про текущую задачу не
        находился. Полноценная лемматизация тянула бы словарь ради пяти строк промпта;
        шести символов основы хватает, чтобы склеить падежи и не склеить разные слова.
        """
        return {w[:6] for w in cls._fact_signature_words(text)}

    @staticmethod
    def _memory_user_scope(user_id: str) -> str:
        normalized = str(user_id or "").strip()
        if not normalized:
            return ""
        # Use explicit user-level namespace so memory is shared across all threads.
        return f"user:{normalized}"

    async def remember_conversation(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Записать реплики/саммери в семантическую память MemOS (граф + вектор).

        Postgres-реестр фактов ведётся отдельно (``extract_and_save_facts``) — это
        кураторский структурированный слой. Здесь наполняем MemOS, который сильнее
        как семантическая память (векторный поиск, связи, реорганизация) и питает
        dashboard. ``metadata`` тегирует запись (напр. ``{"kind": "summary"}``), чтобы
        позже фильтровать саммери. Best-effort: любой сбой проглатывается, чат не страдает.
        """
        if not user_id or not messages:
            return
        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return
        fn = getattr(self.integration, "save_messages", None)
        if fn is None or not getattr(self.integration, "available", False):
            return
        norm = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "").strip()}
            for m in messages
            if str(m.get("content") or "").strip()
        ]
        if not norm:
            return
        try:
            await fn(user_id=scoped_user_id, messages=norm, metadata=metadata)
        except Exception:
            logger.debug("MemOS remember_conversation failed", exc_info=True)
            return
        # Запись состоялась → счётчики дашборда устарели. Сбрасываем ЗДЕСЬ, а не по TTL:
        # человек, который только что поговорил, обязан увидеть это в панели сразу.
        await memory_cache.invalidate(scoped_user_id)

    async def recall_semantic(self, user_id: str, query: str, top_k: int = 3) -> str:
        """Семантически релевантные прошлые саммери/воспоминания из MemOS под текущий
        запрос (векторный поиск с порогом релевантности). Пусто, если MemOS недоступен
        или ничего релевантного — fail-open, чтобы не шуметь в контексте.
        """
        if not user_id or not query or not str(query).strip():
            return ""
        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return ""
        fn = getattr(self.integration, "list_facts", None)
        if fn is None or not getattr(self.integration, "available", False):
            return ""
        try:
            items = await fn(user_id=scoped_user_id, query=str(query).strip(), top_k=top_k)
        except Exception:
            logger.debug("MemOS recall failed", exc_info=True)
            return ""
        texts: list[str] = []
        seen: set[str] = set()
        for item in items or []:
            text = ""
            if isinstance(item, dict):
                for key in ("summary", "memory", "text", "content", "value", "fact_value"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
            elif isinstance(item, str):
                text = item.strip()
            if not text:
                continue
            norm = re.sub(r"\s+", " ", text.lower())
            if norm in seen:
                continue
            seen.add(norm)
            texts.append(text)
            if len(texts) >= top_k:
                break
        if not texts:
            return ""
        return "## Из долговременной памяти (похожие прошлые обсуждения):\n" + "\n".join(
            f"- {t}" for t in texts
        )

    async def get_memory_context(self, user_id: str, top_k: int = 5, query: str = "") -> str:
        if not user_id:
            return ""
        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return ""
        try:
            # ⚠️ Тянем ШИРОКО, а отбираем узко. Прежний потолок в 12 записей делал
            # релевантность бессмысленной: она выбирала бы из тех же свежих фактов, мимо
            # которых и уезжал нужный. Таблица на пользователя мелкая (десятки строк),
            # цена запроса не меняется.
            facts = await self._get_facts_repo().list_facts(
                user_id=scoped_user_id, limit=max(top_k * 10, 60)
            )
        except Exception:
            logger.debug("Memory context loading failed", exc_info=True)
            return ""
        # Порядок трёх фильтров несущий: сначала ПОВТОРЫ (разные формулировки одного
        # факта), потом ПРОТИВОРЕЧИЯ (один ключ — разные значения), и только потом отбор
        # по РЕЛЕВАНТНОСТИ. Иначе релевантность могла бы выбрать устаревшее значение
        # ключа просто потому, что оно словами ближе к вопросу.
        facts = self._rank_by_relevance(
            self._newest_per_key(self._dedupe_facts(facts)), query, max(1, top_k)
        )
        lines: list[str] = []
        for fact in facts:
            key = str(fact.get("fact_key") or "").strip()
            value = str(fact.get("fact_value") or "").strip()
            if not value:
                continue
            if key and key.lower() not in value.lower():
                lines.append(f"- {key}: {value}")
            else:
                lines.append(f"- {value}")
        if not lines:
            return ""
        return _CONTEXT_HEADER + "\n" + "\n".join(lines)

    async def extract_and_save_facts(
        self,
        user_id: str,
        thread_id: str,
        messages: list[dict[str, Any]],
        usage_out: dict[str, Any] | None = None,
    ) -> None:
        if not user_id or not messages:
            return

        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return

        # Своя структурированная экстракция (guardrails) вместо дампа сырого
        # диалога в MemOS: только устойчивые русскоязычные факты о пользователе,
        # без разовых просьб и англоязычного шума. Нет фактов → ничего не пишем.
        # ``usage_out`` (если передан) наполняется токенами LLM-вызова экстракции —
        # воркер по нему тарифицирует долговременную память.
        facts = await self._extract_structured_facts(messages, usage_out=usage_out)
        if not facts:
            return

        repo = self._get_facts_repo()
        for fact in facts:
            value = str(fact.get("value") or "").strip()
            if not value:
                continue
            key = str(fact.get("key") or "").strip() or value[:80]
            try:
                await repo.upsert_fact(
                    fact_id=str(uuid.uuid4()),
                    user_id=scoped_user_id,
                    fact_type=str(fact.get("type") or "general"),
                    fact_key=key,
                    fact_value=value,
                    content_hash=self._content_hash(f"{key} {value}"),
                    confidence=None,
                    source_thread_id=str(thread_id) if thread_id else None,
                )
            except Exception:
                logger.debug("Structured fact save failed", exc_info=True)

    @staticmethod
    def _format_transcript(messages: list[dict[str, Any]]) -> str:
        """Диалог для экстрактора. Реплики ассистента ПОМЕЧЕНЫ как несвидетельство.

        🔴 МЕТКА В КАЖДОЙ СТРОКЕ, А НЕ ПРАВИЛО В ШАПКЕ, и это разница между работает и нет.
        Замер: на диалоге «Пользователь: посчитай 2+2 / Ассистент: 4. Вы, похоже,
        начинающий программист и любите Python» в память уходило ДВА факта о пользователе —
        профессия и любимая технология. Человек не говорил ни того, ни другого.

        Общий запрет в системном промпте («догадки и домыслы») сократил это до одного факта,
        но не убрал: правило было далеко от данных, а «Ассистент: вы начинающий
        программист» выглядит утверждением о пользователе. Метка стоит вплотную к тексту, и
        пропустить её нельзя.

        ⚠️ Реплики ассистента всё равно НУЖНЫ: без них «да, совсем новичок» не к чему
        отнести, и подтверждённый человеком факт потерялся бы. Убирать их нельзя — можно
        только назвать тем, что они есть.
        """
        lines: list[str] = []
        for message in messages or []:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            speaker = (
                "Пользователь" if role in ("user", "human") else "Ассистент (НЕ ИСТОЧНИК ФАКТОВ)"
            )
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)[:6000]

    @staticmethod
    def _parse_facts(raw: str) -> list[dict[str, str]]:
        import json

        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(), flags=re.MULTILINE
        ).strip()
        if not cleaned:
            return []
        try:
            data = json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return []
            try:
                data = json.loads(match.group(0))
            except Exception:
                return []

        items = data.get("facts") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []

        allowed_types = {"identity", "preference", "context", "constraint", "general"}
        out: list[dict[str, str]] = []
        seen: list[set[str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            if len(value) < 3:
                continue
            # Только русскоязычные факты — отсекаем англоязычный вывод модели.
            if not re.search(r"[а-яё]", value.lower()):
                continue
            key = (str(item.get("key") or "").strip() or value[:40]).strip()
            ftype = str(item.get("type") or "general").strip().lower()
            if ftype not in allowed_types:
                ftype = "general"
            signature = MemoryService._fact_signature_words(f"{key} {value}")
            if signature and any(len(signature & s) / len(signature | s) >= 0.6 for s in seen if s):
                continue
            if signature:
                seen.append(signature)
            out.append({"type": ftype, "key": key, "value": value})
            if len(out) >= 12:
                break
        return out

    async def _extract_structured_facts(
        self,
        messages: list[dict[str, Any]],
        usage_out: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        transcript = self._format_transcript(messages)
        if not transcript.strip():
            return []
        # LLM-вызов идёт ЧЕРЕЗ ШЛЮЗ САЙДКАРА: провайдерами владеет он (ключи, политика,
        # фейловер), и второе мнение о том, кто жив, нам не нужно.
        try:
            from service.infrastructure.llm_gateway import chat_completion
            from service.settings import config as _cfg

            result = await asyncio.wait_for(
                chat_completion(
                    _cfg,
                    messages=[
                        {"role": "system", "content": _FACT_EXTRACTION_SYSTEM},
                        {"role": "user", "content": transcript},
                    ],
                    model=_EXTRACTION_MODEL,
                    temperature=0.0,
                    max_tokens=400,
                ),
                timeout=_EXTRACTION_TIMEOUT_SEC,
            )
            if result is None:
                return []
            raw, usage = result
            self._accumulate_usage(usage_out, usage)
        except Exception:
            logger.debug("Structured fact extraction failed", exc_info=True)
            return []
        return self._parse_facts(raw)

    @staticmethod
    def _accumulate_usage(usage_out: dict[str, Any] | None, usage: Any) -> None:
        """Сложить usage LLM-вызова экстракции в ``usage_out`` для биллинга памяти.

        ⚠️ Теперь usage приходит СЛОВАРЁМ из шлюза (OpenAI-формат), а не объектом SDK —
        читаем ключи, а не атрибуты. Промах здесь не падает, а тихо оставляет вызов
        неоплаченным, поэтому форма важна.
        """
        if usage_out is None or not isinstance(usage, dict):
            return
        try:
            usage_out["prompt"] = int(usage_out.get("prompt", 0) or 0) + int(
                usage.get("prompt_tokens", 0) or 0
            )
            usage_out["completion"] = int(usage_out.get("completion", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
            usage_out["total"] = int(usage_out.get("total", 0) or 0) + int(
                usage.get("total_tokens", 0) or 0
            )
            usage_out["model"] = _EXTRACTION_MODEL
        except Exception:
            logger.debug("Memory extraction usage accounting failed", exc_info=True)

    @staticmethod
    def _fact_signature_words(text: str) -> set[str]:
        """Значимые слова факта (для контент-дедупа near-duplicate записей).

        Нижний регистр, только буквенные токены длиной ≥4, без стоп-слов и
        числовых артефактов — так «37 пользователь попросил проверить адрес»
        и «пользователь просил проверить адрес машины» схлопываются в один.
        """
        words = re.findall(r"[a-zа-яё]{4,}", str(text or "").lower())
        return {w for w in words if w not in _FACT_STOPWORDS}

    async def dashboard(self, user_id: str) -> dict[str, Any]:
        """Дашборд памяти MemOS (факты по типам + счётчики) для пользователя. Только
        когда активен memos-провайдер; иначе {} (виджет покажет факты из БД как раньше).

        Ответ КЭШИРУЕТСЯ в Redis: замер — 124-172 мс на каждое открытие панели против 3 мс
        у фактов из Postgres (сеть до сайдкара, прогрев не помогает).

        🔴 TTL здесь НЕ единственный механизм: содержимое MemOS меняется после каждого
        разговора, и кэш только по времени означал бы «поговорил, открыл панель, память не
        сохранилась». Запись СБРАСЫВАЕТ кэш, TTL — страховка на изменения мимо нас.
        """
        if not user_id:
            return {}
        scoped = self._memory_user_scope(str(user_id))
        if not scoped:
            return {}
        fn = getattr(self.integration, "dashboard", None)
        if fn is None:
            return {}

        cached = await memory_cache.get(scoped)
        if cached is not None:
            return cached
        try:
            data = await fn(user_id=scoped) or {}
        except Exception:
            logger.debug("memory dashboard failed", exc_info=True)
            return {}
        # Пустой ответ не кэшируем: он значит «провайдер не memos ИЛИ ещё не ответил»,
        # и запомнить его на пять минут — то же самое, что спрятать память от человека,
        # который её только что наполнил.
        if data:
            await memory_cache.put(scoped, data)
        return data

    async def list_facts(
        self, user_id: str, query: str | None = None, top_k: int = 50
    ) -> list[dict[str, Any]]:
        if not user_id:
            return []

        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return []

        try:
            raw_facts = await self._get_facts_repo().list_facts(user_id=scoped_user_id, limit=top_k)
        except Exception:
            logger.debug("Facts listing failed", exc_info=True)
            return []
        # Факты уже структурированы (свой реестр). Остаётся семантический дедуп
        # near-duplicate записей (разные формулировки одного факта).
        facts = self._dedupe_facts([f for f in raw_facts if isinstance(f, dict)])
        # ⚠️ ПОМЕЧАЕМ, А НЕ ПРЯЧЕМ. В промпт идёт только свежий факт по ключу, но
        # панель обязана показать ВСЁ: расхождение видно только когда оба значения
        # рядом, а решение удалить лишнее — пользователя, не наше. Скрытая запись,
        # которая при этом влияет (или наоборот, не влияет) на ответы, необъяснима.
        live = {id(f) for f in self._newest_per_key(facts)}
        for fact in facts:
            fact["superseded"] = id(fact) not in live
        return facts

    async def add_fact(
        self, user_id: str, fact_type: str, fact_key: str, fact_value: str
    ) -> dict[str, Any]:
        if not user_id:
            return {}

        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return {}

        safe_type = (fact_type or "general").strip() or "general"
        safe_key = (fact_key or "").strip()
        safe_value = (fact_value or "").strip()
        if not safe_key or not safe_value:
            return {}

        fact_id = str(uuid.uuid4())
        try:
            await self._get_facts_repo().upsert_fact(
                fact_id=fact_id,
                user_id=scoped_user_id,
                fact_type=safe_type,
                fact_key=safe_key,
                fact_value=safe_value,
                content_hash=self._content_hash(f"{safe_key} {safe_value}"),
                confidence=None,
                source_thread_id=None,
            )
            return {
                "id": fact_id,
                "fact_type": safe_type,
                "fact_key": safe_key,
                "fact_value": safe_value,
                "confidence": None,
                "updated_at": None,
            }
        except Exception:
            logger.debug("Fact add failed", exc_info=True)
            return {}

    async def forget_everything(self, user_id: str) -> dict[str, Any]:
        """Стереть долговременную память пользователя ЦЕЛИКОМ: факты + MemOS.

        🔴 Хранилища ДВА. Стереть только факты — оставить человека с ассистентом, который
        «всё ещё помнит» (MemOS подмешивает похожие прошлые обсуждения), хотя список пуст.

        ⚠️ Отчёт раздельный: провайдер памяти может лежать, и тогда факты сотрутся, а
        MemOS нет — вызывающая сторона обязана мочь сказать правду, а не общий «ок».
        Порядок несущий: факты первыми — видимая половина убрана, даже если MemOS отвалится.
        """
        if not user_id:
            return {"facts_deleted": 0, "memos": {"ok": False, "reason": "no_user_id"}}
        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return {"facts_deleted": 0, "memos": {"ok": False, "reason": "no_user_id"}}

        facts_deleted = 0
        facts_error: str | None = None
        try:
            facts_deleted = await self._get_facts_repo().delete_all_facts(user_id=scoped_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory facts wipe failed", exc_info=True)
            facts_error = type(exc).__name__

        fn = getattr(self.integration, "forget_user", None)
        if fn is None:
            memos: dict[str, Any] = {"ok": False, "reason": "provider_has_no_wipe"}
        else:
            try:
                memos = await fn(user_id=scoped_user_id) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("MemOS wipe failed", exc_info=True)
                memos = {"ok": False, "error": type(exc).__name__}

        # Дашборд считался по прежнему содержимому — без сброса панель показала бы
        # счётчики стёртой памяти ещё пять минут, и это читалось бы как «не удалилось».
        await memory_cache.invalidate(scoped_user_id)

        result: dict[str, Any] = {"facts_deleted": facts_deleted, "memos": memos}
        if facts_error:
            result["facts_error"] = facts_error
        return result

    async def delete_fact(self, user_id: str, fact_id: str) -> bool:
        if not user_id or not fact_id:
            return False

        scoped_user_id = self._memory_user_scope(str(user_id))
        if not scoped_user_id:
            return False

        try:
            return await self._get_facts_repo().delete_fact(user_id=scoped_user_id, fact_id=fact_id)
        except Exception:
            logger.debug("Fact delete failed", exc_info=True)
            return False
