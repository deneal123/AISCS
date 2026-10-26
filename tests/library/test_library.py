"""Book library: format normalizers, exact locators, isolation from the evidence index."""

import hashlib
import json
from pathlib import Path

import pytest

from service.common.errors import DataError
from service.indexing.embedding import Embedder
from service.indexing.settings import KnowledgeSettings
from service.library import formats
from service.library.catalog import citation, load_catalog, validate_catalog
from service.library.engine import LibraryEngine
from service.library.formats import extract
from service.library.prepare import read_documents
from service.library.projection import chunk_book

ROOT = Path(__file__).parents[2]

FB2 = """<?xml version="1.0" encoding="windows-1251"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:l="http://www.w3.org/1999/xlink"><description><title-info>
<author><first-name>Иван</first-name><last-name>Петров</last-name></author>
<book-title>Как писать диссертацию</book-title><lang>ru</lang></title-info>
<publish-info><publisher>Наука</publisher><year>2001</year></publish-info></description>
<body><title><p>Как писать диссертацию</p></title>
<section><title><p>Глава 1. Выбор темы</p></title>
<p>Тема должна быть актуальной<a l:href="#n_1" type="note">[1]</a>.</p>
<section><title><p>Научная новизна</p></title><p>Научная новизна формулируется явно и
 проверяемо.</p></section></section>
{tail}
</body>
<body name="notes"><section id="n_1"><title><p>1</p></title><p>Сноска о теме.</p></section></body>
<binary id="cover.jpg" content-type="image/jpeg">QUFBQQ==</binary>
</FictionBook>"""
FRAGMENT_TAIL = (
    "<section><title><p>Конец ознакомительного фрагмента.</p></title>"
    "<p>Купите полную версию.</p></section>"
)

MD = """Книга. Практическое пособие

**СОДЕРЖАНИЕ:**

**Предисловие**

**Глава 1\\. Выбор темы**

  Выбор руководителя

  Планирование работы

ПРЕДИСЛОВИЕ

Текст предисловия \\- важный.

Выбор руководителя

Руководитель [сайт](http://example.org) помогает выбрать тему.

| Тема | Раздел |
| ----- | :---: |
| А | Б |

**Планирование работы**

План работы над диссертацией.

КОНЕЦ
"""


def _djvu(pages: list[list[list[str]]]) -> bytes:
    objects = []
    for paragraphs in pages:
        body = "".join(
            "<PARAGRAPH>"
            + "".join(f"<LINE><WORD>{line}</WORD></LINE>" for line in lines)
            + "</PARAGRAPH>"
            for lines in paragraphs
        )
        objects.append(f"<OBJECT><HIDDENTEXT><REGION>{body}</REGION></HIDDENTEXT></OBJECT>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE DjVuXML>\n<DjVuXML><BODY>'
        + "".join(objects)
        + "</BODY></DjVuXML>"
    ).encode()


def test_fb2_structure_notes_encoding_and_fragment():
    full = extract("fb2", FB2.format(tail="").encode("cp1251"))
    assert [s["title"] for s in full["sections"]] == [
        "Глава 1. Выбор темы",
        "Научная новизна",
        "Примечания",
    ]
    assert full["sections"][1]["path"] == ["Глава 1. Выбор темы", "Научная новизна"]
    assert "[1] Сноска о теме." in full["text"]
    assert "QUFBQQ" not in full["text"] and not full["fragment"]
    assert full["metadata"]["authors"] == ["Петров Иван"]
    assert full["metadata"]["year"] == "2001"
    preview = extract("fb2", FB2.format(tail=FRAGMENT_TAIL).encode("cp1251"))
    assert preview["fragment"] and "Купите" not in preview["text"]
    for section in full["sections"]:
        if section["in_text"]:
            assert full["text"][section["char_start"] :].startswith(section["title"])


def test_xml_entity_declarations_are_refused():
    payload = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><FictionBook/>'
    with pytest.raises(DataError, match="entity"):
        extract("fb2", payload)


