"""Привязка песочницы к треду: переиспользование, срок и отказоустойчивость.

🔴 Главное здесь — соотношение сроков: привязка в Redis обязана жить МЕНЬШЕ, чем песочница
у сайдкара. Иначе есть окно, где тред указывает на уже подметённый контейнер.
"""

from __future__ import annotations

import json

import pytest

from service.infrastructure import workspace_client as wc


class _Redis:
    """Минимальный двойник: только то, что модуль действительно зовёт."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[int, str]] = {}
        self.deleted: list[str] = []

    def get(self, key):
        item = self.store.get(key)
        return item[1].encode() if item else None

    def setex(self, key, ttl, value):
        self.store[key] = (int(ttl), value)

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


@pytest.fixture
def sidecar(monkeypatch):
    """Подменяет создание песочницы и включает выдачу."""
    created: list[str] = []

    async def fake_create(base, key, timeout, user_id, ttl_sec):
        created.append(user_id)
        return {"workspace_id": f"ws{len(created)}", "token": "t.sig", "root": "/workspace"}

    monkeypatch.setattr(wc, "_create", fake_create)
    monkeypatch.setattr(wc, "_config", lambda: (True, "http://workspace:8080", 30.0, "k", 1800.0))
    return created


@pytest.mark.asyncio
async def test_workspace_is_created_once_per_thread(sidecar) -> None:
    """🔴 Создание на каждое сообщение исчерпало бы общий потолок сайдкара за минуты."""
    redis = _Redis()
    first = await wc.ensure_workspace(redis, "t1", "7")
    second = await wc.ensure_workspace(redis, "t1", "7")
    assert first["workspace_id"] == second["workspace_id"]
    assert len(sidecar) == 1, "песочница создана повторно для того же треда"


@pytest.mark.asyncio
async def test_different_threads_get_different_workspaces(sidecar) -> None:
    redis = _Redis()
    a = await wc.ensure_workspace(redis, "t1", "7")
    b = await wc.ensure_workspace(redis, "t2", "7")
    assert a["workspace_id"] != b["workspace_id"]


@pytest.mark.asyncio
async def test_binding_expires_before_the_container_does(sidecar) -> None:
    """🔴 Иначе тред указывает на песочницу, которую уборщик уже удалил."""
    redis = _Redis()
    await wc.ensure_workspace(redis, "t1", "7")
    ttl, _ = redis.store["chat:t1:workspace"]
    assert ttl < 1800, f"привязка живёт {ttl} с при сроке песочницы 1800 с"
    assert ttl == int(1800 * wc.BINDING_TTL_RATIO)


@pytest.mark.asyncio
async def test_owner_travels_with_the_reference(sidecar) -> None:
    """Сайдкар сверит владельца с подписью токена — значит он обязан ехать в ссылке."""
    redis = _Redis()
    ref = await wc.ensure_workspace(redis, "t1", "7")
    assert ref["user_id"] == "7" and ref["token"]


@pytest.mark.asyncio
async def test_disabled_means_no_workspace_at_all(monkeypatch) -> None:
    """Выключено — ни одного обращения к сайдкару: инструменты отсеются гейтом."""
    monkeypatch.setattr(wc, "_config", lambda: (False, "http://workspace:8080", 30.0, "k", 1800.0))

    async def explode(*args, **kwargs):
        raise AssertionError("обращение к сайдкару при выключенной песочнице")

    monkeypatch.setattr(wc, "_create", explode)
    assert await wc.ensure_workspace(_Redis(), "t1", "7") is None


@pytest.mark.asyncio
async def test_disabled_autocreate_still_exposes_an_explicit_existing_binding(monkeypatch) -> None:
    """Work Hub allocation is explicit; the next agent round must consume it.

    The switch controls creation only.  Treating it as a revocation hid every
    already-created Work sandbox from ``ws_*`` tools.
    """
    monkeypatch.setattr(wc, "_config", lambda: (False, "http://workspace:8080", 30.0, "k", 1800.0))
    redis = _Redis()
    redis.setex(
        "chat:t1:workspace",
        1200,
        json.dumps(
            {
                "workspace_id": "explicit-ws",
                "token": "opaque-token",
                "root": "/workspace",
                "expires_at": 4_102_444_800.0,
            }
        ),
    )

    async def explode(*_args, **_kwargs):
        raise AssertionError("existing explicit binding must not allocate another sandbox")

    monkeypatch.setattr(wc, "_create", explode)
    ref = await wc.ensure_workspace(redis, "t1", "7")

    assert ref and ref["workspace_id"] == "explicit-ws"
    assert ref["thread_id"] == "t1" and ref["user_id"] == "7"


@pytest.mark.asyncio
async def test_dead_sidecar_yields_no_workspace_not_an_error(monkeypatch) -> None:
    """Сайдкар не поднят — чат обязан работать без песочницы."""
    monkeypatch.setattr(wc, "_config", lambda: (True, "http://workspace:8080", 30.0, "k", 1800.0))

    async def dead(*args, **kwargs):
        return None

    monkeypatch.setattr(wc, "_create", dead)
    assert await wc.ensure_workspace(_Redis(), "t1", "7") is None


@pytest.mark.asyncio
async def test_broken_binding_does_not_poison_the_thread(sidecar) -> None:
    """Мусор в Redis не должен навсегда лишать тред песочницы."""
    redis = _Redis()
    redis.store["chat:t1:workspace"] = (100, "не json")
    ref = await wc.ensure_workspace(redis, "t1", "7")
    assert ref and ref["workspace_id"] == "ws1"


@pytest.mark.asyncio
async def test_release_clears_the_binding_even_if_deletion_fails(monkeypatch, sidecar) -> None:
    """⚠️ Оставленный ключ означал бы вечную ссылку на несуществующую песочницу."""
    redis = _Redis()
    await wc.ensure_workspace(redis, "t1", "7")

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("сеть легла")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Boom())
    await wc.release_workspace(redis, "t1")
    assert "chat:t1:workspace" in redis.deleted


@pytest.mark.asyncio
async def test_stored_reference_carries_no_url(sidecar) -> None:
    """Адрес сайдкара в ссылке не хранится: он координата развёртывания, а не данные треда."""
    redis = _Redis()
    await wc.ensure_workspace(redis, "t1", "7")
    _, raw = redis.store["chat:t1:workspace"]
    assert "http" not in json.loads(raw).get("root", "")
    assert "url" not in json.loads(raw)


@pytest.mark.asyncio
async def test_autocreate_is_off_by_default() -> None:
    """🔴 Каждая песочница — КОНТЕЙНЕР. Дефолт «создавать всем» исчерпал бы потолок хоста
    за минуты, причём молча: пользователь увидел бы «недоступно» без единой ошибки.

    ⚠️ Тест смотрит на НАСТОЯЩИЙ конфиг, а не на подменённый: дефолт — это и есть предмет
    проверки, и подмена превратила бы его в проверку самой подмены.
    """
    from service.settings import config

    assert config.agents.workspace_autocreate is False
    assert wc._config()[0] is False, "создание включено при выключенном автосоздании"


@pytest.mark.asyncio
async def test_explicit_work_action_is_not_blocked_by_autocreate_switch(monkeypatch) -> None:
    """A person can create Work even while implicit chat allocation is off."""
    monkeypatch.setattr(
        wc,
        "_explicit_creation_config",
        lambda: (True, "http://workspace:8080", 30.0, "k", 1800.0),
    )

    async def created(*_args):
        return {"workspace_id": "explicit-ws", "token": "t.sig", "root": "/workspace"}

    monkeypatch.setattr(wc, "_create", created)

    ref = await wc.ensure_workspace_explicit(_Redis(), "t-explicit", "7")

    assert ref and ref["workspace_id"] == "explicit-ws"


# --- импорт приложенных файлов --------------------------------------------------------


@pytest.mark.asyncio
async def test_files_travel_as_links_not_bytes(monkeypatch, sidecar) -> None:
    """⚠️ Качает САЙДКАР: файл весит десятки мегабайт, а тело запроса маленькое намеренно."""
    sent: list[dict] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append({"url": url, "json": json})

            class _R:
                status_code = 200

                def json(self):
                    if url.endswith("/view"):
                        return {"revision": "rev-before-import", "entries": [], "history": []}
                    return {"imported": 1, "files": [{"name": "a.csv", "imported": True}]}

            return _R()

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Client())
    ref = {
        "workspace_id": "ws1",
        "token": "t",
        "user_id": "7",
        "coordination_capability": "opaque-capability",
    }
    taken = await wc.import_files(ref, [{"name": "a.csv", "url": "https://s3/a.csv"}])
    assert taken == 1
    assert [item["url"].rsplit("/", 1)[-1] for item in sent] == ["view", "import"]
    mutation = sent[-1]["json"]
    assert mutation["files"] == [{"name": "a.csv", "url": "https://s3/a.csv"}]
    assert mutation["expected_revision"] == "rev-before-import"
    assert mutation["coordination_capability"] == "opaque-capability"
    assert "content" not in str(mutation), "байты не должны ехать в теле"


def _recorder(monkeypatch, calls: list):
    """⚠️ ЗАПИСЫВАЕТ обращение, а не бросает исключение.

    Бросок здесь бесполезен: сдерживание вокруг похода в сеть поймало бы и его, и тест
    зеленел бы на мутации «звать сайдкар всегда». Проверять надо ФАКТ вызова.
    """

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(url)

            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"imported": 0, "files": []}

            return _R()

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Client())
    return calls


@pytest.mark.asyncio
async def test_no_workspace_means_no_import_attempt(monkeypatch, sidecar) -> None:
    """⚠️ Фикстура `sidecar` ВКЛЮЧАЕТ выдачу: без неё отказ давал бы выключенный тумблер,
    и проверка «нет песочницы — нет вызова» осталась бы непроверенной."""
    calls = _recorder(monkeypatch, [])
    assert await wc.import_files(None, [{"name": "a", "url": "u"}]) == 0
    assert await wc.import_files({"workspace_id": "w"}, []) == 0
    assert calls == [], "сайдкар вызван без песочницы или без файлов"


@pytest.mark.asyncio
async def test_entries_without_a_url_are_dropped(monkeypatch, sidecar) -> None:
    """Запись без ссылки качать нечем — до сайдкара она доехать не должна вовсе."""
    calls = _recorder(monkeypatch, [])
    assert await wc.import_files({"workspace_id": "w", "token": "t"}, [{"name": "a"}]) == 0
    assert calls == [], "запись без ссылки уехала в сайдкар"


@pytest.mark.asyncio
async def test_dead_sidecar_does_not_break_the_message(monkeypatch, sidecar) -> None:
    """Не вышло — агент просто не увидит файлов и скажет об этом. Сообщение не роняем."""

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("сеть легла")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Boom())
    ref = {"workspace_id": "ws1", "token": "t", "user_id": "7"}
    assert await wc.import_files(ref, [{"name": "a.csv", "url": "https://s3/a"}]) == 0


# --- артефакты пользователю -----------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_ride_the_existing_bridge(monkeypatch, sidecar) -> None:
    """⚠️ Форма — та, что мост УЖЕ понимает. Второй способ отдать файл означал бы второе
    место, где чинить владельца, хранилище и запись в `generated_files`."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"content_b64": "YmluYXJ5"}

            return _R()

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Client())
    ref = {"workspace_id": "ws1", "token": "t", "user_id": "7"}
    files = await wc.collect_artifacts(ref, [{"path": "out/report.md", "size": 6}])
    assert files == [{"filename": "report.md", "file_b64": "YmluYXJ5"}]


