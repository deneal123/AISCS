"""Выдача файловой песочницы треду: создать один раз, переиспользовать, отпустить по сроку.

🔴 ПОЧЕМУ НЕ НА КАЖДОЕ СООБЩЕНИЕ. Песочница — это КОНТЕЙНЕР на хосте, а не запись в БД. У
сайдкара общий потолок (`WORKSPACE_MAX_WORKSPACES`), и создание на сообщение исчерпало бы
его за минуты, причём молча: пользователь увидел бы «работа с файлами недоступна» без
единой ошибки в логах. Поэтому песочница привязывается к ТРЕДУ и живёт до своего срока.

🔴 СРОК В REDIS ОБЯЗАН БЫТЬ КОРОЧЕ СРОКА У САЙДКАРА. Иначе наступает окно, в котором
привязка ещё жива, а контейнер уже подметён уборщиком: мы выдадим ссылку на то, чего нет, и
инструменты будут отказывать без внятной причины. Запас берём явным множителем и стережём
тестом — это ровно тот случай, когда два независимых числа разъезжаются молча.

⚠️ Всё best-effort: Redis лёг, сайдкар не ответил — песочницы просто нет, и шесть
инструментов отсеиваются гейтом с причиной. Ронять из-за этого чат нельзя.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging

import httpx

logger = logging.getLogger(__name__)

# Доля срока сайдкара, на которую мы держим привязку. 0.8 — запас на уборку и на то, что
# сайдкар мог создать песочницу чуть раньше, чем мы записали ключ.
BINDING_TTL_RATIO = 0.8


def _status_family(status_code: int) -> str:
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"


def _log_boundary_failure(code: str, *, level: int = logging.WARNING, status: int = 0) -> None:
    """Log bounded operational metadata without exception, payload, path, or identity data."""
    extra = {"component": "workspace", "failure_code": code}
    if status:
        extra["status_family"] = _status_family(status)
    logger.log(level, "workspace integration failure", extra=extra)


class WorkspaceGone(Exception):
    """Песочница БЫЛА, но её больше нет: истёк срок либо сайдкар потерял реестр.

    🔴 ЭТО НЕ «НЕ СМОГЛИ». Всё остальное на этом пути best-effort и отвечает `None`, а
    `None` от чтения дерева неотличим от ПУСТОГО каталога: панель писала «Каталог пуст»
    там, где правда была «песочницы больше нет». Человек видел не ошибку, а ложь о своих
    файлах — и не понимал, куда они делись.

    ⚠️ Запас `BINDING_TTL_RATIO` закрывает только истечение срока. Реестр сайдкара живёт В
    ПАМЯТИ: после его перезапуска привязки указывают в пустоту сразу и все, а срок ключа
    ещё не вышел — тред остаётся без файлов на десятки минут. Поэтому доказанно мёртвую
    привязку надо не только назвать, но и СТЕРЕТЬ (`forget_binding`).
    """


class WorkspaceConflict(Exception):
    """The workspace changed after the client loaded its revision."""


class WorkspaceUnavailable(Exception):
    """The sidecar could not confirm workspace state; its binding remains valid."""


class WorkspaceRequestRejected(Exception):
    """A caller-selected bounded sidecar error safe to preserve across the boundary."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _key(thread_id: str) -> str:
    return f"chat:{thread_id}:workspace"


def _config():
    from service.settings import config

    agents = config.agents
    return (
        # Создаём, только если разрешена способность И включено автосоздание: второе
        # выключено по умолчанию, потому что каждая песочница — контейнер на хосте.
        bool(getattr(agents, "workspace_enabled", False))
        and bool(getattr(agents, "workspace_autocreate", False)),
        str(getattr(agents, "workspace_url", "") or "").rstrip("/"),
        float(getattr(agents, "workspace_timeout_sec", 120.0) or 120.0),
        str(getattr(agents, "workspace_api_key", "") or ""),
        float(getattr(agents, "workspace_ttl_sec", 1800.0) or 1800.0),
    )


