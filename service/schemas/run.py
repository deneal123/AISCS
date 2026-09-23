"""DTO входного запроса ``POST /run``.

Отражает вход ``AgentExecutionPort.execute`` без несериализуемого: `pseudo_session`
строится из `history_messages`, `on_event` — забота транспорта стрима. Соответствие
сигнатуре порта проверяет тест — DTO не должен «уплыть» от него.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

# Поля, которые едут в теле, но разворачиваются в ОКРУЖЕНИЕ прогона (ContextVar), а не в
# аргументы движка. Списком — чтобы страж «поля DTO ⊆ сигнатура execute» ловил настоящий
# дрейф контракта, а не спотыкался об окружение.
AMBIENT_FIELDS = frozenset({"provider_policy", "agent_settings", "mcp_server_ids"})


class AgentRunInput(BaseModel):
    """Тело ``POST /run`` — полный сериализуемый вход прогона движка агента."""

    text: str
    thread_id: str
    user_id: str | None = None
    session_data: dict | None = None
    selected_model: str | None = None
    route_override: str | None = None
    # Категория, уже выбранная роутером в `/route`; пусто → решаем сами.
    # ⚠️ НЕ ПУТАТЬ С `route_override`: тот форсирует инструмент и отключает гейты
    # мульти-интента и планирования, а это поле лишь сообщает готовый ответ роутера.
    resolved_category: str | None = None
    input_type: str | None = None
    web_search: bool = False
    deep_research: bool = False
    file_context: str = ""
    attachments: list | None = None
    memory_enabled: bool = True
    ldr_model: str | None = None
    ldr_strategy: str | None = None
    multi_intent: bool | None = None
    # Собрано backend'ом: сайдкар не ходит в MemOS/PG/Redis.
    memory_parts: tuple[str, str] | None = None
    history_messages: list[dict] | None = None
    compact_summary: str | None = None
    # Презайнед-ССЫЛКИ, не байты: файл весит десятки мегабайт, а `analyze_data`
    # вызывается редко — качаем лениво. Формат: ``[{"name": …, "url": …}]``.
    tabular_files: list[dict] | None = None
    # Последняя картинка треда для image-to-image («сделай фон темнее») — тоже ссылкой.
    reference_image_url: str | None = None
    # graph_id репозиториев треда: `search_knowledge_graph` ищет код в них, а не только
    # в личном графе пользователя.
    repo_graph_ids: list[str] | None = None
    # Рядом с табличным приложен документ/репозиторий → `file_context` НЕЛЬЗЯ выбрасывать
    # при наличии таблиц, иначе карта репо пропадёт из промпта.
    has_non_tabular_attachment: bool = False
    # Только ВЫБОР личностей; сами определения приезжают админ-снимком в `agent_settings`
    # (выбор персональный и меняется каждым сообщением, реестр общий). Потолок — 3.
    persona_ids: list[str] | None = None
    # Роль сменилась с прошлого ответа; считает сторона вызова — история с метаданными
    # есть только у неё. Без явного разрыва смена личности посреди диалога почти не
    # действует: строка инструкции не спорит с демонстрацией из предыдущих ходов.
    persona_switched: bool = False
    # `None` — план по оценке сложности, `True` — всегда (и без вызова-оценки), `False` —
    # никогда. Стратегия поверх «Авто», а не пункт списка режимов.
    planning: bool | None = None
    # Ссылка на файловую песочницу прогона: {workspace_id, token, user_id, root}.
    # 🔴 С ТОКЕНОМ ВЛАДЕНИЯ: без подписи угаданный `workspace_id` был бы доступом к чужой
    # файловой системе. Выдаёт сайдкар песочниц при создании, backend лишь несёт дальше.
    # Пусто — инструменты `ws_*` не выдаются модели вовсе (умолчание на стороне отказа).
    workspace_ref: dict | None = None
    # 🔴 СОГЛАСИЕ ЧЕЛОВЕКА НА ДОРОГОЙ ПРОСМОТР РОЛИКА. Признак жил в схеме контекста и
    # проверялся гейтом инструмента, но в теле `/run` его НЕ БЫЛО — и до контекста он не
    # доходил никогда. Замер: нажатие кнопки давало «Режим „просмотр видео“ не
    # запускался», а сайдкар video видел только health-пробы. Способность, включённая в
    # проде и оплаченная в прайсе, была мертва на HTTP-движке целиком.
    video_tool_enabled: bool = False
    # Окружение прогона (см. AMBIENT_FIELDS): кто выключен админом или заблокирован
    # health-проверкой. Формат: ``{"disabled": [...], "blocked": [...]}``.
    provider_policy: dict | None = None
    # Окружение прогона: слепок переопределённых админом настроек. Чего нет в слепке —
    # берётся из конфига стороны исполнения.
    agent_settings: dict | None = None
    # 🔴 ИДЕНТИФИКАТОРЫ разрешённых MCP-серверов, а НЕ адреса. Адрес из тела запроса —
    # прямой SSRF во внутреннюю сеть, где Postgres, Redis, MinIO, Qdrant и все сайдкары
    # доступны без аутентификации по топологии. Сопоставление «идентификатор → адрес и
    # секрет» живёт в админ-настройках (`mcp_servers`) и наружу не отдаётся.
    # ⚠️ Окружение прогона (см. AMBIENT_FIELDS), а не аргумент движка: набор нужен один раз,
    # на входе, а тянуть его в сигнатуру `execute` значило бы протащить через всю цепочку
    # use-case'ов ради списка строк, который читает подключение MCP.
    # Пусто/отсутствует — MCP не задействован вовсе (умолчание на стороне безопасности).
    mcp_server_ids: list[str] | None = None

    # Forward-compat: backend новее сайдкара — лишнее поле игнорируем, а не роняем прогон.
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _accept_category_from_session(self):
        """Подхватить готовую категорию из ``session_data['_resolved_category']``.

        ⚠️ Боковым каналом, а не полем по всей цепочке: между `/route` и `/run` у
        backend'а десяток слоёв, и пропуск в любом из них выглядел бы как «оптимизация не
        сработала», без ошибки. Тем же каналом уже едет `routing_usage`. Разбор здесь, в
        одном месте; явно переданное значение приоритетнее.
        """
        if self.resolved_category is None and isinstance(self.session_data, dict):
            value = self.session_data.get("_resolved_category")
            if isinstance(value, str) and value.strip():
                self.resolved_category = value.strip()
        return self

    def to_execute_kwargs(self) -> dict[str, Any]:
        """Развернуть в kwargs ``AgentExecutionPort.execute`` (без AMBIENT_FIELDS)."""
        return {k: v for k, v in self.model_dump().items() if k not in AMBIENT_FIELDS}