@pytest.mark.asyncio
async def test_directories_do_not_leak_into_the_user_filename(monkeypatch, sidecar) -> None:
    """Пользователю уезжает ФАЙЛ, а не путь внутри контейнера."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"content_b64": "eA=="}

            return _R()

    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **kw: _Client())
    files = await wc.collect_artifacts(
        {"workspace_id": "w", "token": "t"}, [{"path": "a/b/c.txt", "size": 1}]
    )
    assert files[0]["filename"] == "c.txt"


@pytest.mark.asyncio
async def test_artifact_count_and_size_are_capped(monkeypatch, sidecar) -> None:
    """🔴 Агент мог создать тысячу файлов циклом: выгрузка каждого — трафик и место,
    за которые платит платформа."""
    calls = _recorder(monkeypatch, [])
    inventory = [{"path": f"f{i}.txt", "size": 10} for i in range(wc.MAX_ARTIFACTS + 20)]
    files = await wc.collect_artifacts({"workspace_id": "w", "token": "t"}, inventory)
    assert len(files) <= wc.MAX_ARTIFACTS
    assert len(calls) <= wc.MAX_ARTIFACTS, "сайдкар опрошен по файлам сверх потолка"


@pytest.mark.asyncio
async def test_oversized_artifact_is_skipped_without_a_request(monkeypatch, sidecar) -> None:
    calls = _recorder(monkeypatch, [])
    huge = [{"path": "big.bin", "size": wc.MAX_ARTIFACT_BYTES + 1}]
    assert await wc.collect_artifacts({"workspace_id": "w", "token": "t"}, huge) == []
    assert calls == [], "за файлом сверх потолка всё равно сходили"


@pytest.mark.asyncio
async def test_no_inventory_means_no_requests(monkeypatch, sidecar) -> None:
    calls = _recorder(monkeypatch, [])
    assert await wc.collect_artifacts({"workspace_id": "w", "token": "t"}, []) == []
    assert await wc.collect_artifacts(None, [{"path": "a", "size": 1}]) == []
    assert calls == []


@pytest.mark.asyncio
async def test_bridge_understands_a_plain_file_from_the_sandbox(monkeypatch) -> None:
    """Мост знал только презентации и картинки: без этой ветви файл песочницы пропадал."""
    from service.infrastructure.agents_client import agent_file_bridge as bridge

    class _Saved:
        file_id = "id-1"
        file_url = "https://files/report.md"
        file_key = "k"

    async def fake_save(**kwargs):
        assert kwargs["content"] == b"binary"
        return _Saved()

    monkeypatch.setattr(bridge, "_save_with_fallback", fake_save)
    entry = await bridge._persist_one_artifact(
        {"file_b64": "YmluYXJ5", "filename": "report.md"},
        file_service=None,
        user_uuid_candidates=["u"],
        user_id="7",
        job_id="j",
        idx=0,
    )
    assert entry["kind"] == "file"
    assert entry["filename"] == "report.md"
    assert entry["mime_type"].startswith("text/")


# --- клиент Redis бывает и синхронным, и асинхронным ----------------------------------


class _AsyncRedis:
    """Двойник `redis.asyncio.Redis`: команды — ОБЫЧНЫЕ методы, возвращающие корутину."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def execute_command(self, *args, **kwargs):  # маркер асинхронности клиента
        return None

    def get(self, key):
        async def _run():
            return self.store.get(key)

        return _run()

    def setex(self, key, ttl, value):
        async def _run():
            self.store[key] = value
            return True

        return _run()