def _explicit_creation_config():
    """Return sidecar settings for a deliberate Work Hub allocation.

    ``workspace_autocreate`` protects ordinary chat/tool execution from
    allocating a container just because a run happens to mention a file.  It
    must not silently override an authenticated person's ``/work/activate``
    action.
    """
    from service.settings import config

    agents = config.agents
    return (
        bool(getattr(agents, "workspace_enabled", False)),
        str(getattr(agents, "workspace_url", "") or "").rstrip("/"),
        float(getattr(agents, "workspace_timeout_sec", 120.0) or 120.0),
        str(getattr(agents, "workspace_api_key", "") or ""),
        float(getattr(agents, "workspace_ttl_sec", 1800.0) or 1800.0),
    )


def _is_async_client(redis_client) -> bool:
    """Асинхронный ли клиент Redis. Судим по `execute_command` НА ТИПЕ.

    🔴 НЕ ПО КОНКРЕТНОЙ КОМАНДЕ: `inspect.iscoroutinefunction(client.get)` на
    `redis.asyncio` отвечает ЛОЖЬ — команды там обычные методы, возвращающие корутину.
    Живой прогон поймал именно это: проверка по команде уводила асинхронный клиент в
    `to_thread`, тот возвращал НЕ ДОЖДАННУЮ корутину, и привязка песочницы молча не
    читалась и не сохранялась — панель рабочего места каждый раз видела «песочницы нет».

    🔴 НЕ ПО РЕЗУЛЬТАТУ ВЫЗОВА: чтобы его получить, синхронную команду пришлось бы
    выполнить ПРЯМО В event loop — то есть заблокировать процесс на время сетевого обмена
    ровно в том случае, ради которого тред и заводится.
    """
    return inspect.iscoroutinefunction(getattr(type(redis_client), "execute_command", None))


async def _redis_call(redis_client, method_name: str, *args):
    """Позвать команду Redis, не зная, синхронный клиент или асинхронный."""
    method = getattr(redis_client, method_name)
    if _is_async_client(redis_client):
        return await method(*args)
    return await asyncio.to_thread(method, *args)


async def read_binding(redis_client, thread_id: str | None) -> dict | None:
    """Привязка песочницы треда БЕЗ создания новой — для ЧТЕНИЯ (панель рабочего места).

    🔴 Панель не вправе создавать контейнер. Пока она звала `ensure_workspace`, каждое
    открытие поднимало НОВУЮ песочницу: контейнер на просмотр при общем потолке в 32
    штуки, а в панели — пустое дерево вместо настоящего каталога треда. Найдено живым
    прогоном: в логе сайдкара `POST /workspaces` перед каждым `files/tree`, причём дерево
    и история приезжали из РАЗНЫХ песочниц.
    """
    return await _read_binding(redis_client, str(thread_id or ""))


async def read_binding_state(redis_client, thread_id: str | None) -> tuple[str, dict | None]:
    """Read a binding without turning a Redis outage into a false ``absent`` state.

    Ordinary agent execution intentionally keeps the older fail-open
    ``read_binding`` contract.  The Work Hub is a status surface, however, so
    it must distinguish "there is no sandbox" from "coordination state cannot
    be read" while still returning the persistent Library facet.
    """
    normalized_thread_id = str(thread_id or "")
    if not normalized_thread_id:
        return "absent", None
    if redis_client is None:
        return "unavailable", None
    try:
        raw = await _redis_call(redis_client, "get", _key(normalized_thread_id))
    except Exception:
        _log_boundary_failure("coordination_unavailable", level=logging.DEBUG)
        return "unavailable", None
    if not raw:
        return "absent", None
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except ValueError:
        return "unavailable", None
    if not isinstance(data, dict) or not data.get("workspace_id"):
        return "unavailable", None
    return "ready", data


