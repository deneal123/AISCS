"""Состав архива агент ЗНАЕТ, а не угадывает.

🔴 ЗАМЕРЕНО. Человек приложил `tmlr-style-file-main.zip` (стили LaTeX для журнала TMLR,
девять файлов) и спросил «что в нём». Ответ: «в проекте три файла — LICENSE, README.md,
fancyhdr.sty». Шести файлов агент не назвал, включая тот самый `tmlr.sty`, ради которого
пакет и существует.

Прогон `_analyze_repository` на том же архиве показал причину прямо:

    POST /graph/build → HTTP 500 (build_failed)
    graphify: build_failed — graph is empty — extraction produced no nodes.
                             Possible causes: all files skipped, binary-only corpus…
    ДЛИНА КАРТЫ: 0 символов
    НЕ УПОМЯНУТЫ В КАРТЕ: все девять файлов

graphify строит граф КОДА. LaTeX, вёрстка, данные, конфиги — не код, узлов нет, отчёта
нет; путь fail-open молча возвращал пустую строку, и о вложении у агента не оставалось НИ
ОДНОГО факта. Отвечать было нечем — он и перечислил состав по догадке.

⚠️ Перечень — не замена карте, а нижний слой под ней: он верен для любого архива и стоит
одного разбора оглавления.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from service.infrastructure.graphify import MAX_LISTED_ENTRIES, archive_listing

TMLR = [
    "tmlr-style-file-main/LICENSE",
    "tmlr-style-file-main/README.md",
    "tmlr-style-file-main/fancyhdr.sty",
    "tmlr-style-file-main/tmlr.sty",
    "tmlr-style-file-main/math_commands.tex",
    "tmlr-style-file-main/main.tex",
    "tmlr-style-file-main/main.bib",
    "tmlr-style-file-main/main.pdf",
    "tmlr-style-file-main/main-accepted.pdf",
]


def _zip(names, size=10) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, "x" * size)
    return buf.getvalue()


def test_every_file_of_the_measured_archive_is_named():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ АРХИВ: девять файлов, назван каждый."""
    listing = archive_listing(_zip(TMLR))

    for path in TMLR:
        assert path.split("/")[-1] in listing, f"{path} потерян — снова ответ по догадке"
    assert "(9)" in listing, "число файлов не названо — нечем сверить полноту"


def test_the_common_root_directory_is_stripped():
    """⚠️ Архивы с GitHub упакованы одним корневым каталогом. Он ничего не сообщает о
    проекте, а место в каждой строке занимает."""
    listing = archive_listing(_zip(TMLR))

    assert "tmlr-style-file-main/" not in listing


def test_a_flat_archive_keeps_its_paths():
    """🔴 ГРАНИЦА. Корень срезаем ТОЛЬКО когда он общий: иначе из `src/app.py` и
    `docs/app.py` вышли бы два одинаковых `app.py`, и агент читал бы не тот файл."""
    listing = archive_listing(_zip(["src/app.py", "docs/app.py"]))

    assert "src/app.py" in listing and "docs/app.py" in listing


def test_a_truncated_listing_says_so():
    """🔴 Молча укороченный перечень неотличим от полного — и агент уверенно скажет, что
    остальных файлов в проекте нет."""
    listing = archive_listing(_zip([f"repo/f{i}.txt" for i in range(MAX_LISTED_ENTRIES + 25)]))

    assert "перечень сокращён" in listing
    assert f"({MAX_LISTED_ENTRIES + 25})" in listing, "полное число файлов не названо"


@pytest.mark.parametrize(
    "payload", [b"", "не архив вовсе".encode(), b"PK\x03\x04" + "сломанный".encode()]
)
def test_a_broken_archive_yields_nothing(payload):
    """⚠️ Битый файл — пусто, а не исключение: перечень идёт на пути загрузки, и падать
    из-за него нельзя."""
    assert archive_listing(payload) == ""


def test_directories_are_not_listed_as_files():
    """⚠️ Записи-каталоги в перечень не попадают: они не файлы, и счёт бы врал."""
    listing = archive_listing(_zip(["repo/", "repo/a.py"]))

    assert "(1)" in listing


@pytest.mark.asyncio
async def test_the_listing_survives_a_failed_graph():
    """🔴 ТОЧКА ВЫЗОВА И ИМЕННО ЗАМЕРЕННЫЙ СБОЙ: graphify ответил 500. Прежде это давало
    пустую строку — вложение исчезало из контекста целиком."""
    from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase

    class _Dead:
        enabled = True

        async def build(self, *a, **kw):
            raise RuntimeError("graphify: build_failed — graph is empty")

    use_case = UploadFileUseCase.__new__(UploadFileUseCase)
    use_case.graph_client = _Dead()
    use_case.last_graph = None

    listing = await use_case._analyze_repository("tmlr-style-file-main.zip", _zip(TMLR))

    assert "tmlr.sty" in listing, "граф не построился — и о вложении снова ничего не известно"


@pytest.mark.asyncio
async def test_a_built_graph_carries_the_listing_too():
    """🔴 ГРАНИЦА С ДРУГОЙ СТОРОНЫ. Граф построился — перечень всё равно нужен: карта
    показывает связи РАЗОБРАННЫХ модулей и молчит о конфигах, данных и вёрстке, а вопрос
    «что в проекте» задают именно про состав."""
    from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase

    class _Alive:
        enabled = True

        async def build(self, *a, **kw):
            return {"report": "# Graph Report\n\nGod Nodes: app", "nodes": 12, "edges": 30}

    use_case = UploadFileUseCase.__new__(UploadFileUseCase)
    use_case.graph_client = _Alive()
    use_case.last_graph = None

    out = await use_case._analyze_repository("repo.zip", _zip(["repo/app.py", "repo/data.csv"]))

    assert "# Graph Report" in out, "карта потеряна"
    assert "data.csv" in out, "файл, который AST не понимает, снова невидим"
