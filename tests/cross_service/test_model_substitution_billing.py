"""Подмена модели при фейловере не должна разорять пользователя.

Живой инцидент: человек выбрал claude-haiku (класс `fast`), у OpenRouter кончился лимит
ключа, фейловер ушёл на RouterAI, а там `_pick_chat_capable_model` брал ПЕРВУЮ по алфавиту
модель — `ai21/jamba-large-1.7` (класс `large`, в 15× дороже). Те же 17k токенов стоили
4505 кредитов вместо 396.

Оборона строилась в три линии, по одной на источник ошибки. Здесь живёт только ПЕРВАЯ —
единственная, что принадлежит движку:

1. фейловер не подставляет модель ДОРОЖЕ выбранной (`_pick_chat_capable_model`) — ЗДЕСЬ;
2. потолок счёта ценой выбранной модели (`_charge_usage`) — остался в backend'е;
3. пользователь ВИДИТ подмену (`_build_public_usage_meta`) — остался в backend'е.

Линии 2 и 3 не переехали намеренно: считает и показывает их backend, движок в этом не
участвует вовсе. Фейк `_charge_usage` проверял бы арифметику фейка, а не потолок цены.
Значит, регресс «счёт не капнулся» ловится теперь ТОЛЬКО тестами backend'а — здесь
ловится лишь то, что фейловер вообще не полезет за дорогой моделью.
"""

from service.domain.client.registry import _pick_chat_capable_model
from service.shared.model_class import classify_model, cost_rank, is_not_pricier_than

###############################################################################
# Классификатор и порядок дороговизны                                         #
###############################################################################


def test_the_real_incident_models_classify_as_expected() -> None:
    assert classify_model("~anthropic/claude-haiku-latest") == "fast"
    assert classify_model("ai21/jamba-large-1.7") == "large"
    assert cost_rank("~anthropic/claude-haiku-latest") < cost_rank("ai21/jamba-large-1.7")


def test_is_not_pricier_than() -> None:
    assert is_not_pricier_than("ai21/jamba-large-1.7", "claude-haiku") is False
    assert is_not_pricier_than("claude-haiku", "ai21/jamba-large-1.7") is True
    assert is_not_pricier_than("some-fast-mini", "another-mini") is True
    # Без выбранной модели ограничивать нечего.
    assert is_not_pricier_than("ai21/jamba-large-1.7", None) is True


###############################################################################
# Фейловер не подставляет модель дороже выбранной                             #
###############################################################################


def test_failover_skips_provider_with_only_pricier_models() -> None:
    """У провайдера только large-модели, а выбрана fast → лучше None (идём к соседу)."""
    only_large = ["ai21/jamba-large-1.7", "x-ai/grok-2", "openai/gpt-4o"]
    assert _pick_chat_capable_model(only_large, prefer="claude-haiku") is None


def test_failover_picks_affordable_substitute() -> None:
    """Есть модель не дороже выбранной — берём её, а не первую по алфавиту."""
    mixed = ["ai21/jamba-large-1.7", "google/gemma-2-9b", "qwen/qwen-mini"]
    got = _pick_chat_capable_model(mixed, prefer="claude-haiku")
    assert got is not None
    assert classify_model(got) == "fast"


def test_failover_without_preference_keeps_first() -> None:
    """Нет выбранной модели (внутренний вызов) — старое поведение: первая подходящая."""
    models = ["ai21/jamba-large-1.7", "google/gemma-2-9b"]
    assert _pick_chat_capable_model(models, prefer=None) == "ai21/jamba-large-1.7"
