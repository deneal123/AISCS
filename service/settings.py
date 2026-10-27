"""Настройки приложения GPTHub (backend).

Корневая композиция секций: сервис, БД, Redis, MinIO, почта, платежи, биллинг, JWT,
уведомления, celery. Зеркало настроек агентов — в ``configuration.agents`` с прежними
импортами через этот модуль. Читается pydantic-settings из окружения; ``config`` —
синглтон, собираемый НА ИМПОРТЕ: ошибка формы окружения обязана валить старт громко,
а не всплывать на первом запросе.

Жил в общем пакете с сайдкаром и был самой большой его статьёй (818 строк, 40% объёма)
при том, что сайдкар читал 2 секции из 20 и ~440 строк грузил, ни разу не прочитав.
Теперь у сайдкара свой узкий конфиг, а этот файл вернулся туда, где ему место.

⚠️ Имена переменных окружения при разделении НЕ менялись: ``env_prefix`` копировался,
а не переписывался.
"""

import dotenv
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from service.configuration.agents import Agents as Agents
from service.configuration.agents import AgentsConfig as AgentsConfig
from service.shared.ide_checkpoint_settings import IdeCheckpointConfig

ENV_FILE = dotenv.find_dotenv()
if ENV_FILE:
    # Load .env into os.environ early so modules that read os.environ at import time
    # (for example the OpenAI client) will see variables such as OPENAI_API_KEY.
    # Do not override existing environment variables.
    try:
        dotenv.load_dotenv(ENV_FILE, override=False)
    except Exception:
        # Best-effort: if loading fails, continue — BaseSettings still uses env_file
        pass

# Форма логирования живёт отдельно (`logging_config`): это не настройка сервиса.
# Ре-экспорт — чтобы `from service.settings import LOGGING` не пришлось править везде.
from service.logging_config import LOGGING, LOGGING_LEVEL  # noqa: E402,F401


class Postgresql(BaseModel):
    protocol: str = "postgresql+asyncpg"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 5.0
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True


class PgConfig(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = "password"
    db: str = "main"
    settings: Postgresql | None = Postgresql()
    model_config = SettingsConfigDict(env_prefix="PG__")

    @property
    def dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class ServiceConfig(BaseSettings):
    application_profile: str = Field(default="gpthub", pattern="^(gpthub|simulation)$")
    logging_level: str = Field(default_factory=str)
    server_port: int = Field(default_factory=int)
    name: str = Field(default_factory=str)
    app_domain: str = Field(default_factory=str)
    admin_user_ids: list[str] | str = Field(default_factory=list)
    nginx_port: int = Field(default_factory=int)
    react_app_api_base_url: str = Field(default_factory=str)
    react_app_ws_base_url: str = Field(default_factory=str)
    react_app_enable_admin_ui: bool = Field(default_factory=bool)
    model_config = SettingsConfigDict(env_prefix="SERVICE__")

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value):  # noqa: D401 - simple converter
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @property
    def admin_user_ids_set(self) -> set[str]:
        return {item.lower() for item in self.admin_user_ids}


class AuthConfig(BaseSettings):
    dev_mode: bool = Field(default_factory=bool)
    auth_mode: str = "prod"
    secret: str
    algorithm: str
    jwt_exp_hours: int
    ws_auth_allowlist_prod: list[str] = Field(default_factory=lambda: ["jwt_cookie"])
    ws_auth_allowlist_dev: list[str] = Field(
        default_factory=lambda: [
            "jwt_cookie",
            "query_token",
            "authorization_bearer",
            "session_cookie",
            "anon_token",
        ]
    )
    enable_legacy_ws_token_auth: bool = False
    enable_dev_test_token: bool = False
    enforce_prod_runtime_auth_guard: bool = True
    model_config = SettingsConfigDict(env_prefix="AUTH__")

    @field_validator("auth_mode", mode="before")
    @classmethod
    def _normalize_auth_mode(cls, value):
        normalized = str(value or "").strip().lower()
        if normalized in {"dev", "prod"}:
            return normalized
        return "prod"

    @field_validator("secret", mode="before")
    @classmethod
    def _default_secret_for_dev(cls, value, info: ValidationInfo):
        auth_mode = str(info.data.get("auth_mode") or "").strip().lower()
        if auth_mode == "dev" and not str(value or "").strip():
            return "dev-insecure-secret-change-me"
        return value

    @field_validator("secret")
    @classmethod
    def _validate_secret(cls, value: str):
        secret = value.strip()
        if len(secret) < 16:
            raise ValueError("AUTH__SECRET must be at least 16 characters long")
        return secret

    @field_validator("algorithm", mode="before")
    @classmethod
    def _default_algorithm_for_dev(cls, value, info: ValidationInfo):
        auth_mode = str(info.data.get("auth_mode") or "").strip().lower()
        if auth_mode == "dev" and not str(value or "").strip():
            return "HS256"
        return value

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, value: str):
        algorithm = value.strip().upper()
        allowed_algorithms = {"HS256", "HS384", "HS512"}
        if algorithm not in allowed_algorithms:
            raise ValueError("AUTH__ALGORITHM must be one of: HS256, HS384, HS512")
        return algorithm

    @field_validator("jwt_exp_hours", mode="before")
    @classmethod
    def _default_jwt_exp_hours_for_dev(cls, value, info: ValidationInfo):
        auth_mode = str(info.data.get("auth_mode") or "").strip().lower()
        try:
            _int_val = int(value) if value is not None and str(value).strip() != "" else 0
        except (ValueError, TypeError):
            _int_val = 0
        if auth_mode == "dev" and (value is None or str(value).strip() == "" or _int_val <= 0):
            return 24
        return value

    @field_validator("jwt_exp_hours")
    @classmethod
    def _validate_jwt_exp_hours(cls, value: int):
        if value <= 0:
            raise ValueError("AUTH__JWT_EXP_HOURS must be greater than zero")
        return value