async def _read_binding(redis_client, thread_id: str) -> dict | None:
    if redis_client is None or not thread_id:
        return None
    try:
        raw = await _redis_call(redis_client, "get", _key(thread_id))
    except Exception:
        _log_boundary_failure("coordination_unavailable", level=logging.DEBUG)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("workspace_id") else None


async def forget_binding(redis_client, thread_id: str | None) -> None:
    """Забыть привязку к песочнице, которой доказанно нет.

    ⚠️ УДАЛЯТЬ КОНТЕЙНЕР НЕЧЕГО — его уже нет, потому мы сюда и попали; `release_workspace`
    здесь был бы лишним обращением к сайдкару за несуществующим. Оставленный же ключ
    означает, что тред указывает в пустоту до конца своего срока: у сайдкара реестр в
    памяти, так что после его перезапуска это десятки минут без файлов на КАЖДЫЙ тред.
    """
    if redis_client is None or not thread_id:
        return
    try:
        await _redis_call(redis_client, "delete", _key(str(thread_id)))
    except Exception:  # noqa: BLE001 — Redis лёг: следующий ход разберётся сам
        _log_boundary_failure("binding_cleanup", level=logging.DEBUG)


async def _save_binding(redis_client, thread_id: str, ref: dict, ttl_sec: float) -> None:
    if redis_client is None or not thread_id:
        return
    payload = json.dumps(ref, ensure_ascii=False)
    ttl = int(max(1.0, ttl_sec))
    # 🔴 КЛИЕНТ REDIS БЫВАЕТ И СИНХРОННЫМ, И АСИНХРОННЫМ: воркер держит `redis.Redis`,
    # веб-процесс — асинхронный. `to_thread(async_fn)` вернул бы корутину, которую никто
    # не ожидает, и запись НЕ ПРОИСХОДИЛА БЫ молча.
    try:
        await _redis_call(redis_client, "setex", _key(thread_id), ttl, payload)
    except Exception:
        _log_boundary_failure("binding_store")


async def _create(base: str, key: str, timeout: float, user_id: str, ttl_sec: float) -> dict | None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/workspaces",
                json={"user_id": str(user_id), "ttl_sec": ttl_sec},
                headers=headers,
            )
    except Exception:  # noqa: BLE001 — сайдкар не обязан быть поднят
        _log_boundary_failure("create_transport")
        return None
    if response.status_code >= 400:
        # The sidecar may include file-system details in its error body.  HTTP
        # status is sufficient for this best-effort allocation path.
        _log_boundary_failure("create_remote", status=response.status_code)
        return None
    try:
        data = response.json() or {}
    except Exception:  # noqa: BLE001
        return None
    if not data.get("workspace_id") or not data.get("token"):
        _log_boundary_failure("create_protocol")
        return None
    return data


async def _ensure_workspace(
    redis_client,
    thread_id: str | None,
    user_id: str | None,
    *,
    settings: tuple[bool, str, float, str, float],
) -> dict | None:
    """Ссылка на песочницу треда: из привязки или новая. `None` — песочницы нет.

    ⚠️ `user_id` кладём в ссылку САМИ: сайдкар сверит его с подписью токена, и подменить
    владельца по дороге не выйдет. Брать его из тела запроса на той стороне было бы
    доверием к полю, которое как раз и проверяется.
    """
    enabled, base, timeout, key, ttl_sec = settings
    if not base or not thread_id or not user_id:
        return None

    existing = await _read_binding(redis_client, str(thread_id))
    if existing:
        return {**existing, "user_id": str(user_id), "thread_id": str(thread_id)}

    # ``enabled`` is the automatic-allocation switch, not a revocation switch.
    # A sandbox created explicitly in Work Hub must remain available to the
    # next agent round even when implicit chat allocation is disabled.
    if not enabled:
        return None

    created = await _create(base, key, timeout, str(user_id), ttl_sec)
    if created is None:
        return None
    ref = {
        "workspace_id": created["workspace_id"],
        "token": created["token"],
        "root": created.get("root") or "/workspace",
        # Absolute expiry is needed by the collaboration coordinator.  It must
        # never extend ephemeral Redis state beyond the sandbox lifetime.
        "expires_at": float(created.get("expires_at") or 0.0),
        "user_id": str(user_id),
        # ⚠️ ССЫЛКА ЗНАЕТ СВОЙ ТРЕД. Не для сайдкара — ему тред не нужен и не отправляется,
        # — а для нас: узнав, что песочницы больше нет, привязку надо стереть, а стирается
        # она ПО ТРЕДУ. Без этого поля тред пришлось бы тащить отдельным аргументом сквозь
        # весь путь обработки хода до шага артефактов.
        "thread_id": str(thread_id),
    }
    await _save_binding(redis_client, str(thread_id), ref, ttl_sec * BINDING_TTL_RATIO)
    return ref