@pytest.mark.asyncio
async def test_binding_survives_an_async_redis_client(monkeypatch, sidecar) -> None:
    """🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. Веб-процесс держит АСИНХРОННЫЙ клиент, воркер — синхронный.

    `inspect.iscoroutinefunction(client.get)` на `redis.asyncio` отвечает ЛОЖЬ: команды
    там обычные методы, возвращающие корутину. Проверка по команде уводила асинхронный
    клиент в `to_thread`, тот возвращал НЕ ДОЖДАННУЮ корутину — привязка молча не
    писалась и не читалась, и панель рабочего места каждый раз отвечала «песочницы нет»,
    а прогон поднимал НОВЫЙ контейнер (при общем потолке в 32 штуки).
    """
    redis = _AsyncRedis()

    first = await wc.ensure_workspace(redis, "t-async", "7")
    assert first and first["workspace_id"]

    stored = await wc.read_binding(redis, "t-async")
    assert stored and stored["workspace_id"] == first["workspace_id"], (
        "привязка не сохранилась через асинхронный клиент"
    )

    second = await wc.ensure_workspace(redis, "t-async", "7")
    assert second["workspace_id"] == first["workspace_id"], "песочница создана повторно"
    assert len(sidecar) == 1, "асинхронный клиент всё ещё плодит песочницы"