class ProfileConfig(BaseSettings):
    base_available_launches: int = 10
    model_config = SettingsConfigDict(env_prefix="PROFILE__")


class BillingConfig(BaseSettings):
    """Параметры экономики кредитов (Фаза 2: ценообразование).

    Все значения настраиваются через env (BILLING__*) и/или БД-registry
    (profile.model_pricing имеет приоритет над дефолтами цен). Формула:
        billable_rub = Σ(cost_call × маржа) + Σ(surcharge × маржа), ×complexity
        credits      = ceil(billable_rub / credit_unit_rub), не ниже min_credits
    """

    credit_unit_rub: float = 0.003  # якорь: ₽ за 1 кредит (согласован с ценой топапа 100k=299₽)
    margin_multiplier: float = 2.5  # глобальная наценка над себестоимостью
    min_margin: float = 2.0  # нижняя планка маржи (защита от убытка)
    cost_guard_warning_events: int = 1  # fallback/budget-stop за 24ч → warning
    cost_guard_critical_events: int = 5  # fallback/budget-stop за 24ч → critical
    free_plan_credits: int = 10_000
    plan_credits: dict[str, int] = Field(
        default_factory=lambda: {"free": 10_000, "pro": 500_000, "enterprise": 5_000_000}
    )
    # Цена тарифов в ₽/мес (для checkout подписки)
    plan_prices_rub: dict[str, int] = Field(
        default_factory=lambda: {"free": 0, "pro": 990, "enterprise": 2990}
    )
    # Длительность платного подписочного периода в днях (скользящий от даты оплаты,
    # НЕ календарный месяц: покупка 25-го не должна сгорать 1-го).
    subscription_period_days: int = 30
    # Паки докупки (не сгорают): id → credits/price
    topup_packs: list[dict] = Field(
        default_factory=lambda: [
            {"id": "p100k", "credits": 100_000, "price_rub": 299},
            {"id": "p500k", "credits": 500_000, "price_rub": 990},
            {"id": "p2m", "credits": 2_000_000, "price_rub": 2990},
        ]
    )
    insufficient_credits_message: str = (
        "Кредиты закончились. Пополните баланс или смените тариф, чтобы продолжить общение."
    )
    # Анти-абьюз (Фаза 5): лимиты частоты (анти-флуд) и порог аномальных трат
    rate_limits: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {"default": {"rpm": 30, "rph": 600, "rpd": 5000}}
    )
    abuse_spend_threshold_credits: int = 200_000  # за окно ниже
    abuse_spend_window_seconds: int = 3600
    complexity_factor_complex: float = 1.15  # множитель за сложные запросы
    min_credits_per_request: int = 1  # анти-демпинг на микрозапросах
    reserve_safety: float = 1.2  # запас при предварительной оценке (Фаза 3)
    # Запрос с такой оценкой не стартует без явного подтверждения пользователя.
    # 0 отключает подтверждение (оставлено только для аварийной совместимости).
    expensive_run_confirmation_credits: int = 5_000
    # Fallback-цены (₽ за 1K токенов), если модели нет в registry. Ориентир —
    # реальные цены провайдеров (OpenRouter): gpt-4o ~0.24/0.95, gpt-4o-mini
    # ~0.014/0.057, llama-70b ~0.01/0.03 ₽/1K. Дефолт держим ближе к среднему.
    default_price_in_rub_per_1k: float = 0.05
    default_price_out_rub_per_1k: float = 0.15
    # Цены по классу модели (image/fast/large) — второй уровень fallback: [in, out].
    # 🔴 `image` — по ЗАМЕРУ каталога: выходной токен картинки стоит 3.04 ₽/1k
    # (gemini-2.5-flash-image) и 12.17 ₽/1k (gemini-3-pro-image), в 20-80 раз дороже
    # текстового. Берём ВЕРХНЮЮ границу с округлением вверх: фолбэк применяется, когда
    # модель нам незнакома, и ошибаться там безопаснее в сторону перебора.
    class_prices_rub_per_1k: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "fast": [0.02, 0.06],
            "large": [0.3, 1.0],
            "image": [0.05, 12.5],
        }
    )
    # Фикс-надбавки за внешние операции (₽), до маржи
    tool_surcharge_rub: dict[str, float] = Field(
        default_factory=lambda: {
            "web_search": 1.0,
            "deep_research": 3.0,
            # 🔴 5.0 → 1.0. Прежнее было НЕ надбавкой, а заплаткой поверх недобора в 51
            # раз (картинка тарифилась как `fast`), и от модели оно не зависело — смена
            # картиночной модели на дорогую давала прямой убыток. Теперь токены картинки
            # идут по НАСТОЯЩЕЙ цене, а надбавка покрывает невидимое в токенах: неудачные
            # попытки (платим мы) и хранение артефакта.
            "image_gen": 1.0,
            "pptx_gen": 2.0,
            "pdf_gen": 3.0,
            "audio_transcribe": 1.5,
            "web_search_tool": 0.5,  # поиск по ходу ответа: субагента с синтезом нет → половина
            # Вызов инструмента внешнего MCP-сервера. Одна цена на все серверы: набор
            # имён сверяется с сайдкаром офлайн-гейтом, и цена на сервер превращала бы
            # подключение каждого нового в согласованный релиз двух репозиториев.
            "mcp_tool": 0.3,
            # ⚠️ ОДНА цена на все шесть инструментов песочницы: цена на инструмент
            # делала бы каждый новый согласованным релизом двух репозиториев.
            "workspace_tool": 0.2,
            # Просмотр ролика. ⚠️ ПОМЕЧЕННЫЙ ДЕФОЛТ, а не выверенная цена: владелец назовёт
            # её отдельно, до тех пор правится `BILLING__` без релиза. Покрывает невидимое
            # в токенах (скачивание, ffmpeg, хранение кадров) — сами кадры и расшифровка
            # тарифицируются токенами, и вторая цена за них была бы двойным счётом.
            "watch_video": 2.0,
        }
    )
    model_config = SettingsConfigDict(env_prefix="BILLING__")