async def ensure_workspace(redis_client, thread_id: str | None, user_id: str | None) -> dict | None:
    """Create only when automatic sandbox allocation is enabled."""
    return await _ensure_workspace(redis_client, thread_id, user_id, settings=_config())


async def ensure_workspace_explicit(
    redis_client, thread_id: str | None, user_id: str | None
) -> dict | None:
    """Create after a deliberate, authenticated Work Hub action only."""
    return await _ensure_workspace(
        redis_client,
        thread_id,
        user_id,
        settings=_explicit_creation_config(),
    )


async def release_workspace(redis_client, thread_id: str | None) -> None:
    """Отпустить песочницу треда: удалить контейнер и стереть привязку.

    ⚠️ Привязку стираем ДАЖЕ ЕСЛИ удалить не вышло: оставленный ключ означал бы, что тред
    навсегда указывает на песочницу, которой нет, — а не оставленный просто создаст новую.
    """
    if not thread_id:
        return
    ref = await _read_binding(redis_client, str(thread_id))
    enabled, base, timeout, key, _ = _config()
    if ref and enabled and base:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                await client.request(
                    "DELETE",
                    f"{base}/workspaces/{ref['workspace_id']}",
                    json={"user_id": ref.get("user_id", ""), "token": ref.get("token", "")},
                    headers=headers,
                )
        except Exception:  # noqa: BLE001
            _log_boundary_failure("destroy_transport")
    try:
        await _redis_call(redis_client, "delete", _key(str(thread_id)))
    except Exception:  # noqa: BLE001
        _log_boundary_failure("binding_cleanup", level=logging.DEBUG)


