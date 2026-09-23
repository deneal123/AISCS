"""Рабочее место треда: дерево, превью, история, откат — и кому это видно.

🔴 Песочница есть, но человек её не видел: файлы появлялись и исчезали, история правок
не хранилась, найти нужный файл было нечем. Ручки доводят её до рабочего места.

🔴 ГЛАВНОЕ ЗДЕСЬ — ВЛАДЕНИЕ. «Покажи дерево» и «покажи файл» без проверки треда стали бы
чтением ЧУЖОЙ песочницы по угаданному `thread_id`. Проверок две, и они про разное: тред
принадлежит спрашивающему (здесь), песочница — владельцу токена (в сайдкаре).
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from service.services.chat.presentation.routers.chat_api import workspace_api as api

REF = {
    "workspace_id": "ws1",
    "token": "t.sig",
    "user_id": "7",
    "root": "/workspace",
    "expires_at": 4_000_000_000.0,
}


class _Service:
    def __init__(self, owned: bool = True):
        self.owned = owned
        self.checked: list[tuple[str, str]] = []

    async def ensure_thread_owner(self, thread_id, user_id):
        self.checked.append((thread_id, user_id))
        if not self.owned:
            raise HTTPException(status_code=404, detail="Thread not found")


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "workspace-panel-test-secret")
    calls: dict = {}

    async def _binding(redis, thread_id):
        calls["binding"] = thread_id
        return REF

    async def _tree(ref, path=""):
        calls["tree"] = (ref, path)
        return [
            {"type": "dir", "size": 0, "path": "/workspace/src"},
            {"type": "file", "size": 12, "path": "/workspace/src/main.py"},
        ]

    async def _view(ref, path=""):
        calls["view"] = (ref, path)
        return {
            "entries": await _tree(ref, path),
            "history": await _history(ref),
            "revision": "current",
            "recovered": False,
        }

    async def _binding_state(redis, thread_id):
        return "ready", REF

    async def _read(ref, path):
        calls["read"] = (ref, path)
        return {"path": path, "content": "print(1)", "truncated": False}

    async def _history(ref):
        calls["history"] = ref
        return [{"ref": "a1b2c3", "at": "2026-07-28T10:00:00+00:00", "message": "правка"}]

    async def _revert(ref, revision, expected_revision, path=""):
        calls["revert_ref"] = ref
        calls["revert"] = (revision, expected_revision, path)
        return {"reverted": True, "revision": "next"}

    monkeypatch.setattr(api.workspace_client, "read_binding", _binding)
    monkeypatch.setattr(api.workspace_client, "read_binding_state", _binding_state)
    monkeypatch.setattr(api.workspace_client, "tree", _tree)
    monkeypatch.setattr(api.workspace_client, "view", _view)
    monkeypatch.setattr(api.workspace_client, "read_file", _read)
    monkeypatch.setattr(api.workspace_client, "history", _history)
    monkeypatch.setattr(api.workspace_client, "revert", _revert)
    return calls


class _Profile:
    user_id = "7"


class _Library:
    async def list_chat_library(self, user_id, *, limit=200):
        assert str(user_id) == "7"
        return [
            {
                "file_id": "opaque-file-id",
                "name": "contract.docx",
                "file_type": "CHAT",
                "availability": "ready",
            }
        ]


@pytest.mark.asyncio
async def test_tree_returns_paths_relative_to_the_root(sandbox):
    """Абсолютный путь внутри чужого контейнера человеку ничего не говорит."""
    out = await api.workspace_tree("t-1", _Profile(), "", _Service(), None)

    assert out["root"] == "/workspace"
    assert [e["path"] for e in out["entries"]] == ["src", "src/main.py"]


@pytest.mark.asyncio
async def test_stranger_cannot_read_someone_elses_workspace(sandbox):
    """⚠️ ГЛАВНОЕ. Не твой тред — не твоя песочница, и это решается ДО похода в неё."""
    service = _Service(owned=False)

    with pytest.raises(HTTPException) as exc:
        await api.workspace_tree("t-1", _Profile(), "", service, None)

    assert exc.value.status_code == 404
    assert "tree" not in sandbox, "в чужую песочницу всё-таки сходили"


@pytest.mark.asyncio
async def test_every_handle_checks_the_thread_owner(sandbox):
    """Проверка нужна у КАЖДОЙ ручки: забытая в одной открывает всё остальное."""
    service = _Service()
    await api.workspace_tree("t-1", _Profile(), "", service, None)
    await api.workspace_file("t-1", api.PathRequest(path="src/main.py"), _Profile(), service, None)
    await api.workspace_history("t-1", _Profile(), service, None)
    await api.workspace_revert(
        "t-1",
        api.RevertRequest(ref="a1b2c3", expected_revision="current"),
        _Profile(),
        service,
        None,
    )

    assert len(service.checked) == 4, "какая-то ручка отдаёт песочницу без проверки треда"


@pytest.mark.asyncio
async def test_preview_reads_the_requested_file(sandbox):
    out = await api.workspace_file(
        "t-1", api.PathRequest(path="src/main.py"), _Profile(), _Service(), None
    )

    assert out["content"] == "print(1)"
    assert sandbox["read"][1] == "src/main.py"


@pytest.mark.asyncio
async def test_missing_file_is_404_not_empty_preview(sandbox, monkeypatch):
    async def _none(ref, path):
        return None

    monkeypatch.setattr(api.workspace_client, "read_file", _none)

    with pytest.raises(HTTPException) as exc:
        await api.workspace_file(
            "t-1", api.PathRequest(path="нет.txt"), _Profile(), _Service(), None
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_history_and_revert(sandbox):
    entries = (await api.workspace_history("t-1", _Profile(), _Service(), None))["entries"]
    assert entries[0]["ref"] == "a1b2c3"

    out = await api.workspace_revert(
        "t-1",
        api.RevertRequest(ref="a1b2c3", expected_revision="current", path="src/main.py"),
        _Profile(),
        _Service(),
        None,
    )
    assert out["reverted"] is True
    assert sandbox["revert"] == ("a1b2c3", "current", "src/main.py")
    assert sandbox["revert_ref"]["coordination_capability"]


@pytest.mark.asyncio
async def test_failed_revert_is_reported_not_swallowed(sandbox, monkeypatch):
    async def _no(ref, revision, expected_revision, path=""):
        return {"reverted": False}

    monkeypatch.setattr(api.workspace_client, "revert", _no)

    with pytest.raises(HTTPException) as exc:
        await api.workspace_revert(
            "t-1",
            api.RevertRequest(ref="zzz", expected_revision="current"),
            _Profile(),
            _Service(),
            None,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_no_sandbox_is_404(monkeypatch):
    async def _none(redis, thread_id):
        return None

    monkeypatch.setattr(api.workspace_client, "read_binding", _none)

    with pytest.raises(HTTPException) as exc:
        await api.workspace_tree("t-1", _Profile(), "", _Service(), None)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_work_snapshot_joins_safe_library_with_the_current_workspace(sandbox, monkeypatch):
    """The Work Hub receives names/opaque ids, never source URLs or keys."""

    class _Store:
        async def snapshot(self, *, revision):
            return {
                "issues": [],
                "leases": [],
                "activity": [],
                "control": {"state": "running"},
                "revision": revision,
            }

    monkeypatch.setattr(api, "_collaboration", lambda ref, redis: _Store())
    out = await api.work_snapshot("t-1", _Profile(), _Service(), _Library(), None, 20)

    assert out["workspace"]["state"] == "ready"
    assert out["workspace"]["entries"][1]["path"] == "src/main.py"
    assert out["library"]["items"] == [
        {
            "file_id": "opaque-file-id",
            "name": "contract.docx",
            "file_type": "CHAT",
            "availability": "ready",
        }
    ]
    assert "url" not in str(out).lower()
    assert "token" not in str(out).lower()


@pytest.mark.asyncio
async def test_work_library_never_allocates_a_sandbox():
    out = await api.account_work_library(_Profile(), _Library(), 20)

    assert out["items"][0]["file_id"] == "opaque-file-id"


def test_snapshot_is_taken_after_every_turn():
    """🔴 БЕЗУСЛОВНО, а не «если агент создал файл».

    Опись артефактов перечисляет НОВЫЕ файлы; правка импортированного в неё не попадает
    вовсе — а именно её и нельзя было бы восстановить. «Нечего фиксировать» отличает сам
    сайдкар.
    """
    from service.services.chat.infrastructure.chat_worker import artifacts, run_execution

    finalization = inspect.getsource(run_execution._finalize_success)
    assert "persist_all_artifacts(" in finalization and "request.text" in finalization, (
        "запрос человека не доезжает до снимка — история станет «commit 1, commit 2»"
    )
    assert "snapshot_workspace(engine_env, user_text)" in inspect.getsource(
        artifacts.persist_all_artifacts
    ), "снимок песочницы не делается — история правок останется пустой"

    src = inspect.getsource(artifacts.snapshot_workspace)
    assert "workspace_artifacts" not in src, "снимок снова привязан к описи созданных файлов"


def test_panel_never_creates_a_sandbox():
    """🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. Панель — просмотр, а не создание контейнера.

    Пока `_ref` звал `ensure_workspace`, каждое открытие поднимало НОВУЮ песочницу: в
    логе сайдкара `POST /workspaces` перед каждым `files/tree`, а дерево и история
    приезжали из РАЗНЫХ песочниц — то есть человек видел пустой каталог вместо своего.
    Общий потолок на хост при этом 32 штуки.
    """
    src = inspect.getsource(api._ref)

    assert "read_binding" in src
    assert "ensure_workspace" not in src, "панель снова создаёт песочницу на чтение"
