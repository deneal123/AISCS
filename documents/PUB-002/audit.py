# /// script
# requires-python = ">=3.12"
# dependencies = ["PyMuPDF>=1.26,<2", "python-docx>=1.2,<2", "Pillow>=11,<13", "olefile>=0.47,<1"]
# ///
"""Validate source, journal layout, legacy Word roundtrip and both PDF builds."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from zipfile import ZipFile

import olefile
import pymupdf
from docx import Document
from PIL import Image

ROOT = Path(__file__).resolve().parent
text = (ROOT / "manuscript.md").read_text("utf-8")
evidence = json.loads((ROOT / "evidence.json").read_text("utf-8"))
meta = json.loads((ROOT / "metadata.json").read_text("utf-8"))
profile = json.loads((ROOT / "journal-profile.json").read_text("utf-8"))
errors = []
ordered = []
for group in re.findall(r"\[([\d, –-]+)\]", text):
    for part in group.split(","):
        ends = re.split(r"[–-]", part.strip())
        for number in range(int(ends[0]), int(ends[-1]) + 1):
            if number not in ordered:
                ordered.append(number)
if ordered != list(range(1, len(evidence["sources"]) + 1)):
    errors.append("Missing references or incorrect first-citation order")
if len({s["source_id"] for s in evidence["sources"]}) != len(ordered):
    errors.append("Duplicate sources")
if len(ordered) < 11 or any(
    not s.get("metadata_verified") or not s.get("authors_full") for s in evidence["sources"]
):
    errors.append("Incomplete bibliography")
reported_count = re.search(r"(?:Отобраны|отобраны) (\d+) (?:работ|источников)", text)
if not reported_count or int(reported_count[1]) != len(evidence["sources"]):
    errors.append("Source count in methods disagrees with bibliography")
if re.search(r"\b(?:S\d{3,}|PUB-\d+|G0_REVISE|STOP-UNSATURATED|TODO)\b", text):
    errors.append("Internal identifiers in manuscript")
# Scientific provenance: a search-page hit must not become article evidence.
review = evidence.get("judge_review", {})
if review.get("generation") != evidence["generation"]:
    errors.append("Scientific review generation mismatch")
reads = {s["source_id"]: s for s in review.get("source_checks", [])}
if not {s["source_id"] for s in evidence["sources"]} <= reads.keys():
    errors.append("Scientific citation coverage incomplete")
allowed_verdicts = {
    "подтверждено", "требует ограничения", "авторское предложение", "гипотеза", "неподтверждено"
}
for claim in review.get("claim_checks", []):
    if (
        claim.get("verdict") not in allowed_verdicts
        or not all(claim.get(k) for k in ("id", "section", "question", "reason", "correction"))
        or not set(claim["source_ids"]) <= reads.keys()
    ):
        errors.append("Incomplete scientific assertion decision")
for sid, read in reads.items():
    external = read.get("origin") == "external_article_local"
    if external and (
        not sid.startswith("EXT-PUB002-")
        or read.get("generation") is not None
        or not all(read.get("primary_locator", {}).get(k) for k in ("url", "locator"))
        or not read.get("text_sha256")
    ):
        errors.append("Invalid external-source origin: " + sid)
    if not external and read["generation"] != evidence["generation"]:
        errors.append("Source review generation mismatch: " + sid)
    if read.get("basis") == "previous_primary_verification":
        if read.get("fresh_full_text_read") is not False or not read.get("primary_locator"):
            errors.append("Previous verification incorrectly presented as fresh: " + sid)
    elif not read.get("fragment", {}).get("quote"):
        errors.append("Missing primary evidence fragment: " + sid)
    if read.get("excluded_registered_documents") and read.get("accepted_context_ids"):
        errors.append("Rejected citation-search page used as evidence: " + sid)
for query in review.get("query_protocol", []):
    if {q["role"] for q in query["queries"]} != {"support", "challenge"}:
        errors.append("Missing critical query")
    if any(q["generation"] != evidence["generation"] for q in query["queries"]):
        errors.append("Query generation mismatch")
if not review.get("post_revision_recheck") or any(
    q["errors"] or q["mode"] != "hybrid" or q["generation"] != evidence["generation"]
    for q in review.get("post_revision_recheck", [])
):
    errors.append("Post-revision retrieval check incomplete")

editorial = evidence.get("editorial_review", {})
if editorial.get("manuscript_sha256") != hashlib.sha256(
    (ROOT / "manuscript.md").read_bytes()
).hexdigest():
    errors.append("Editorial evidence is stale for the current manuscript")
if editorial.get("generation") != evidence["generation"]:
    errors.append("Editorial generation mismatch")
for query in editorial.get("queries", []) + editorial.get("source_filtered_queries", []):
    if query.get("mode") != "hybrid" or query.get("errors"):
        errors.append("Editorial retrieval used fallback or failed")
for context in editorial.get("primary_contexts", []):
    if (
        context.get("source_id") not in reads
        or context.get("generation") != evidence["generation"]
        or not context.get("primary_url")
        or not context.get("locators")
        or not context.get("excerpt")
        or context.get("include_unreviewed") is not False
        or not re.fullmatch(r"[a-f0-9]{64}", context.get("document_sha256", ""))
    ):
        errors.append("Incomplete editorial primary context")
for claim in editorial.get("claim_checks", []):
    if not set(claim["source_ids"]) <= reads.keys() or not claim.get("decision"):
        errors.append("Invalid editorial decision")
if not editorial.get("claim_checks") or not editorial.get("primary_contexts"):
    errors.append("Missing editorial decisions or primary contexts")

search_log = json.loads((ROOT / "literature-search.json").read_text("utf-8"))
screening = search_log["screening"]
by_query = {
    q["id"]: [r for r in screening if r["query_id"] == q["id"]]
    for q in search_log["queries"]
}
for query in search_log["queries"]:
    rows = by_query[query["id"]]
    if (
        len(rows) != query["viewed_count"]
        or len(rows) != min(20, query["total_reported"])
        or [r["rank"] for r in rows] != list(range(1, len(rows) + 1))
        or any(not r.get("reason") or not r.get("decision") for r in rows)
    ):
        errors.append("Incomplete ranked search screening: " + query["id"])
counts = search_log["counts"]
if (
    counts["returned_viewed"] != len(screening)
    or counts["exact_duplicates"] != sum(r["decision"] == "excluded_duplicate" for r in screening)
    or counts["supplement_included"] != sum(r["decision"] == "included" for r in screening)
    or counts["final_sources"] != len(evidence["sources"])
):
    errors.append("Search selection counts mismatch")
external_ids = {
    s["source_id"] for s in evidence["sources"] if s.get("origin") == "external_article_local"
}
selected_ids = {r["article_source_id"] for r in screening if r["decision"] == "included"}
foundational_ids = {r["source_id"] for r in search_log["foundational_additions"]}
if external_ids != selected_ids | foundational_ids:
    errors.append("External source has no documented selection route")
matrix = text.split("Таблица 3.", 1)[1].split("## Обсуждение", 1)[0]
matrix_numbers = [int(n) for n in re.findall(r"^\| \[(\d+)\];", matrix, re.M)]
if matrix_numbers != list(range(1, len(evidence["sources"]) + 1)):
    errors.append("Comparative matrix does not cover all sources")
if len(evidence["historical_selection"]["source_decisions"]) != 19:
    errors.append("Original source reappraisal incomplete")

abstract = text.split("## Аннотация\n\n", 1)[1].split("\n\n**", 1)[0]
extended = text.split("## Extended abstract\n\n", 1)[1].split("**Keywords:", 1)[0]
extended = re.sub(r"^### .*\n", "", extended)
if not 200 <= len(abstract.split()) <= 250 or len(extended.split()) < 350:
    errors.append("Abstract word limits")
if re.search(r"\[\d", abstract):
    errors.append("Citation in Russian abstract")
for label in ("Ключевые слова", "Keywords"):
    keywords = re.search(r"\*\*" + label + r":\*\* ([^\n]+)", text)[1].rstrip(".").split(",")
    if not 5 <= len(keywords) <= 10:
        errors.append("Keyword count")
docx_path = ROOT / "build/article.docx"
doc = Document(docx_path)
if doc.core_properties.author or doc.core_properties.last_modified_by:
    errors.append("Word reviewer metadata")
section = doc.sections[0]
for key, expected in profile["requirements"]["margins_mm"].items():
    if abs(getattr(section, key + "_margin").mm - expected) > 0.05:
        errors.append("Wrong Word margin: " + key)
normal = doc.styles["Normal"]
if (
    normal.font.name != "Times New Roman"
    or normal.font.size.pt != 12
    or normal.paragraph_format.line_spacing != 2
):
    errors.append("Word normal style")
all_paragraphs = list(doc.paragraphs) + [
    p for t in doc.tables for row in t.rows for c in row.cells for p in c.paragraphs
]
for p in all_paragraphs:
    if (
        p.text
        and (
            p.paragraph_format.line_spacing
            or p.style.paragraph_format.line_spacing
            or normal.paragraph_format.line_spacing
        )
        != 2
    ):
        errors.append("Non-double Word paragraph")
    for run in p.runs:
        if run.text and (run.font.name != "Times New Roman" or run.font.size.pt not in (12, 14)):
            errors.append("Unexpected Word run font")
with ZipFile(docx_path) as archive:
    xml = archive.read("word/document.xml").decode()
    if re.search(r"\b(?:REF|PAGEREF|NOTEREF)\b", xml):
        errors.append("Forbidden Word cross-reference field")
all_text = "\n".join(p.text for p in doc.paragraphs)
bibliography = {}
in_bibliography = False
for paragraph in doc.paragraphs:
    if paragraph.text == "Список литературы":
        in_bibliography = True
        continue
    if in_bibliography and paragraph.text == "Extended abstract":
        break
    match = re.match(r"^(\d+)\. ", paragraph.text) if in_bibliography else None
    if match:
        bibliography[int(match[1])] = paragraph.text
if set(bibliography) != set(range(1, len(evidence["sources"]) + 1)):
    errors.append("Incomplete rendered Word bibliography")
for number, source in enumerate(evidence["sources"], 1):
    description = bibliography.get(number, "")
    identifier = source.get("doi") or source["primary_url"]
    if identifier not in description:
        errors.append("Bibliographic DOI or versioned URL lost: " + source["source_id"])
    if re.search(r"[А-Яа-яЁё]", source["title"]):
        for field, label in (("volume", "Т."), ("issue", "№"), ("page", "С.")):
            if source.get(field):
                value = str(source[field]).replace("-", "–")
                if label + " " + value not in description:
                    errors.append("Wrong Russian bibliography label: " + field)
if any(s["source_id"] == "S741" for s in evidence["sources"]) and "Dhiman N." not in all_text:
    errors.append("Personal author surname/initial formatting lost")
in_extended = False
for paragraph in doc.paragraphs:
    in_extended = in_extended or paragraph.text == "Extended abstract"
    if in_extended or paragraph.text.startswith(("Table ", "Figure ")):
        for run in paragraph.runs:
            if run.text and run._r.xpath("./w:rPr/w:lang/@w:val") != ["en-GB"]:
                errors.append("Missing English proofing language")
table_numbers = re.findall(r"^Таблица (\d+)\.", text, re.M)
if len(table_numbers) != len(doc.tables) or len(doc.tables) != len(meta["table_captions_en"]):
    errors.append("Table/caption count")
for table in doc.tables:
    if not table.rows[0]._tr.xpath("./w:trPr/w:tblHeader"):
        errors.append("Missing repeatable Word table header")
    if any(
        p.paragraph_format.keep_with_next
        for row in table.rows[1:]
        for cell in row.cells
        for p in cell.paragraphs
    ):
        errors.append("Word body rows chained across pages")
tex = (ROOT / "main.tex").read_text("utf-8")
if tex.count(r"\begin{longtable}") != len(doc.tables) or tex.count(r"\endhead") != len(doc.tables):
    errors.append("Missing multipage LaTeX tables or repeated headers")
for number in table_numbers:
    if len(re.findall(rf"^Table {number}\.", all_text, re.M)) != 1:
        errors.append("Missing bilingual table caption")
if re.search(r"<\/?i>|&amp;|&lt;|&gt;", all_text):
    errors.append("Unprocessed bibliography markup")
if "Yu S.-C." not in all_text or "Evoke Study Group" not in all_text:
    errors.append("Hyphenated or collective authors lost")
if re.search(r"\.\.|,\s*,|https\\://", all_text):
    errors.append("Broken bibliography punctuation or URL")
for number, image_match in enumerate(re.finditer(r"!\[[^]]*\]\([^)]+\)", text), 1):
    preceding = re.split(r"\n\s*\n", text[:image_match.start()].rstrip())[-1]
    if not re.search(rf"\bрис(?:унок|унке|унки|унках|\.)\s*{number}\b", preceding, re.I):
        errors.append("Figure not introduced in the immediately preceding paragraph")
for image_index, image_path in enumerate(re.findall(r"!\[[^]]*\]\(([^)]+)\)", text)):
    with Image.open(ROOT / image_path) as image:
        if min(image.info.get("dpi", (0, 0))) < 299:
            errors.append("Figure resolution")
        shape = doc.inline_shapes[image_index]
        density = min(image.width / shape.width.inches, image.height / shape.height.inches)
        if density < profile["requirements"]["figure_dpi_minimum"]:
            errors.append("Figure effective density below 300 dpi at Word placement")
roundtrip = json.loads((ROOT / "build/doc-roundtrip.json").read_text("utf-8"))
for name in ("article.docx", "article.doc", "article.pdf", "article-doc.pdf"):
    current_sha256 = hashlib.sha256((ROOT / "build" / name).read_bytes()).hexdigest()
    if roundtrip.get("sha256", {}).get(name) != current_sha256:
        errors.append("Stale Word export or roundtrip report: " + name)
if (
    not all(roundtrip[key] for key in ("same_text", "same_tables", "same_pictures"))
    or roundtrip["doc_pages"] != roundtrip["docx_pages"]
):
    errors.append("Legacy Word roundtrip mismatch")
if (
    roundtrip["normal_font"] != "Times New Roman"
    or roundtrip["normal_size"] != 12
    or roundtrip["normal_line_spacing_rule"] != 2
):
    errors.append("Legacy Word styles")
for key, mm in profile["requirements"]["margins_mm"].items():
    if abs(roundtrip["margins_points"][key] * 25.4 / 72 - mm) > 0.1:
        errors.append("Legacy Word margin")
with olefile.OleFileIO(ROOT / "build/article.doc") as legacy:
    properties = legacy.getproperties("\x05SummaryInformation")
    if properties.get(4) or properties.get(8):
        errors.append("Legacy reviewer author metadata")
pdf_reports = {}
pdf_texts = {}


def caption_text(value):
    """Compare content without line breaks, punctuation or math-index markup."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value)).casefold()