async def _call(
    ref: dict | None,
    path: str,
    body: dict,
    *,
    bounded_errors: frozenset[str] = frozenset(),
) -> dict | None:
    """Обращение к песочнице владельца. ``None`` — не смогли (best-effort по всему пути).

    Владение подтверждает САЙДКАР по подписи токена: мы лишь возим то, что нам выдали
    при создании. Поэтому здесь нет ни одной проверки прав — она была бы второй копией
    правила, которая однажды разойдётся с первой.

    🔴 ЕДИНСТВЕННОЕ ИСКЛЮЧЕНИЕ ИЗ best-effort — `WorkspaceGone` на 404. Это не «сайдкар не
    справился», а определённый ответ «такой песочницы нет»: 403 сайдкар отдаёт отдельно,
    когда токен не подошёл, так что 404 приходит ровно тогда, когда песочница истекла или
    пропала вместе с реестром. Молча вернуть `None` здесь значит выдать смерть за пустоту.
    """
    if not ref or not ref.get("workspace_id"):
        return None
    enabled, base, timeout, key, _ = _config()
    if not enabled or not base:
        return None
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    capability = str(ref.get("coordination_capability") or "")
    payload = {
        "user_id": ref.get("user_id", ""),
        "token": ref.get("token", ""),
        **({"coordination_capability": capability} if capability else {}),
        **body,
    }
    url = f"{base}/workspaces/{ref['workspace_id']}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
    except Exception:  # noqa: BLE001 — transport/timeout is not proof that the sandbox died
        _log_boundary_failure("transport")
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable") from None
    error_code = ""
    if response.status_code >= 400:
        try:
            candidate = str((response.json() or {}).get("error") or "")
        except (AttributeError, TypeError, ValueError):
            candidate = ""
        if candidate in bounded_errors:
            error_code = candidate
    if response.status_code == 404:
        if not error_code:
            try:
                error_code = str((response.json() or {}).get("error") or "")
            except (AttributeError, TypeError, ValueError):
                error_code = ""
        # A nested resource may be missing while the owning sandbox is healthy.
        # New sidecars make workspace death explicit.  During a rolling deploy,
        # legacy generic 404 remains authoritative only on whole-workspace probes.
        workspace_probe = path in {"view", "history", "snapshot", "files/tree"}
        if error_code == "workspace_not_found" or (error_code == "not_found" and workspace_probe):
            raise WorkspaceGone(f"песочница {ref['workspace_id']} истекла или пропала")
        if error_code in bounded_errors:
            raise WorkspaceRequestRejected(error_code, response.status_code)
        return None
    if response.status_code == 409:
        if not error_code:
            try:
                error_code = str((response.json() or {}).get("error") or "")
            except (AttributeError, TypeError, ValueError):
                error_code = ""
        if error_code == "workspace_conflict":
            raise WorkspaceConflict("workspace revision changed")
    if error_code in bounded_errors:
        raise WorkspaceRequestRejected(error_code, response.status_code)
    if response.status_code >= 400:
        _log_boundary_failure("remote", status=response.status_code)
        if response.status_code >= 500:
            raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable")
        return None
    try:
        data = response.json()
    except ValueError:
        _log_boundary_failure("protocol")
        raise WorkspaceUnavailable("workspace sidecar returned an invalid response") from None
    if not isinstance(data, dict):
        raise WorkspaceUnavailable("workspace sidecar returned an invalid response")
    return data


async def tree(ref: dict | None, path: str = "") -> dict:
    """Дерево содержимого песочницы — для панели рабочего места.

    ⚠️ ПО ЗАПРОСУ, а не вместе с каждым ответом: дерево на тысячу файлов и превью на
    мегабайт не должны ехать в каждом сообщении.
    """
    data = await _call(ref, "files/tree", {"path": path or ""})
    return data or {"entries": []}


async def view(ref: dict | None, path: str = "") -> dict:
    """Read tree, history and revision from one sidecar operation boundary."""
    data = await _call(ref, "view", {"path": path or ""})
    return data or {"entries": [], "history": [], "revision": ""}


async def read_file(ref: dict | None, path: str) -> dict | None:
    """Превью файла песочницы. ``None`` — нет файла либо прочитать не удалось.

    ⚠️ Путь проходит `safe_path` НА СТОРОНЕ САЙДКАРА, там же, где живёт корень политики.
    Проверка здесь была бы проверкой, которую вызывающий может и не сделать.
    """
    return await _call(ref, "files/read", {"path": str(path or "")})


async def write_file(
    ref: dict | None,
    path: str,
    content: str,
    expected_revision: str,
    *,
    fence: int | None = None,
    coordination_capability: str = "",
) -> dict | None:
    """Atomically write an editor update guarded by revision and a path lease."""
    body = {
        "path": str(path or ""),
        "content": str(content),
        "expected_revision": str(expected_revision or ""),
        "coordination_capability": str(coordination_capability or ""),
    }
    if fence is not None:
        body["coordination_fence"] = int(fence)
    return await _call(ref, "files/write", body)


async def snapshot(ref: dict | None, message: str) -> dict | None:
    """Зафиксировать состояние песочницы после хода, который что-то менял.

    Сообщение снимка — запрос человека: по нему история читается как разговор, а не как
    «commit 1, commit 2».
    """
    return await _call(ref, "snapshot", {"message": str(message or "")[:200]})