def test_doc_pages_footnotes_and_heading_levels(monkeypatch):
    text = (
        "ПРЕДИСЛОВИЕ\n"
        "    Первый абзац страницы пять. [5]\n"
        "    Нам хотелось бы, чтобы по-[6]-чаще думали [2] о главном.\n"
        "Глава I\n"
        "ЗАЧЕМ ЗАНИМАТЬСЯ НАУКОЙ?\n"
        "ШИФРЫ ВНУТРИ НАС\n"
        "    Текст главы. [7]\n"
        "Тезисы\n"
        "    Про тезисы.[pic]\n"
        "-----------------------\n"
        "[1] Сноска.\n"
    )
    monkeypatch.setattr(formats.doc, "antiword_text", lambda data: (text, "antiword test"))
    result = extract("doc", b"stub")
    assert [(s["level"], s["title"]) for s in result["sections"]] == [
        (1, "ПРЕДИСЛОВИЕ"),
        (1, "Глава I. ЗАЧЕМ ЗАНИМАТЬСЯ НАУКОЙ? ШИФРЫ ВНУТРИ НАС"),
        (3, "Тезисы"),
        (1, "Примечания"),
    ]
    body = result["text"]
    assert "почаще думали [2]" in body and "[5]" not in body and "[pic]" not in body
    assert [p["page"] for p in result["page_starts"]] == ["5", "6", "7", "8"]
    seventh = next(p for p in result["page_starts"] if p["page"] == "7")
    assert body[seventh["char"] :].startswith("чаще")
    assert result["tool"] == "antiword test"


def test_markdown_toc_restores_chapters_without_inserting_text():
    result = extract("md", MD.encode())
    sections = [(s["level"], s["title"], s["in_text"]) for s in result["sections"]]
    assert sections == [
        (1, "Предисловие", True),
        (1, "Глава 1. Выбор темы", False),
        (2, "Выбор руководителя", True),
        (2, "Планирование работы", True),
    ]
    text = result["text"]
    assert "Глава 1" not in text and "СОДЕРЖАНИЕ" not in text and "КОНЕЦ" not in text
    assert "Текст предисловия - важный." in text
    assert "Руководитель сайт помогает" in text and "Тема | Раздел" in text


def test_djvu_hyphenation_page_continuation_and_toc():
    pages = [
        [["ОБЛОЖКА"]],
        [
            ["ЦИТИРОВАНИЕ"],
            ["Жанр научно-популярного изложения прост."],
            ["Цитата нужна для сред-", "ства доказательства и научно-"],
            ["1"],
        ],
        [["популярного изложения."], ["2"]],
    ]
    toc = [{"level": 1, "title": "Цитирование", "page": 1}]
    result = extract("djvu_xml", _djvu(pages), options={"toc": toc})
    text = result["text"]
    assert "средства доказательства и научно-популярного изложения." in text
    assert "\n\n1\n\n" not in text and not text.endswith("2")
    assert [p["page"] for p in result["page_starts"]] == ["0", "1", "2"]
    section = result["sections"][0]
    assert section["title"] == "Цитирование" and not section["in_text"]
    assert text[section["char_start"] :].startswith("ЦИТИРОВАНИЕ")


def test_word_html_headings_skip_head_and_limit_levels():
    html = (
        "11:41 18.10.2007<html><head><title>Иванов И.И. МЕТОДОЛОГИЯ. – М., 2007</title>"
        "<style>p {margin:0}</style></head><body><h1>Глава 1. ОСНОВАНИЯ</h1>"
        "<p class=MsoNormal>Первый&nbsp;абзац\nтекста.</p><h2>1.1. Раздел</h2><p>Второй.</p>"
        "<h5>ФАЗЫ</h5><p>Схема.</p></body></html>"
    ).encode("cp1251")
    result = extract("html", html, options={"max_heading_level": 2})
    assert [s["title"] for s in result["sections"]] == ["Глава 1. ОСНОВАНИЯ", "1.1. Раздел"]
    assert "Первый абзац текста." in result["text"] and "ФАЗЫ" in result["text"]
    assert "11:41" not in result["text"] and "margin" not in result["text"]
    assert result["metadata"]["title"].startswith("Иванов")