figure_caption_ru = re.search(r"^Рисунок 1\..+$", text, re.M)[0]
for relative in ("build/article.pdf", "build/article-doc.pdf", "build/latex/article-latex.pdf"):
    pdf = pymupdf.open(ROOT / relative)
    fonts, outside, unembedded = set(), [], set()
    for i, page in enumerate(pdf):
        if not page.get_text().strip():
            errors.append(relative + ": blank page")
        for font in page.get_fonts():
            if not font[0] or not pdf.extract_font(font[0])[3]:
                unembedded.add(font[3])
        # All printed text must stay within the prescribed horizontal margins.
        left, right = 30 * 72 / 25.4, page.rect.width - 10 * 72 / 25.4
        if relative.endswith("article-latex.pdf"):
            paths = [drawing["rect"] for drawing in page.get_drawings()]
            full_rules = [
                box for box in paths if box.width > 0.95 * (right - left) and box.height < 1
            ]
            table_sides = [box for box in paths if box.width < 1 and box.height > 2]
            if full_rules and not table_sides:
                errors.append(relative + f": orphan table border on page {i + 1}")
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    fonts.add(span["font"])
                    for char in span["chars"]:
                        if not char["c"].strip():
                            continue
                        bbox = pymupdf.Rect(char["bbox"])
                        if (
                            not page.rect.contains(bbox)
                            or bbox.x0 < left - 2
                            or bbox.x1 > right + 2
                        ):
                            outside.append({"page": i + 1, "text": char["c"]})
    if outside:
        errors.append(relative + ": text outside margins")
    if unembedded:
        errors.append(relative + ": fonts not embedded")
    if len(pdf) > 20:
        errors.append(relative + ": page limit")
    caption_pages = [
        i for i, page in enumerate(pdf)
        if caption_text(figure_caption_ru) in caption_text(page.get_text())
        and caption_text(meta["figure_caption_en"]) in caption_text(page.get_text())
    ]
    if len(caption_pages) != 1:
        errors.append(relative + ": figure captions split across pages or incomplete")
    elif not relative.endswith("article-latex.pdf") and not pdf[caption_pages[0]].get_image_info():
        errors.append(relative + ": figure separated from bilingual captions")
    if any(
        "TimesNewRoman" not in f
        and not (relative.endswith("article-latex.pdf") and "TeXGyreTermesMath" in f)
        for f in fonts
    ) or pdf.metadata.get("author"):
        errors.append(relative + ": font or author metadata")
    pdf_texts[relative] = re.sub(r"\s+", "", "".join(p.get_text() for p in pdf))
    if re.search(r"[A-Za-zα-ω]_[FHijkα-ω]", pdf_texts[relative]):
        errors.append(relative + ": mathematical index rendered as literal markup")
    pdf_reports[relative] = {
        "pages": len(pdf), "fonts": sorted(fonts), "outside": outside,
        "unembedded_fonts": sorted(unembedded),
    }