async def history(ref: dict | None) -> dict:
    """История правок песочницы (новейшая первой). Пусто — правок не было или нет git."""
    data = await _call(ref, "history", {})
    return data or {"entries": []}


async def diff(ref: dict | None, revision: str = "", path: str = "") -> str:
    """Что изменилось от ревизии до текущего состояния. Пусто — нечего показывать."""
    data = await _call(ref, "diff", {"ref": revision or "", "path": path or ""})
    return str((data or {}).get("diff") or "")


async def revert(
    ref: dict | None, revision: str, expected_revision: str, path: str = ""
) -> dict | None:
    """Вернуть файл (или всё дерево) к состоянию ревизии."""
    return await _call(
        ref,
        "revert",
        {
            "ref": str(revision or ""),
            "expected_revision": str(expected_revision or ""),
            "path": path or "",
        },
    )


async def import_into_workspace(
    ref: dict | None,
    files: list[dict] | None,
    *,
    expected_revision: str = "",
    fence: int | None = None,
) -> dict | None:
    """Import a caller-approved source into a workspace without exposing its URL.

    ``files`` is an internal backend-to-sidecar payload.  The public chat API
    accepts only an opaque library file id and deliberately never forwards a
    source URL or storage key to a browser.
    """
    if not ref or not files:
        return {"files": [], "imported": 0, "kept": 0}
    payload = [
        {"name": str(f.get("name") or ""), "url": str(f.get("url") or "")}
        for f in files
        if isinstance(f, dict) and f.get("url")
    ]
    if not payload:
        return {"files": [], "imported": 0, "kept": 0}
    body = {"files": payload}
    if expected_revision:
        body["expected_revision"] = str(expected_revision)
    if fence is not None:
        body["coordination_fence"] = int(fence)
    return await _call(ref, "import", body)


from .workspace_documents import (  # noqa: E402, F401 - compatibility facade
    DocumentArtifactDownload,
    DocumentArtifactMissing,
    activate_document_vendor_profile,
    apply_document_profile,
    apply_document_vendor_overlay,
    cancel_document_build,
    create_document_project,
    document_authoring_state,
    document_build_status,
    document_profiles,
    document_project_status,
    publish_document_source,
    start_document_build,
    stream_document_artifact,
)


async def import_files(ref: dict | None, files: list[dict] | None) -> int:
    """Положить приложенные пользователем файлы внутрь песочницы. Возвращает сколько взято.

    ⚠️ ССЫЛКАМИ, а не байтами: качает сайдкар. Список тот же, что уже собран для табличного
    инструмента, — второй сборки не заводим, иначе два представления одного и того же
    однажды разойдутся.

    Best-effort: не вышло — агент просто не увидит файлов в каталоге и скажет об этом. Это
    не повод ронять сообщение пользователя.
    """
    if not ref or not files:
        return 0
    enabled, base, _timeout, _key, _ = _config()
    if not enabled or not base:
        return 0
    payload = [
        {"name": str(f.get("name") or ""), "url": str(f.get("url") or "")}
        for f in files
        if isinstance(f, dict) and f.get("url")
    ]
    if not payload:
        return 0
    # ⚠️ Сдерживание охватывает ТОЛЬКО поход в сеть. Раньше оно накрывало и сборку тела —
    # то есть глотало и ошибки программиста, и (в тестах) сами провалы проверок: мутация
    # «слать записи без ссылки» оставалась зелёной, потому что исключение из подмены
    # ловилось этим же `except`. Широкое сдерживание прячет не только сбои чужого сервиса.
    try:
        # Coordination-capable imports are optimistic mutations.  Observe one
        # coherent revision immediately before publishing instead of sending the
        # capability-only payload that the sidecar correctly rejects with 422.
        current = await view(ref)
        revision = str(current.get("revision") or "")
        if not revision:
            _log_boundary_failure("import_preflight")
            return 0
        data = await import_into_workspace(ref, payload, expected_revision=revision)
    except WorkspaceConflict:
        _log_boundary_failure("import_conflict")
        return 0
    except WorkspaceUnavailable:
        _log_boundary_failure("import_transport")
        return 0
    if not isinstance(data, dict):
        _log_boundary_failure("import_protocol")
        return 0
    # ⚠️ Непринятые файлы называем ПОИМЁННО: молча укоротившийся список выглядит как
    # «столько и было», и разбираться пришлось бы по чужим логам.
    #
    # 🔴 НО `kept` — НЕ ОТКАЗ. Импорт повторяется на КАЖДОМ ходу, и со второго все файлы
    # диалога отвечают «уже лежит»: сайдкар не перезаписывает их, чтобы не стереть работу
    # агента. Считая это отказом, мы писали бы предупреждение на каждый файл каждого хода —
    # и настоящий отказ утонул бы в ровном шуме, ради предотвращения которого лог и заведён.
    refused = [f for f in (data.get("files") or []) if not f.get("imported") and not f.get("kept")]
    if refused:
        _log_boundary_failure("import_rejected")
    return int(data.get("imported") or 0)


