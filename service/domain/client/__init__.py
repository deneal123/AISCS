"""Фасад мультипровайдерного слоя: единый API поверх MWS / OpenAI / OpenRouter /
RouterAI / GigaChat.

⚠️ ЭТОТ ФАЙЛ — ТОЛЬКО РЕЭКСПОРТЫ. Раньше здесь лежало 680 строк ЛОГИКИ: кэш каталога,
выбор провайдера, привязка SDK, оба вызова с фейловером и весь стрим. Логика в
`__init__` пакета исполняется при КАЖДОМ импорте, а импортируют этот пакет 46 мест —
то есть «зайти за одной функцией» означало протащить через интерпретатор всё сразу.

Где что теперь живёт:

    active.py     активный провайдер: выбор, привязка Agents SDK, пересборка после
                  смены ключа в админке. ЕДИНСТВЕННЫЙ дом изменяемого состояния
    catalog.py    агрегированный каталог моделей: кэш с TTL, индекс model → владелец
    chat.py       не-стримовые вызовы с ПОЛНЫМ фейловером
    streaming.py  стрим: фейловер только ДО первой дельты
    registry.py   реестр провайдер-модулей, порядок обхода, подбор модели
    retry.py      классификация ошибок, бэкофф, параметры ретраев

⚠️ Провайдер-специфичные модули (`mws_client`, `openai_client`, …) по-прежнему доступны
как `service.domain.client.<имя>` — их импортируют напрямую реестр и здоровье.

⚠️ ЗДЕСЬ НЕТ реэкспорта изменяемых имён (`ACTIVE_PROVIDER`, `OPENAI_CLIENT`) как
значений: их меняет `active.rebuild_provider()`, и связанная на импорте копия молча
осталась бы старой. Снаружи они доступны только функциями — `get_active_provider()`,
`get_openai_client()`, — и все 46 потребителей уже пользуются именно ими (проверено).

⚠️ ПОДМОДУЛИ `circuit_breaker`/`provider_policy` РЕЭКСПОРТИРУЮТСЯ ЗДЕСЬ ОБЯЗАТЕЛЬНО.
Сами они лежат в `resilience/`, и внешние потребители (`media`, `vector_store`) берут их
как `from ...client import circuit_breaker`. Пока модули лежали в корне, это работало
само собой — машинерия импорта вытягивает подмодуль пакета без объявления. После
переезда в подпакет такой импорт ломается, и фасад обязан их подставить: снаружи не
должно быть видно, как пакет разложен внутри.

Состав фасада проверяется тестом `tests/test_client_facade_contract.py`: он обходит весь
`service/` и сверяет каждое запрошенное имя с тем, что пакет реально отдаёт.
"""

from .active import (
    clear_models_cache,
    get_active_provider,
    get_openai_client,
    rebuild_provider,
    rebuild_provider_generation,
)
from .calls.catalog import get_model_catalog
from .calls.chat import (
    create_chat_completion,
    create_completion,
    create_embedding,
    list_available_models,
)
from .calls.legacy_stream import stream_chat_completion
from .calls.streaming import stream_provider_completion
from .model_catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from .model_requirements import (
    ModelQualification,
    ModelRequirement,
    ProviderQualificationStatus,
)
from .registry import (
    build_provider_order,
    build_qualified_model_catalog,
    get_provider_model_catalog,
    get_provider_module,
    initialize_run_provider_admission,
    is_chat_capable,
    list_qualified_models,
    qualify_model,
)
from .resilience import circuit_breaker, provider_policy

__all__ = [
    "build_qualified_model_catalog",
    "build_provider_order",
    "CapabilityEvidenceSource",
    "circuit_breaker",
    "clear_models_cache",
    "create_chat_completion",
    "create_completion",
    "create_embedding",
    "get_active_provider",
    "get_model_catalog",
    "get_openai_client",
    "get_provider_model_catalog",
    "get_provider_module",
    "initialize_run_provider_admission",
    "is_chat_capable",
    "list_available_models",
    "list_qualified_models",
    "ModelCatalogSource",
    "ModelCatalogStatus",
    "ModelQualification",
    "ModelRequirement",
    "ProviderModelCatalog",
    "ProviderModelRecord",
    "ProviderQualificationStatus",
    "provider_policy",
    "qualify_model",
    "rebuild_provider",
    "rebuild_provider_generation",
    "stream_chat_completion",
    "stream_provider_completion",
]