if pdf_texts["build/article.pdf"] != pdf_texts["build/article-doc.pdf"]:
    errors.append("DOC PDF text differs from DOCX PDF")
log = (ROOT / "build/latex/article-latex.log").read_text("utf-8", errors="replace")
if "Overfull" in log or "undefined references" in log:
    errors.append("LaTeX overflow or undefined reference")
indexed = profile["bibliography_indexing_check"]
source_ids = {s["source_id"] for s in evidence["sources"]}
indexed_ids = {
    sid for item in indexed["publisher_declarations"] for sid in item["refs"]
} & source_ids
if len(indexed_ids) / len(source_ids) < 0.3:
    errors.append("Indexed foreign reference share below 30%")
paths = [
    ROOT / n
    for n in (
        "README.md",
        "audit.md",
        "manuscript.md",
        "evidence.json",
        "literature-search.json",
        "metadata.json",
        "journal-profile.json",
        "build.py",
        "audit.py",
        "main.tex",
        "figures/observation-scheme.png",
        "figures/observation-scheme.pdf",
        "figures/observation-scheme.svg",
        "figures/observation-scheme.tex",
        "figures/observation-diagram.tex",
        "build/article.docx",
        "build/article.doc",
        "build/article.pdf",
        "build/article-doc.pdf",
        "build/latex/article-latex.pdf",
    )
]
report = {
    "ok": not errors,
    "errors": sorted(set(errors)),
    "pages": pdf_reports,
    "references": len(ordered),
    "verified_indexed_references": len(indexed_ids),
    "first_citation_order": ordered,
    "russian_abstract_words": len(abstract.split()),
    "english_extended_abstract_words": len(extended.split()),
    "tables": len(doc.tables),
    "figures": len(doc.inline_shapes),
    "roundtrip": roundtrip,
    "sha256": {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
    },
}
(ROOT / "build/audit-report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(
    json.dumps(
        {k: v for k, v in report.items() if k not in ("sha256", "roundtrip", "pages")},
        ensure_ascii=False,
    )
)
print(json.dumps({p: v["pages"] for p, v in pdf_reports.items()}, ensure_ascii=False))
raise SystemExit(bool(errors))