def test_inline_roman_decimal_headings_ignore_cross_references():
    body = (
        "<section><title><p>III. Сбор материала</p></title><p>III. Сбор материала "
        "III. 1. Доступность источников III. 1. 1.Что является источником? Текст. "
        "См. раздел II. 6. 1 и III.2.1, далее. III. 1. 2. Первоисточники Текст.</p></section>"
    )
    payload = FB2.format(tail="").replace(
        "<section><title><p>Глава 1.", body + "<section><title><p>Глава 1.", 1
    )
    result = extract("fb2", payload.encode("cp1251"), options={"inline_headings": "roman_decimal"})
    titles = [s["title"].split(" ")[0] for s in result["sections"]][:4]
    assert titles == ["III.", "III.1.", "III.1.1.", "III.1.2."]
    assert "См. раздел II. 6. 1 и III.2.1, далее." in result["text"]


def test_pdf_spreads_dedupe_reorder_toc_and_footers(monkeypatch):
    sheets = [
        "ОБЛОЖКА\n1 / 3",
        "10 11\nСпособы представления\nпрезентаций\nПервая строка абзаца, кото-\nрый продолжается.\n"
        "Короткая.\nPowered by TCPDF (www.tcpdf.org)\n2 / 3",
        "10 11\nСпособы представления\nпрезентаций\nПервая строка абзаца, кото-\nрый продолжается.\n"
        "Короткая.\n3 / 3",
        "12 13\nабзац с прошлого листа и ауди тории.\n1 / 3",
        "8 9\nВведение\nТекст введения про аудитории.\n2 / 3",
    ]
    monkeypatch.setattr(formats.pdf, "pdf_page_texts", lambda data: sheets)
    toc = [
        {"level": 1, "title": "Введение", "page": 9},
        {"level": 2, "title": "Способы представления презентаций", "page": 10},
    ]
    options = {"pdf_layout": "spreads", "toc": toc, "join_split_words": True}
    result = extract("pdf", b"stub", options=options)
    assert [p["page"] for p in result["page_starts"]] == ["1", "8–9", "10–11", "12–13"]
    assert [(s["title"], s["in_text"]) for s in result["sections"]] == [
        ("Введение", True),
        ("Способы представления презентаций", True),
    ]
    text = result["text"]
    assert "который продолжается." in text and "TCPDF" not in text and "/ 3" not in text
    assert "аудитории." in text and "ауди тории" not in text
    assert text.count("Первая строка") == 1


def test_pdf_running_headers_watermark_and_chapter_openings(monkeypatch):
    pages = [
        "ОГЛАВЛЕНИЕ\nГлава 1 ..... 15\nwatermark.example",
        "14 Название книги\nТекст страницы чт о-то. Конец\nабзаца.\nwatermark.example",
        "Глава 1\nАргументация\nНачало главы и продолжение аргумен -\nтации.\nwatermark.example",
        "Глава 1. Аргументация 16\nСтраница с колонтитулом и что-то ещё. watermark.example",
    ]
    monkeypatch.setattr(formats.pdf, "pdf_page_texts", lambda data: pages)
    toc = [{"level": 1, "title": "Глава 1. Аргументация", "page": 15}]
    result = extract("pdf", b"stub", options={"toc": toc, "join_split_words": True})
    assert [p["page"] for p in result["page_starts"]] == ["13", "14", "15", "16"]
    assert result["sections"][0]["title"] == "Глава 1. Аргументация"
    assert result["sections"][0]["in_text"]
    text = result["text"]
    assert "watermark" not in text and "Название книги" not in text
    assert "аргументации." in text and "что-то" in text