@pytest.mark.asyncio
async def test_read_binding_never_creates_a_workspace(sidecar) -> None:
    """Чтение — это чтение: панель не вправе поднимать контейнер."""
    assert await wc.read_binding(_Redis(), "t-empty") is None
    assert sidecar == [], "чтение привязки создало песочницу"


@pytest.mark.asyncio
async def test_a_kept_file_is_not_logged_as_a_refusal(monkeypatch, sidecar) -> None:
    """🔴 `kept` — НЕ ОТКАЗ, и путать их дорого именно из-за частоты.

    Импорт повторяется на КАЖДОМ ходу, и со второго все файлы диалога отвечают «уже лежит»:
    сайдкар их не перезаписывает, чтобы не стереть работу агента. Считая это отказом, мы
    писали бы предупреждение на каждый файл каждого хода — и настоящий отказ утонул бы в
    ровном шуме, ради предотвращения которого лог и заведён.

    ⚠️ Пишем ВЫЗОВЫ логгера, а не `caplog`: тот зависит от глобальной настройки логирования,
    и в общем прогоне тест зеленел/краснел от соседей, а не от правила.
    """
    warned = _capture_warnings(monkeypatch)
    monkeypatch.setattr(
        wc.httpx,
        "AsyncClient",
        lambda **kw: _canned(
            {
                "imported": 0,
                "kept": 2,
                "files": [
                    {"name": "договор.txt", "imported": False, "kept": True},
                    {"name": "смета.xlsx", "imported": False, "kept": True},
                ],
            }
        ),
    )
    ref = {"workspace_id": "ws1", "token": "t", "user_id": "7"}

    assert await wc.import_files(ref, [{"name": "договор.txt", "url": "https://s/x"}]) == 0
    assert not [m for m in warned if "import_rejected" in m], (
        "«уже лежит» записано как отказ — лог наполнится ложной тревогой на каждом ходу"
    )


