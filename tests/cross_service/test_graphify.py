"""Граф знаний: ВХОДНАЯ половина — превращение архива в формат сайдкара.

Что это закрывает:
  * zip раньше уходил в ветку `binary` и декодировался как utf-8 → мусор из ZIP-архива;
  * архив приходит от пользователя — path traversal и zip-бомба обязаны отсекаться ДО
    того, как байты уедут в сайдкар.

Поиск по личному графу и регистрация инструмента уехали в
``agents/tests/cross_service/test_graphify.py``: там они и живут. Гарды остались здесь,
потому что стоят на границе сервиса — сайдкар получает уже готовый tar.gz.
"""

import io
import zipfile

import pytest

from service.infrastructure.graphify import (
    text_to_targz,
    user_graph_id,
    zip_to_targz,
)
from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Безопасность архива                                                          #
# --------------------------------------------------------------------------- #
def test_zip_converts_to_targz():
    payload = zip_to_targz(_zip({"src/a.py": "def a(): pass"}))
    assert payload[:2] == b"\x1f\x8b"  # gzip-магия


@pytest.mark.parametrize("evil", ["../../etc/passwd", "/etc/passwd", "src/../../../etc/passwd"])
def test_zip_rejects_path_traversal(evil):
    """Архив от пользователя не должен уметь писать за пределы своего каталога."""
    with pytest.raises(ValueError, match="traversal"):
        zip_to_targz(_zip({evil: "pwned"}))


def test_zip_rejects_too_many_entries(monkeypatch):
    import service.infrastructure.graphify as gc

    monkeypatch.setattr(gc, "_MAX_ENTRIES", 3)
    with pytest.raises(ValueError, match="entries"):
        gc.zip_to_targz(_zip({f"f{i}.py": "x" for i in range(5)}))


def test_zip_rejects_zip_bomb(monkeypatch):
    import service.infrastructure.graphify as gc

    monkeypatch.setattr(gc, "_MAX_UNPACKED_BYTES", 100)
    with pytest.raises(ValueError, match="size cap"):
        gc.zip_to_targz(_zip({"big.py": "x" * 500}))


# --------------------------------------------------------------------------- #
# Идентификатор личного графа                                                  #
# --------------------------------------------------------------------------- #
def test_user_graph_id_is_stable_and_sanitised():
    """Дубль такого же теста в сайдкаре — намеренный: обе стороны считают graph_id
    сами, и разъезд их формул тихо оторвал бы пользователя от его графа."""
    assert user_graph_id("abc-123") == "user-abc-123"
    # graph_id попадает в путь файла на сайдкаре — мусор из него вычищаем.
    assert user_graph_id("../../etc") == "user-etc"
    assert user_graph_id("") == ""


def test_text_to_targz_wraps_single_document():
    payload = text_to_targz("отчёт.pdf", "# Заголовок\n\nтекст")
    assert payload[:2] == b"\x1f\x8b"


# --------------------------------------------------------------------------- #
# Врезка zip в загрузку                                                        #
# --------------------------------------------------------------------------- #
class _NoFiles:
    async def save(self, **_kw):
        raise RuntimeError("хранилище в тесте не нужно")


class _FakeGraph:
    """Сайдкар, который вернул карту репозитория."""

    enabled = True

    def __init__(self, result=None):
        self.result = (
            result
            if result is not None
            else {
                "nodes": 42,
                "edges": 77,
                "report": "# Graph Report\n\n## Community Hubs\n- AgentProcessor",
            }
        )
        self.calls: list[dict] = []

    async def build(self, tar_gz, *, graph_id, mode="code", merge=False, label=None):
        self.calls.append({"graph_id": graph_id, "mode": mode, "merge": merge})
        return self.result


@pytest.mark.asyncio
async def test_zip_becomes_repository_map():
    """Сегодня zip → binary → мусор из ZIP. Должна получаться карта архитектуры."""
    graph = _FakeGraph()
    uc = UploadFileUseCase(media_analysis_port=None, file_service=_NoFiles(), graph_client=graph)

    text, file_type = await uc._extract_text(
        "project.zip", None, _zip({"src/a.py": "def hello(): return 1"})
    )

    assert file_type == "repo"
    assert "Карта репозитория: project.zip" in text
    assert "42 узлов · 77 связей" in text
    assert "без обращений к LLM" in text
    assert "Community Hubs" in text
    assert graph.calls[0]["mode"] == "code"  # AST, не семантика: это должно быть бесплатно


@pytest.mark.asyncio
async def test_zip_without_a_graph_still_lists_its_files():
    """🔴 ПРЕЖДЕ ЗДЕСЬ ЖДАЛИ `binary` — то есть zip декодировался как utf-8 и приезжал
    мусором. Замер показал цену: на архиве стилей TMLR graphify отвечает «graph is empty»,
    и о вложении не оставалось НИ ОДНОГО факта — агент перечислил три файла из девяти.

    Перечень файлов от графа не зависит: он верен и для архива, в котором кода нет вовсе.
    Fail-open прежний — загрузка не ломается, — но пустоты на выходе больше нет.
    """
    uc = UploadFileUseCase(
        media_analysis_port=None, file_service=_NoFiles(), graph_client=_FakeGraph(result={})
    )

    text, file_type = await uc._extract_text("project.zip", None, _zip({"a.py": "x = 1"}))

    assert file_type == "repo"
    assert "a.py" in text, "состав архива снова неизвестен"


@pytest.mark.asyncio
async def test_zip_without_graph_client_keeps_legacy_path():
    uc = UploadFileUseCase(media_analysis_port=None, file_service=_NoFiles(), graph_client=None)
    _text, file_type = await uc._extract_text("project.zip", None, _zip({"a.py": "x = 1"}))
    assert file_type == "binary"