class PaymentsConfig(BaseSettings):
    """Параметры платёжного провайдера (провайдер-агностик)."""

    provider: str = "mock"  # mock | yookassa | ...
    webhook_secret: str = ""
    success_url: str = "https://app.local/billing/success"
    cancel_url: str = "https://app.local/billing/cancel"
    # YooKassa: идентификатор магазина и секретный ключ (Basic-auth к API)
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""

    # --- фискализация (54-ФЗ) --------------------------------------------- #
    # Передавать данные чека в платёж («Платёж и чек одновременно»): ЮKassa регистрирует
    # фискальный чек и отправляет его покупателю на customer.email. По умолчанию ВЫКЛ —
    # включать, только когда в кабинете ЮKassa подключены «Чеки от ЮKassa» и заданы
    # корректные для вашего юрлица налоговые реквизиты ниже (иначе чек будет невалиден).
    receipt_enabled: bool = False
    # Ставка НДС товара/услуги (тег 1199). 1=без НДС, 2=0%, 3=10%, 4=20%, 5=10/110, 6=20/120.
    # Значение ЗАВИСИТ от вашей системы налогообложения — уточните у бухгалтера.
    receipt_vat_code: int = 1
    # Признак предмета расчёта (тег 1212). Для доступа к сервису/кредитам — "service".
    receipt_payment_subject: str = "service"
    # Признак способа расчёта (тег 1214). Полная оплата в момент платежа — "full_payment".
    receipt_payment_mode: str = "full_payment"
    # Система налогообложения (тег 1055). Нужна только для СТОРОННИХ онлайн-касс при
    # нескольких СНО; для «Чеков от ЮKassa» игнорируется — оставляйте 0 (не передаём).
    receipt_tax_system_code: int = 0
    model_config = SettingsConfigDict(env_prefix="PAYMENTS__")


