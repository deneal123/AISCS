"""Белый список окружения сайдкара `agents` не отстаёт от его настроек.

⚠️ ЗАЧЕМ. У backend в compose стоит `env_file` — он получает `.env.*` целиком. У
сайдкара так нельзя: `AgentsConfig` объявлен с `extra="forbid"`, и backend-only ключи
(`AGENTS__ENGINE_MODE`, `AGENTS__ENGINE_CANARY_USER_IDS`) уронили бы ему старт. Поэтому
переменные перечислены поимённо — и этот список молча отстал от настроек.

🔴 Замер на живом контейнере: 68 полей `AgentsConfig` из 136 до сайдкара не доезжали.
`proxy_host=''` при заданном в `.env` прокси, `llm_provider='auto'` при `routerai`,
`multi_intent_enabled=False` при `true`. Отказ БЕСШУМНЫЙ по построению: pydantic не
знает, что переменную кто-то задавал, и просто берёт дефолт. Файл окружения при этом
выглядит настройкой — правку в нём видно, эффекта нет.

⚠️ Ключ добавляется в список ТОЛЬКО вместе со значением в трёх `.env`-файлах. Compose
подставляет `"${VAR:-}"`, то есть отсутствие значения даёт ПУСТУЮ СТРОКУ, а пустая
строка в поле-числе или поле-словаре роняет старт сайдкара. Пропуск ключа — тихий
дефект, пустая строка — громкий; проверка ловит оба.

Зависимостей нет — только stdlib (ast + регулярки по compose).
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "agents" / "service" / "settings"
COMPOSES = ("docker/docker-compose.yaml", "docker/docker-compose.dev.yaml")
ENV_FILES = ("docker/.env.prod", "docker/.env.dev", "docker/.env.example")

# Поле-контейнер вложенной секции, а не переменная окружения.
_NOT_A_KEY = {"settings"}

# Настройки-СТРУКТУРЫ (словарь/список), которые крутят из админ-панели, а не из `.env`.
# Через окружение они непригодны по построению: `"${VAR:-}"` даёт пустую строку, а пустая
# строка в поле-словаре роняет старт сайдкара — то есть «доставить на всякий случай» здесь
# опаснее, чем не доставлять. В сайдкар они приезжают админ-снимком в теле `/run`.
# ⚠️ Список ЗАКРЫТЫЙ и живёт здесь, а не в виде «пропускаем всё сложное»: иначе следующее
# скалярное поле, добавленное в настройки, тихо провалится мимо проверки.
_OVERLAY_ONLY = {
    "doc_embedder_fallback",
    "mcp_servers",
    "memos_embedder_fallback",
    "personas",
    "provider_enabled",
    # Сценарии, закреплённые человеком кнопкой. Структура и меняется НАЖАТИЕМ, а не
    # развёртыванием: через `.env` она непригодна по построению.
    "saved_workflows",
    "whisper_model_multipliers",
}

# Интеграции GPTHub, снятые из Alter, временно остаются как compatibility-поля в
# конфигурации agents: старый deployment не должен упасть только из-за чтения настроек.
# Они НЕ получают env, не регистрируют инструмент и не могут быть включены overlay-ом.
# Когда поля будут физически удалены из agents, этот набор уменьшится вместе с ними.
_RETIRED_FIELDS = {
    "attachment_text_max_chars",
    "context_budget_files",
    "context_budget_knowledge",
    "doc_chunk_overlap_tokens",
    "doc_chunk_tokens",
    "doc_embedder_dim",
    "doc_embedder_fallback",
    "doc_embedder_max_tokens",
    "doc_embedder_model",
    "doc_vector_collection",
    "doc_vector_top_k",
    "duckdb_enabled",
    "duckdb_max_bytes",
    "duckdb_timeout_sec",
    "duckdb_url",
    "graph_index_enabled",
    "graph_index_price_rub_per_doc",
    "graphify_enabled",
    "graphify_max_bytes",
    "graphify_model",
    "graphify_timeout_sec",
    "graphify_url",
    "max_attachments_per_message",
    "opendataloader_enabled",
    "opendataloader_max_bytes",
    "opendataloader_timeout_sec",
    "opendataloader_url",
    "qdrant_url",
    "repo_allowed_hosts",
    "repo_fetch_timeout_sec",
    "repo_max_bytes",
    "upload_max_bytes",
    "vector_search_enabled",
    "video_api_key",
    "video_enabled",
    "video_timeout_sec",
    "video_url",
    "workspace_api_key",
    "workspace_enabled",
    "workspace_timeout_sec",
    "workspace_url",
}


def _class_fields(node: ast.ClassDef) -> set[str]:
    return {
        stmt.target.id
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }


def _agents_config_fields() -> set[str]:
    """Поля класса с ``env_prefix="AGENTS__"`` — по AST, без импорта сервиса.

    ⚠️ Настройки — ПАКЕТ, а поля живут в примесях, а не в самом классе. Обходим все модули
    и добавляем поля баз: иначе после распила проверка нашла бы класс с нулём полей и молча
    прошла на пустом множестве — ровно тот отказ, ради которого её и завели.
    """
    classes: dict[str, ast.ClassDef] = {}
    target: ast.ClassDef | None = None
    for path in sorted(SETTINGS.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.ClassDef):
                continue
            classes[node.name] = node
            # ⚠️ Кавычки нормализует сам `ast.unparse` — сверяем без них.
            if "env_prefix='AGENTS__'" in ast.unparse(node):
                target = node
    if target is None:
        return set()

    fields, seen, queue = set(), set(), [target]
    while queue:
        node = queue.pop()
        if node.name in seen:
            continue
        seen.add(node.name)
        fields |= _class_fields(node)
        queue += [classes[b.id] for b in node.bases if isinstance(b, ast.Name) and b.id in classes]

    # 🔴 Примесь, выпавшая из баз, унесла бы свои поля И ИЗ КОНФИГА, И ИЗ ЭТОЙ ПРОВЕРКИ —
    # то есть гейт стал бы слабее ровно там, где случилась потеря. Требуем, чтобы КАЖДЫЙ
    # объявленный в пакете класс настроек был достижим: осиротевший модуль — красный.
    orphans = sorted(n for n in classes if n.endswith("Settings") and n not in seen)
    if orphans:
        raise SystemExit(
            f"классы настроек не подключены к AgentsConfig: {', '.join(orphans)} — "
            f"их поля не читаются и не проверяются"
        )
    return fields - _NOT_A_KEY - _OVERLAY_ONLY - _RETIRED_FIELDS


def _forwarded(compose: pathlib.Path) -> dict[str, str]:
    """Ключ окружения сайдкара → переменная, ИЗ КОТОРОЙ он берётся.

    Обычно они совпадают, но могут намеренно отличаться. В таком случае проверка следует
    за ссылкой и проверяет существование источника, а не требует вторую копию значения.
    """
    body = re.search(r"\n  agents:\n(.*?)(?=\n  [a-z])", compose.read_text(encoding="utf-8"), re.S)
    if body is None:
        return {}
    found: dict[str, str] = {}
    for key, value in re.findall(r"^      ([A-Z_0-9]+):[ \t]*(.*)$", body.group(1), re.M):
        source = re.search(r"\$\{([A-Z_0-9]+)", value)
        found[key] = source.group(1) if source else key
    return found


def _env_keys(path: pathlib.Path) -> set[str]:
    return set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.M))


def main() -> int:
    fields = _agents_config_fields()
    if not fields:
        print("НЕ НАЙДЕН класс настроек сайдкара — проверка бессмысленна", file=sys.stderr)
        return 1

    problems: list[str] = []
    for rel in COMPOSES:
        forwarded = _forwarded(ROOT / rel)
        missing = sorted(f"AGENTS__{f}".upper() for f in fields)
        missing = [k for k in missing if k not in forwarded]
        if missing:
            problems.append(f"{rel}: сайдкару не доставлено {len(missing)} настроек: {', '.join(missing)}")
        retired_forwarded = sorted(
            f"AGENTS__{field}".upper()
            for field in _RETIRED_FIELDS
            if f"AGENTS__{field}".upper() in forwarded
        )
        if retired_forwarded:
            problems.append(
                f"{rel}: retired GPTHub settings снова проброшены в agents: "
                f"{', '.join(retired_forwarded)}"
            )

    # Доставленное обязано иметь значение во всех трёх файлах, иначе приедет "".
    env_sets = {rel: _env_keys(ROOT / rel) for rel in ENV_FILES}
    forwarded_all = _forwarded(ROOT / COMPOSES[0])
    for key in sorted(k for k in forwarded_all if k.startswith("AGENTS__")):
        if key.removeprefix("AGENTS__").lower() not in fields:
            continue
        source = forwarded_all[key]
        blank = [rel for rel, keys in env_sets.items() if source not in keys]
        if blank:
            named = key if source == key else f"{key} (из {source})"
            problems.append(f"{named}: доставляется сайдкару, но не задан в {', '.join(blank)} → приедет пустая строка")

    if problems:
        print("БЕЛЫЙ СПИСОК ОКРУЖЕНИЯ САЙДКАРА РАСХОДИТСЯ С НАСТРОЙКАМИ:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"  ok  сайдкар получает все {len(fields)} настроек, каждая со значением")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