# Сколько артефактов и байт забираем за прогон. 🔴 Не «сколько создал агент»: он мог
# сгенерировать тысячу файлов циклом, и выгрузка каждого — это трафик и место в хранилище,
# за которые платит платформа.
MAX_ARTIFACTS = 10
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


async def collect_artifacts(ref: dict | None, inventory: list[dict] | None) -> list[dict]:
    """Забрать созданные агентом файлы по описи → `[{filename, file_b64}]`.

    ⚠️ Форма ответа — та, которую уже понимает мост артефактов (`_pending_artifacts`), а не
    своя: у моста есть хранилище, фолбэк по владельцу и запись в `generated_files`. Новой
    машинерии не строим, иначе появится второй способ отдать пользователю файл.

    Best-effort: не смогли забрать — пользователь просто не увидит файла, но ответ получит.
    """
    if not ref or not inventory:
        return []
    enabled, base, timeout, key, _ = _config()
    if not enabled or not base:
        return []
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out: list[dict] = []
    total = 0
    attempts = 0
    for item in inventory:
        # 🔴 Потолок на ОБРАЩЕНИЯ, а не на успехи. Считая успехи, мы при неудачных выгрузках
        # опрашивали бы сайдкар по КАЖДОЙ записи описи — а её пишет агент, и он мог создать
        # тысячу файлов циклом. Нашёл собственный тест: 30 запросов при потолке 10.
        if attempts >= MAX_ARTIFACTS or total >= MAX_ARTIFACT_BYTES:
            _log_boundary_failure("artifact_limit")
            break
        path = str((item or {}).get("path") or "").strip()
        size = int((item or {}).get("size") or 0)
        if not path or size <= 0 or size > MAX_ARTIFACT_BYTES:
            continue
        attempts += 1
        body = {"user_id": ref.get("user_id", ""), "token": ref.get("token", ""), "path": path}
        url = f"{base}/workspaces/{ref['workspace_id']}/files/download"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=body, headers=headers)
        except Exception:  # noqa: BLE001 — чужой сервис лёг, ответ пользователю не роняем
            _log_boundary_failure("artifact_transport")
            continue
        if response.status_code >= 400:
            _log_boundary_failure("artifact_remote", status=response.status_code)
            continue
        try:
            content = str((response.json() or {}).get("content_b64") or "")
        except ValueError:
            continue
        if not content:
            continue
        total += size
        # Имя — БЕЗ каталогов: пользователю уезжает файл, а не путь внутри контейнера.
        out.append({"filename": path.rsplit("/", 1)[-1], "file_b64": content})
    return out