class EmailConfig(BaseSettings):
    """SMTP для писем с кодами подтверждения (провайдер — Selectel).

    Секреты — `login`/`password` (только env, НЕ в admin-реестр). Порт 1127 =
    implicit TLS (`use_tls=True`); 1126 = STARTTLS (`use_tls=False`).
    """

    enabled: bool = False
    host: str = Field(default_factory=str)  # smtp.mail.selcloud.ru
    port: int = 1127
    use_tls: bool = True  # True → implicit TLS (1127); False → STARTTLS (1126)
    start_tls: bool = True  # Explicitly disabled only for a local plaintext SMTP sink.
    login: str = Field(default_factory=str)  # секрет (SMTP-логин)
    password: str = Field(default_factory=str)  # секрет (API-key)
    from_address: str = "no-reply@incellcorp.ru"
    from_name: str = "GPTHub"
    timeout_sec: float = 20.0
    # Не-секретные ручки OTP (редактируются в админке через runtime-overlay).
    # Кулдаун повтора и кап проверок задаются лимитами в auth-роутере (rate_limiter).
    code_length: int = 6
    code_ttl_seconds: int = 600
    model_config = SettingsConfigDict(env_prefix="MAIL__")


class Job(BaseModel):
    wait_time_sec: int = 10
    processing_interval_sec: int = 5
    processing_batch_size: int = 5
    processing_timeout_sec: int = 300


class JobConfig(BaseSettings):
    settings: Job = Job()
    model_config = SettingsConfigDict(env_prefix="JOB__")


class CorsConfig(BaseSettings):
    allow_origins: list[str] = Field(default_factory=list)
    model_config = SettingsConfigDict(env_prefix="CORS_")


class MinioConfig(BaseSettings):
    endpoint: str = Field(default_factory=str)
    access_key: str = Field(default_factory=str)
    secret_key: str = Field(default_factory=str)
    bucket: str = Field(default_factory=str)
    region: str = Field(default_factory=str)
    secure: bool = Field(default_factory=bool)
    public_endpoint: str = Field(default_factory=str)
    retry_attempts: int = Field(default_factory=int)
    retry_backoff: float = Field(default_factory=float)
    presign_expiry: int = Field(default_factory=int)
    model_config = SettingsConfigDict(env_prefix="MINIO__")


class Redis(BaseModel):
    use_ssl: bool = False
    decode_responses: bool = True
    health_check_interval: int = 30