@pytest.mark.asyncio
async def test_a_real_refusal_is_still_logged(monkeypatch, sidecar) -> None:
    """🔴 БЕЗ ЭТОГО тест выше зелен и от «не предупреждать никогда»."""
    warned = _capture_warnings(monkeypatch)
    monkeypatch.setattr(
        wc.httpx,
        "AsyncClient",
        lambda **kw: _canned(
            {
                "imported": 0,
                "files": [{"name": "битый.zip", "imported": False, "reason": "запись не удалась"}],
            }
        ),
    )
    ref = {"workspace_id": "ws1", "token": "t", "user_id": "7"}

    await wc.import_files(ref, [{"name": "битый.zip", "url": "https://s/x"}])

    assert [m for m in warned if "import_rejected" in m], (
        "файл не взят в песочницу, и об этом никто не узнал"
    )
    assert "битый.zip" not in str(warned)
    assert "запись не удалась" not in str(warned)


def _capture_warnings(monkeypatch) -> list[str]:
    """Собрать предупреждения клиента песочницы, не полагаясь на настройку логирования."""
    seen: list[str] = []

    def _warning(message, *args, **kwargs):
        rendered = str(message) % args if args else str(message)
        failure_code = str((kwargs.get("extra") or {}).get("failure_code") or "")
        seen.append(f"{rendered}:{failure_code}")

    def _log(_level, message, *args, **kwargs):
        _warning(message, *args, **kwargs)

    monkeypatch.setattr(wc.logger, "warning", _warning)
    monkeypatch.setattr(wc.logger, "log", _log)
    return seen


def _canned(payload: dict):
    """Клиент, отвечающий заданным телом на любой POST."""

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            if url.endswith("/view"):
                return _RevisionResponse()
            return _R()

    class _RevisionResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"revision": "rev-before-import", "entries": [], "history": []}

    return _Client()
