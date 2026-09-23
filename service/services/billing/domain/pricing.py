"""Чистая доменная логика ценообразования (без I/O).

Переводит фактическое потребление (токены по вызовам + использованные
инструменты) в абстрактные кредиты по формуле с заложенной маржой:

    cost_call   = prompt/1000 * price_in + completion/1000 * price_out
    billable    = Σ(cost_call × маржа_модели) + Σ(surcharge × маржа_глоб)
    billable   *= complexity_factor                      # за сложные запросы
    credits     = ceil(billable / credit_unit_rub)
    credits     = max(credits, min_credits_per_request)  # анти-демпинг

Маржа на модель может переопределяться (``margin_override``); иначе берётся
глобальная. Всё в Decimal — деньги не считаем во float.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


@dataclass(frozen=True)
class ModelPrice:
    """Цена модели (₽ за 1K токенов) + опциональная пер-модельная маржа."""

    price_in_rub_per_1k: Decimal
    price_out_rub_per_1k: Decimal
    margin_override: Decimal | None = None


@dataclass(frozen=True)
class PricingParams:
    credit_unit_rub: Decimal
    margin_multiplier: Decimal
    complexity_factor_complex: Decimal
    min_credits_per_request: int


@dataclass(frozen=True)
class PriceResult:
    credits: int
    raw_cost_rub: Decimal  # себестоимость без маржи (для reconcile)
    billable_rub: Decimal  # после маржи и complexity (основа кредитов)
    # Сколько кредитов из `credits` пришлось на НАДБАВКИ за инструменты.
    #
    # 🔴 Не украшение. Замер по живому сообщению: 2193+739 токенов на GigaChat дали 733
    # кредита, а списано 1567 — надбавка за веб-поиск (1₽ × маржу) составила БОЛЬШЕ
    # ПОЛОВИНЫ счёта. В интерфейсе рядом стояли «2.9k т.» и «1567 кр.», из чего читалось,
    # будто столько стоят токены. Счёт был верен, а объяснить его пользователь не мог.
    #
    # Считается ВЫЧИТАНИЕМ второго прогона той же формулы, а не отдельным выражением:
    # потолок и complexity нелинейны, и повторённая формула разошлась бы с настоящей.
    surcharge_credits: int = 0


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def call_cost_rub(prompt_tokens: int, completion_tokens: int, price: ModelPrice) -> Decimal:
    """Себестоимость одного LLM-вызова (₽) без маржи."""
    thousand = Decimal(1000)
    p = (Decimal(int(prompt_tokens)) / thousand) * price.price_in_rub_per_1k
    c = (Decimal(int(completion_tokens)) / thousand) * price.price_out_rub_per_1k
    return p + c


def compute_credits(
    *,
    per_call_prices: Iterable[tuple[int, int, ModelPrice]],
    tool_surcharges_rub: Iterable[Decimal],
    is_complex: bool,
    params: PricingParams,
) -> PriceResult:
    """Свести потребление к кредитам.

    ``per_call_prices`` — последовательность (prompt, completion, ModelPrice)
    по каждому LLM-вызову запроса. ``tool_surcharges_rub`` — надбавки за
    инструменты (уже как Decimal-суммы). Маржа применяется пер-вызов (с учётом
    override), к надбавкам — глобальная.
    """
    if params.credit_unit_rub <= 0:
        raise ValueError("credit_unit_rub must be > 0")

    raw_cost = Decimal(0)
    billable = Decimal(0)

    for prompt_tokens, completion_tokens, price in per_call_prices:
        cost = call_cost_rub(prompt_tokens, completion_tokens, price)
        margin = (
            price.margin_override if price.margin_override is not None else params.margin_multiplier
        )
        raw_cost += cost
        billable += cost * margin

    tokens_only_billable = billable
    for surcharge in tool_surcharges_rub:
        surcharge = _to_decimal(surcharge)
        raw_cost += surcharge
        billable += surcharge * params.margin_multiplier

    complexity_factor = params.complexity_factor_complex if is_complex else Decimal(1)
    billable *= complexity_factor

    credits_int = _to_credits(billable, params)
    # Доля надбавок — РАЗНИЦА двух прогонов одной формулы. Отдельное выражение
    # («надбавка × маржа / единица») разошлось бы с настоящим счётом: и complexity, и
    # округление вверх, и минимум применяются к СУММЕ, а не к слагаемым.
    surcharge_credits = credits_int - _to_credits(tokens_only_billable * complexity_factor, params)
    return PriceResult(
        credits=credits_int,
        raw_cost_rub=raw_cost,
        billable_rub=billable,
        surcharge_credits=max(surcharge_credits, 0),
    )


def _to_credits(billable_rub: Decimal, params: PricingParams) -> int:
    credits = (billable_rub / params.credit_unit_rub).to_integral_value(rounding=ROUND_CEILING)
    return max(int(credits), int(params.min_credits_per_request))


def resolve_model_price(
    model_id: str | None,
    *,
    registry: Mapping[object, ModelPrice],
    provider: str | None = None,
    classify: Callable[[str], str | None],
    class_prices: Mapping[str, ModelPrice],
    default_price: ModelPrice,
) -> ModelPrice:
    """Fallback-цепочка цены: provider+registry → общий registry → класс → дефолт.

    ``classify`` — callable(model_id) -> str|None (имя класса, напр. 'fast').

    Явная цена 0/0 трактуется как «не задана» и уходит в fallback: модель, за
    которую мы платим провайдеру, не должна биллиться в ноль (частая дыра в данных
    — импортированные media-модели с нулевой ценой). Частичный ноль валиден
    (эмбеддинги: вход>0, выход=0) и сохраняется.
    """
    key = (model_id or "").strip()
    provider_key = (provider or "").strip().lower()
    if not provider_key and ":" in key:
        candidate, _, candidate_model = key.partition(":")
        known_providers = {"openai", "openrouter", "routerai", "gigachat", "mws"}
        if candidate.lower() in known_providers and candidate_model:
            provider_key, key = candidate.lower(), candidate_model
    # В реестре новый ключ — пара (provider, model_id). Строковый ключ оставлен
    # как совместимость для тестов и старых интеграций, а ('', model_id) — для
    # намеренно общих ручных тарифов.
    explicit = None
    if key and provider_key:
        explicit = registry.get((provider_key, key))
    if explicit is None and key:
        explicit = registry.get(("", key)) or registry.get(key)
    if explicit is not None and not (
        explicit.price_in_rub_per_1k <= 0 and explicit.price_out_rub_per_1k <= 0
    ):
        return explicit
    model_class = classify(key) if key else None
    if model_class and model_class in class_prices:
        return class_prices[model_class]
    return default_price