def _book(book_id, fmt, path, **extra):
    return {
        "book_id": book_id,
        "title": "Книга " + book_id,
        "authors": ["Автор А. А."],
        "translators": [],
        "language": "ru",
        "year": "2001",
        "publisher": "Наука",
        "city": "Москва",
        "isbn": ["5-00-000000-0"],
        "format": fmt,
        "completeness": "full_text",
        "origin": {"kind": "file", "file": path.name},
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "options": {},
        "field_resolution": {},
        **extra,
    }


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.delenv("RESEARCH_LIBRARY_DIR", raising=False)
    books = tmp_path / "books"
    books.mkdir()
    fb2 = books / "a.fb2"
    fb2.write_bytes(FB2.format(tail="").encode("cp1251"))
    md = books / "b.md"
    md.write_text(MD, encoding="utf-8")
    project = tmp_path / "project"
    (project / "knowledge" / "library").mkdir(parents=True)
    catalog = {
        "schema_version": "1.0.0",
        "source_dir": "../books",
        "books": [_book("B001", "fb2", fb2), _book("B002", "md", md)],
    }
    (project / "knowledge" / "library" / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False), encoding="utf-8"
    )
    return LibraryEngine(project, KnowledgeSettings(tmp_path / "state"))


def test_offline_lifecycle_search_passage_and_isolation(library, tmp_path):
    assert library.state == (tmp_path / "state" / "library").resolve()
    prepared = library.prepare()
    assert prepared["ok"] and prepared["books"] == 2
    assert library.status()["mode"] == "prepared_lexical"
    candidate = library.build(offline=True)
    with pytest.raises(DataError, match="must be ready"):
        library.publish(candidate["generation"])
    library.publish(candidate["generation"], allow_offline=True)
    assert library.status()["mode"] == "published_offline"
    result = library.search("научная новизна")
    assert result["mode"] == "library_lexical_fallback"
    assert "dense_index_not_ready" in result["errors"]
    top = result["items"][0]
    # Short sections are packed together; the path names the section where a chunk starts.
    assert top["book_id"] == "B001" and "Научная новизна формулируется" in top["text"]
    assert top["section_path"] == ["Глава 1. Выбор темы"]
    passage = library.passage(top["chunk_id"], context=1)
    assert top["text"] in passage["context"]["text"]
    assert library.check()["ok"]
    books = {b["book_id"]: b for b in library.books()["books"]}
    assert books["B002"]["chunks"] >= 1 and books["B001"]["citation"].startswith("Автор")
    assert library.search("тему", book_ids=["B002"])["items"][0]["book_id"] == "B002"
    with pytest.raises(DataError, match="unknown book_ids"):
        library.search("тему", book_ids=["B999"])
    # The evidence index pointer and corpus live one level up and are never created here.
    assert not (tmp_path / "state" / "active.json").exists()
    assert not (tmp_path / "state" / "corpus").exists()


def test_display_citation_and_spread_pages_keep_index_inputs(library):
    library.prepare()
    projection, _, _ = library._read()
    book = next(n for n in projection["nodes"] if n["id"] == "book:B001")
    # The frozen index form stays in the projection, so published generations do not change.
    assert book["metadata"]["citation"] == "Автор А. А.. Книга B001. Москва, Наука, 2001"
    item = library.search("научная новизна")["items"][0]
    assert item["citation"] == "Автор А. А. Книга B001. Москва, Наука, 2001"
    assert citation({"authors": ["Эко Умберто"], "title": "Как?", "year": "2001"}) == (
        "Эко Умберто. Как? 2001"
    )
    pages = LibraryEngine._pages
    assert pages({"page_start": "98–99", "page_end": "100–101"}) == "98–101"
    assert pages({"page_start": "24–25", "page_end": "24–25"}) == "24–25"
    assert pages({"page_start": "27", "page_end": "28"}) == "27–28"
    assert pages({"page_start": "7", "page_end": "7"}) == "7"
    assert pages({"page_start": None, "page_end": None}) is None