class RedisConfig(BaseSettings):
    enabled: bool = Field(default_factory=bool)
    host: str = Field(default_factory=str)
    port: int = Field(default_factory=int)
    db: int = Field(default_factory=int)
    password: str = Field(default_factory=str)
    session_prefix: str = Field(default_factory=str)
    session_ttl_seconds: int = Field(default_factory=int)
    cache_prefix: str = Field(default_factory=str)
    cache_default_ttl_seconds: int = Field(default_factory=int)
    profile_cache_ttl_seconds: int = Field(default_factory=int)
    settings: Redis = Redis()

    @property
    def dsn(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        scheme = "rediss" if self.settings.use_ssl else "redis"
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"


class Sessions(BaseModel):
    encryption_key: str | None = None
    backend: str = "redis"
    sqlite_db_path: str | None = None


class SessionsConfig(BaseSettings):
    settings: Sessions = Sessions()
    backend: str | None = None  # "redis" | "sqlite" | "pseudo" | "auto"
    sqlite_db_path: str | None = None
    encryption_key: str | None = None
    model_config = SettingsConfigDict(env_prefix="SESSIONS__")


class StorageConfig(BaseSettings):
    root: str = Field(default_factory=str)
    backend: str = Field(default_factory=str)  # "local" or "minio"
    model_config = SettingsConfigDict(env_prefix="STORAGE__")


class File(BaseModel):
    allowed_extensions: list[str] = Field(default_factory=lambda: [".png", ".jpg", ".jpeg"])
    max_file_size_byte: int = 2_000_000  # 2 MB


class FileConfig(BaseSettings):
    settings: File = File()
    model_config = SettingsConfigDict(env_prefix="FILE__")


class Celery(BaseModel):
    chat_retention_days: int = 365


class CeleryConfig(BaseSettings):
    broker_url: str = Field(default_factory=str)
    result_backend: str = Field(default_factory=str)
    queues: str = Field(default_factory=str)
    settings: Celery = Celery()
    model_config = SettingsConfigDict(env_prefix="CELERY__")


class ChatWs(BaseModel):
    max_replay: int = 200
    max_claim: int = 100
    pel_min_idle_ms: int = 60_000
    heartbeat_interval: int = 5


class HumanQuestionConfig(BaseSettings):
    # Enable only after migration + resume dispatcher + shared UI are integrated.
    enabled: bool = False
    model_config = SettingsConfigDict(env_prefix="HUMAN_QUESTIONS__")


class ChatWsConfig(BaseSettings):
    settings: ChatWs = ChatWs()
    model_config = SettingsConfigDict(env_prefix="CHAT_WS__")


class AdminConfig(BaseSettings):
    """Параметры админ-панели: TTL кэшей runtime-настроек и админ-роли."""

    settings_overlay_ttl_sec: int = 30  # окно меж-процессной свежести DB-overlay
    admin_role_cache_ttl_sec: int = 30  # кэш DB-флага is_admin (per user)
    model_config = SettingsConfigDict(env_prefix="ADMIN__")


class NotificationsConfig(BaseSettings):
    """Жизненные уведомления по email.

    Сервисные письма (подписка истекает, кредиты на исходе, платёж не прошёл) — это
    состояние аккаунта, а не реклама. Реактивация («давно не заходили») — реклама, и она
    уходит ТОЛЬКО при `marketing_consent_at`: согласие на обработку ПД рекламу не
    покрывает (ФЗ «О рекламе», ст. 18).
    """

    enabled: bool = True
    app_url: str = "https://gpthub.ru"
    subscription_notice_days: int = 3  # за сколько дней предупреждать о конце периода
    low_credits_threshold: float = 0.1  # доля остатка, ниже которой «кредиты на исходе»
    idle_days: int = 30  # сколько дней без сообщений считаем простоем
    # Частотный лимит: даже когда сработало несколько триггеров сразу, человек не должен
    # получить пачку писем.
    max_per_window: int = 1
    frequency_window_days: int = 7
    model_config = SettingsConfigDict(env_prefix="NOTIFICATIONS__")


class Config(BaseSettings):
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    # ⚠️ auth НЕОБЯЗАТЕЛЕН — это про независимость сервисов. У `AuthConfig.secret` нет
    # дефолта (пустой JWT-секрет хуже отсутствующего), и из-за этого сайдкар, которому
    # auth не нужен вовсе, вынужден был врать плейсхолдером. Нет AUTH__* → секция None;
    # кому auth нужен, тому наличие проверяет `require_auth()` на старте.
    auth: AuthConfig | None = None
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    payments: PaymentsConfig = Field(default_factory=PaymentsConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    pg: PgConfig = Field(default_factory=PgConfig)
    job: JobConfig = Field(default_factory=JobConfig)
    cors: CorsConfig = Field(default_factory=CorsConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    file: FileConfig = Field(default_factory=FileConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    chat_retention_days: int = 365
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    ide_checkpoints: IdeCheckpointConfig = Field(default_factory=IdeCheckpointConfig)
    human_questions: HumanQuestionConfig = Field(default_factory=HumanQuestionConfig)
    chat_ws: ChatWsConfig = Field(default_factory=ChatWsConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
    )


def _get_config() -> Config:
    config = Config()
    return config


def require_auth(config: Config) -> AuthConfig:
    """Вернуть auth-секцию или упасть ГРОМКО, если её нет.

    Зовёт тот, кому auth действительно нужен (backend — на старте). Смысл в том, чтобы
    сервис без JWT-секрета не поднялся вовсе, а не выяснял это на первом входе
    пользователя. Сайдкару агентов auth не нужен, и он эту функцию не зовёт.
    """
    if config.auth is None:
        raise RuntimeError(
            "AUTH__SECRET/AUTH__ALGORITHM/AUTH__JWT_EXP_HOURS не заданы — сервису, "
            "которому нужна авторизация, без них подниматься нельзя"
        )
    return config.auth


def redact_config_for_logging(config: Config) -> dict:
    return {
        "service": {
            "name": config.service.name,
            "server_port": config.service.server_port,
        },
        # Секция auth необязательна (см. `Config.auth`): нет `AUTH__*` — нет секции.
        # Безусловное разыменование роняло бы сервис на СТАРТЕ, потому что редактор
        # зовётся на уровне модуля в `main.py`.
        "auth": {
            "auth_mode": config.auth.auth_mode if config.auth else None,
        },
        "storage": {
            "backend": config.storage.backend,
        },
    }


config = _get_config()