def test_changed_original_is_rejected(library, tmp_path):
    (tmp_path / "books" / "b.md").write_text(MD + "\nИзменение.\n", encoding="utf-8")
    result = library.prepare()
    assert not result["ok"] and "B002" in result["errors"]


def test_chunks_resolve_exactly_and_respect_sections(library):
    library.prepare()
    for document in read_documents(library.state):
        for chunk in chunk_book(document):
            assert document["text"][chunk["char_start"] : chunk["char_end"]] == chunk["text"]
            assert len(chunk["text"]) <= 2800 * 2


def test_live_build_uses_library_label_and_collection(library, monkeypatch):
    import service.library.engine as module

    library.prepare()
    created, points = {}, set()

    class Graph:
        nodes, edges = [], []

        def __init__(self, settings, *, label="Knowledge", analyzer=""):
            created.update(label=label, analyzer=analyzer)
            self.label = label

        def import_graph(self, generation, projection):
            Graph.nodes = [n["id"] for n in projection["nodes"]]
            Graph.edges = [e["id"] for e in projection["edges"]]

        def counts(self, generation):
            return {"nodes": len(Graph.nodes), "edges": len(Graph.edges)}

        def query(self, statement, **params):
            assert ":Library " in statement
            ids = Graph.edges if "r.id" in statement else Graph.nodes
            return [{"id": i} for i in ids]

        def search(self, generation, query, limit, *, allowed=None):
            return [n for n in Graph.nodes if "::" in n][:2]

    class Vector:
        def __init__(self, settings):
            pass

        def ensure(self, collection):
            created["collection"] = collection

        def upsert_many(self, collection, rows):
            points.update(key for key, _ in rows)

        def count(self, collection):
            return len(points)

        def search(self, collection, vector, limit, *, allowed=None):
            return sorted(points)[-2:]

        def request(self, method, route, **kwargs):
            if method == "GET":
                return {"result": {"config": {"params": {"vectors": {"size": 2560}}}}}
            payload = [{"payload": {"node_id": key}} for key in points]
            return {"result": {"points": payload, "next_page_offset": None}}

    monkeypatch.setattr(module, "GraphStore", Graph)
    monkeypatch.setattr(module, "VectorStore", Vector)
    monkeypatch.setattr("service.indexing.verification.VectorStore", Vector)
    monkeypatch.setattr(Embedder, "embed_many", lambda self, inputs: [[1.0] * 2560] * len(inputs))
    monkeypatch.setattr(Embedder, "embed", lambda self, text, query=False: [1.0] * 2560)
    info = library.build()
    assert info["ready"] and info["collection"].startswith("aspa_library_g_")
    assert created["label"] == "Library" and created["analyzer"] == "russian"
    library.publish(info["generation"])
    result = library.search("тема диссертации")
    assert result["mode"] == "hybrid" and not result["errors"] and result["items"]
    assert library.check()["backend_ids_checked"]


def test_catalog_validation_requires_explicit_resolution(tmp_path):
    path = tmp_path / "x.fb2"
    path.write_bytes(b"x")
    book = _book("B001", "fb2", path, year=None)
    errors = validate_catalog({"schema_version": "1.0.0", "books": [book, dict(book)]})
    assert any("year needs field_resolution" in e for e in errors)
    assert any("unique B###" in e for e in errors)


def test_repository_catalog_and_benchmark_are_consistent():
    catalog = load_catalog(ROOT)
    ids = {b["book_id"] for b in catalog["books"]}
    assert len(ids) == len(catalog["books"]) == 10
    suite = json.loads((ROOT / "knowledge" / "library" / "evaluation.json").read_text("utf-8"))
    for case in suite["cases"]:
        assert set(case["expected_books"]) <= ids
        assert any("Ѐ" <= ch <= "ӿ" for ch in case["query"])
