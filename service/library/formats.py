"""Book normalizers: FB2, Word 97 via antiword, Markdown, DjVu XML, Word HTML and PDF.

Each extractor yields ordered blocks; :func:`assemble` turns them into one text with
exact heading and page offsets, so every chunk locator resolves in the normalized book.
Blocks are ``("heading", level, title, in_text)``, ``("para", text)``, ``("cont", text)``
(the same paragraph continued after a page break), ``("join", text)`` (a word split by
a page break) and ``("page", label)`` (the following text starts that printed page).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..core import DataError
from ..knowledge.corpus import decode_bytes

PARSER_VERSION = "library-normalizer-v1"
FORMATS = ("fb2", "doc", "md", "djvu_xml", "html", "pdf")
FRAGMENT_MARK = "конец ознакомительного фрагмента"
TOC_TITLES = frozenset({"содержание", "оглавление"})
NOTES_TITLE = "Примечания"
FB2 = "{http://www.gribuser.ru/xml/fictionbook/2.0}"
ANTIWORD_CANDIDATES = (Path(r"C:\Program Files\Git\mingw64\bin\antiword.exe"),)
TEXT_BLOCKS = frozenset({"para", "cont", "join"})

_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[^\W\d_]+")
_INNER_HYPHEN_RE = re.compile(r"\b([^\W\d_]+)-([^\W\d_]+)\b")
_COMPOUND_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)+")


def clean(text: str) -> str:
    """Single-line NFC text without soft hyphens or repeated whitespace."""
    text = unicodedata.normalize("NFC", text).replace("\u00ad", "").replace("\ufeff", "")
    return _SPACE_RE.sub(" ", text).strip()


def title_key(text: str) -> str:
    """Letters and digits only, case-folded; tolerant to spacing, quotes and ё."""
    return "".join(ch for ch in text.casefold().replace("ё", "е") if ch.isalnum())


def _vocabulary(blocks: list[tuple]) -> set[str]:
    words: set[str] = set()
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            words.update(w.casefold() for w in _WORD_RE.findall(block[1]))
    return words


def join_inner_hyphens(blocks: list[tuple]) -> list[tuple]:
    """Join typesetting hyphens such as ``ка-федрой`` only when the joined word occurs
    elsewhere in the same book; genuine compounds (``из-за``, ``научно-популярный``) stay."""
    words = _vocabulary(blocks)

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        if right[:1].islower() and (left + right).casefold() in words:
            return left + right
        return match.group(0)

    joined = []
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            block = (block[0], _INNER_HYPHEN_RE.sub(repl, block[1]))
        joined.append(block)
    return joined


# The right fragment is a lookahead so overlapping pairs ("и ауди тории") are all seen.
_SPLIT_WORD_RE = re.compile(r"\b([^\W\d_]+) (?=([^\W\d_]+)\b)")


def join_split_words(blocks: list[tuple]) -> list[tuple]:
    """Repair OCR spaces inside words (``дей ствительно``, ``чт о``).

    Two fragments are joined only when the joined word occurs whole in the same book
    and one fragment never occurs on its own outside such pairs; ordinary phrases
    (``во время``, ``так и``) consist of free-standing words and stay apart."""
    texts = [block[1] for block in blocks if block[0] in TEXT_BLOCKS]
    counts = Counter(w.casefold() for text in texts for w in _WORD_RE.findall(text))
    inside: Counter = Counter()
    for text in texts:
        for match in _SPLIT_WORD_RE.finditer(text):
            left, right = match.group(1).casefold(), match.group(2).casefold()
            if match.group(2)[:1].islower() and counts.get(left + right, 0) > 0:
                inside[left] += 1
                inside[right] += 1

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        a, b = left.casefold(), right.casefold()
        bound = counts[a] <= inside[a] or counts[b] <= inside[b]
        if right[:1].islower() and counts.get(a + b, 0) > 0 and bound:
            return left  # drop the space; the right fragment follows untouched
        return match.group(0)

    repaired = []
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            block = (block[0], _SPLIT_WORD_RE.sub(repl, block[1]))
        repaired.append(block)
    return repaired


def exclude_sections(blocks: list[tuple], prefixes: list[str]) -> tuple[list[tuple], list[str]]:
    """Drop a printed table of contents and catalog-listed sections with their children."""
    keys = [title_key(p) for p in prefixes]
    kept: list[tuple] = []
    removed: list[str] = []
    skip_level: int | None = None
    for block in blocks:
        if block[0] == "heading":
            level, title = block[1], block[2]
            if skip_level is not None and level <= skip_level:
                skip_level = None
            key = title_key(title)
            if skip_level is None and (
                (level == 1 and key in TOC_TITLES) or any(key.startswith(k) for k in keys if k)
            ):
                skip_level = level
                removed.append(clean(title))
                continue
        if skip_level is None or block[0] == "page":
            kept.append(block)
    return kept, removed


def assemble(blocks: list[tuple]) -> dict[str, Any]:
    """Concatenate blocks with blank-line paragraph breaks and exact offsets."""
    parts: list[str] = []
    length = 0
    sections: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    pending_pages: list[str] = []
    pending_sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []

    def emit(separator: str, text: str) -> None:
        nonlocal length
        if parts:
            parts.append(separator)
            length += len(separator)
        for label in pending_pages:
            if pages and pages[-1]["char"] == length:
                pages[-1] = {"page": label, "char": length}
            elif not pages or pages[-1]["page"] != label:
                pages.append({"page": label, "char": length})
        pending_pages.clear()
        for section in pending_sections:
            section["char_start"] = length
            sections.append(section)
        pending_sections.clear()
        parts.append(text)
        length += len(text)

    for block in blocks:
        kind = block[0]
        if kind == "page":
            pending_pages.append(str(block[1]))
            continue
        if kind == "heading":
            _, level, title, in_text = block
            title = clean(title)
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            pending_sections.append(
                {
                    "level": level,
                    "title": title,
                    "path": [t for _, t in stack],
                    "in_text": bool(in_text),
                }
            )
            if in_text:
                emit("\n\n", title)
            continue
        text = clean(block[1])
        if text:
            emit({"cont": " ", "join": ""}.get(kind, "\n\n"), text)
    text = "".join(parts)
    for position, section in enumerate(sections):
        section["char_end"] = (
            sections[position + 1]["char_start"] if position + 1 < len(sections) else len(text)
        )
    return {"text": text, "sections": sections, "page_starts": pages}


# ---------------------------------------------------------------------------
# FB2
# ---------------------------------------------------------------------------


def safe_xml(data: bytes) -> ET.Element:
    """Parse local XML books, refusing entity declarations (no expansion attacks)."""
    if b"<!ENTITY" in data or re.search(rb"<!DOCTYPE[^>]*\[", data[:65536]):
        raise DataError("XML entity declarations are refused")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DataError("malformed XML book: " + str(exc)) from exc


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(element: ET.Element | None) -> str:
    return clean("".join(element.itertext())) if element is not None else ""


def _title(element: ET.Element | None) -> str:
    if element is None:
        return ""
    lines = [_text(child) for child in element if _local(child.tag) == "p"]
    return clean(" ".join(line for line in lines if line)) or _text(element)


def fb2_metadata(root: ET.Element) -> dict[str, Any]:
    description = root.find(FB2 + "description")
    info = description.find(FB2 + "title-info") if description is not None else None
    publish = description.find(FB2 + "publish-info") if description is not None else None
    if info is None:
        return {}

    def person(element: ET.Element) -> str:
        names = [
            clean(element.findtext(FB2 + k) or "")
            for k in ("last-name", "first-name", "middle-name")
        ]
        return " ".join(n for n in names if n) or clean(element.findtext(FB2 + "nickname") or "")

    def field(element: ET.Element | None, name: str) -> str:
        return clean(element.findtext(FB2 + name) or "") if element is not None else ""

    metadata = {
        "title": field(info, "book-title"),
        "authors": [p for a in info.findall(FB2 + "author") if (p := person(a))],
        "translators": [p for a in info.findall(FB2 + "translator") if (p := person(a))],
        "language": field(info, "lang"),
        "source_language": field(info, "src-lang"),
        "genres": [g for e in info.findall(FB2 + "genre") if (g := clean(e.text or ""))],
        "annotation": _text(info.find(FB2 + "annotation")),
        "publisher": field(publish, "publisher"),
        "city": field(publish, "city"),
        "year": field(publish, "year"),
        "isbn": field(publish, "isbn"),
    }
    return {k: v for k, v in metadata.items() if v}


class _FragmentEnd(Exception):
    """A retailer preview ends here; everything after it is advertising."""


def _fb2_blocks(root: ET.Element) -> tuple[list[tuple], bool]:
    blocks: list[tuple] = []

    def paragraph(element: ET.Element) -> None:
        text = _text(element)
        if FRAGMENT_MARK in text.casefold():
            raise _FragmentEnd
        if text:
            blocks.append(("para", text))

    def walk(element: ET.Element, depth: int) -> None:
        for child in element:
            tag = _local(child.tag)
            if tag == "section":
                title = _title(child.find(FB2 + "title"))
                if FRAGMENT_MARK in title.casefold():
                    raise _FragmentEnd
                if title:
                    blocks.append(("heading", depth + 1, title, True))
                    walk(child, depth + 1)
                else:
                    walk(child, depth)
            elif tag in {"title", "image", "empty-line", "binary"}:
                continue
            elif tag in {"p", "subtitle", "v", "text-author"}:
                paragraph(child)
            elif tag == "table":
                for row in child.iter(FB2 + "tr"):
                    cells = [_text(c) for c in row if _local(c.tag) in {"td", "th"}]
                    if any(cells):
                        blocks.append(("para", " | ".join(cells)))
            else:  # epigraph, cite, poem, stanza, annotation
                walk(child, depth)

    bodies = root.findall(FB2 + "body")
    note_names = {"notes", "comments", "footnotes"}
    fragment = False
    try:
        for body in bodies:
            if body.get("name") not in note_names:
                walk(body, 0)
    except _FragmentEnd:
        fragment = True
    notes: list[str] = []
    for body in bodies:
        if body.get("name") not in note_names:
            continue
        for section in body.iter(FB2 + "section"):
            lines = [
                _text(c)
                for c in section
                if _local(c.tag) in {"p", "v", "subtitle", "text-author", "cite", "poem"}
            ]
            text = clean(" ".join(line for line in lines if line))
            if not text:
                continue
            label = _title(section.find(FB2 + "title")).strip("[]() ")
            notes.append(f"[{label}] {text}" if label else text)
    if notes:
        blocks.append(("heading", 1, NOTES_TITLE, True))
        blocks.extend(("para", note) for note in notes)
    return blocks, fragment


def extract_fb2(data: bytes) -> dict[str, Any]:
    root = safe_xml(data)
    if _local(root.tag) != "FictionBook":
        raise DataError("not an FB2 FictionBook document")
    blocks, fragment = _fb2_blocks(root)
    return {"blocks": blocks, "metadata": fb2_metadata(root), "fragment": fragment}


# ---------------------------------------------------------------------------
# Word 97 (.doc) through antiword
# ---------------------------------------------------------------------------


def antiword_binary() -> str:
    configured = os.environ.get("RESEARCH_ANTIWORD")
    if configured:
        return configured
    found = shutil.which("antiword")
    if found:
        return found
    for candidate in ANTIWORD_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    raise DataError("antiword is required for .doc books; set RESEARCH_ANTIWORD")


def antiword_text(data: bytes) -> tuple[str, str]:
    """Return UTF-8 text with one line per paragraph and the antiword version."""
    binary = antiword_binary()
    with tempfile.TemporaryDirectory(prefix="aspa-library-") as tmp:
        path = Path(tmp) / "book.doc"
        path.write_bytes(data)
        env = {**os.environ, "HOME": os.environ.get("HOME", tmp)}
        try:
            result = subprocess.run(  # noqa: S603 - fixed binary, fixed arguments, local file
                [binary, "-w", "0", "-m", "UTF-8.txt", str(path)],
                capture_output=True,
                env=env,
                timeout=180,
                check=False,
            )
            usage = subprocess.run(  # noqa: S603 - usage text carries the version line
                [binary], capture_output=True, env=env, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DataError("antiword could not run: " + type(exc).__name__) from exc
    if result.returncode != 0 or not result.stdout:
        raise DataError("antiword failed with exit code " + str(result.returncode))
    match = re.search(rb"Version:\s*([^\r\n]+)", usage.stdout + usage.stderr)
    version = "antiword " + (match.group(1).decode().strip() if match else "unknown")
    return result.stdout.decode("utf-8").replace("\r\n", "\n"), version


_CHAPTER_RE = re.compile(r"Глава\s+([IVXLC]+|\d+)\.?", re.IGNORECASE)
_PAGE_MARK_RE = re.compile(r"(?:(?<=[^\W\d_])-)?\[(\d{1,3})\](?:-(?=[^\W\d_]))?")
_NOTE_RULE_RE = re.compile(r"^-{10,}\s*$")
_LEVEL_ONE_KEYS = frozenset({"предисловие", "послесловие", "введение", "заключение"}) | TOC_TITLES


def _mostly_upper(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 3 and sum(ch.isupper() for ch in letters) >= 0.8 * len(letters)


def _accepted_page_marks(lines: list[str]) -> list[tuple[int, int, int]]:
    """Printed page ends form an increasing sequence; footnote calls such as [2] do not."""
    accepted: list[tuple[int, int, int]] = []
    last: int | None = None
    for number, line in enumerate(lines):
        for match in _PAGE_MARK_RE.finditer(line):
            value = int(match.group(1))
            if (last is None and value <= 30) or (last is not None and last < value <= last + 3):
                accepted.append((number, match.start(), value))
                last = value
    return accepted


def _doc_paragraph(line: str, number: int, marks: set[tuple[int, int]]) -> list[tuple]:
    """Split one paragraph at accepted page-end marks; ``[N]`` closes printed page N."""
    blocks: list[tuple] = []
    kind = "para"
    cursor = 0
    for match in _PAGE_MARK_RE.finditer(line):
        if (number, match.start()) not in marks:
            continue
        piece = line[cursor : match.start()]
        inside_word = match.group(0).startswith("-") and match.group(0).endswith("-")
        if piece.strip():
            blocks.append((kind, piece))
            kind = "cont"
        blocks.append(("page", int(match.group(1)) + 1))
        cursor = match.end()
        if inside_word:
            kind = "join"  # "по-[6]-чаще" is one word broken across pages
    rest = line[cursor:]
    if rest.strip():
        blocks.append((kind, rest))
    return blocks


def _doc_blocks(text: str) -> list[tuple]:
    lines = text.split("\n")
    rule = max((i for i, line in enumerate(lines) if _NOTE_RULE_RE.match(line)), default=None)
    body, notes = (lines, []) if rule is None else (lines[:rule], lines[rule + 1 :])
    body = [line.replace("[pic]", "") for line in body]
    accepted = _accepted_page_marks(body)
    marks = {(number, start) for number, start, _ in accepted}
    nonblank = [i for i, line in enumerate(body) if line.strip()]
    following = dict(zip(nonblank, nonblank[1:], strict=False))
    blocks: list[tuple] = [("page", accepted[0][2])] if accepted else []
    chapter: list[str] | None = None
    started = False
    seen_chapter = False

    def flush_chapter() -> None:
        nonlocal chapter
        if chapter is not None:
            title = chapter[0] + (". " + " ".join(chapter[1:]) if chapter[1:] else "")
            blocks.append(("heading", 1, title, True))
            chapter = None

    for number in nonblank:
        line = body[number]
        stripped = line.strip()
        indented = line[:1] in {" ", "\t"}
        if not indented and _CHAPTER_RE.fullmatch(stripped):
            flush_chapter()
            chapter = [stripped.rstrip(".")]
            started = seen_chapter = True
            continue
        if chapter is not None and not indented and _mostly_upper(stripped):
            chapter.append(stripped)  # the printed title wraps over consecutive caps lines
            continue
        flush_chapter()
        upper = not indented and len(stripped) <= 120 and _mostly_upper(stripped)
        if upper and title_key(stripped) in _LEVEL_ONE_KEYS:
            blocks.append(("heading", 1, stripped, True))
            started = True
            continue
        if started and upper:
            blocks.append(("heading", 2 if seen_chapter else 1, stripped, True))
            continue
        next_line = body[following[number]] if number in following else ""
        if (
            seen_chapter
            and not indented
            and len(stripped) <= 70
            and stripped[:1].isupper()
            and not stripped.endswith((".", ",", ";", ":", "!", ")", "»", '"'))
            and not stripped.startswith(("(", "*", "«"))
            and next_line[:1] in {" ", "\t"}
        ):
            blocks.append(("heading", 3, stripped, True))
            continue
        blocks.extend(_doc_paragraph(line, number, marks))
    flush_chapter()
    note_lines = [line.strip() for line in notes if line.strip()]
    if note_lines:
        blocks.append(("heading", 1, NOTES_TITLE, True))
        blocks.extend(("para", line) for line in note_lines)
    return blocks


def extract_doc(data: bytes) -> dict[str, Any]:
    text, version = antiword_text(data)
    return {"blocks": _doc_blocks(text), "metadata": {}, "fragment": False, "tool": version}


# ---------------------------------------------------------------------------
# Markdown with a bold-line table of contents (no ``#`` headings)
# ---------------------------------------------------------------------------

_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~:])")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)\s]+\)")
_MD_TABLE_RULE_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def _md_inline(text: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", re.sub(r"\*{2,3}|_{2,3}", "", text))
    return clean(_MD_ESCAPE_RE.sub(r"\1", text))


def _md_toc(lines: list[str]) -> tuple[list[tuple[int, str, str | None]], int, int]:
    """Return ``(level, title, chapter)`` items and the line range of the printed ToC."""
    start = next(
        (i for i, line in enumerate(lines) if title_key(_md_inline(line)) in TOC_TITLES), None
    )
    if start is None:
        return [], 0, 0
    items: list[tuple[int, str, str | None]] = []
    chapter: str | None = None
    end = start + 1
    for index in range(start + 1, len(lines)):
        raw = lines[index]
        if not raw.strip():
            continue
        bold = raw.strip().startswith("**")
        if not bold and not raw.startswith((" ", "\t")):
            break
        title = _md_inline(raw)
        if bold:
            chapter = title
            items.append((1, title, None))
        else:
            items.append((2, title, chapter))
        end = index + 1
    return items, start, end


def _md_blocks(text: str) -> list[tuple]:
    lines = text.replace("\r\n", "\n").split("\n")
    toc, toc_start, toc_end = _md_toc(lines)
    keys = [title_key(title) for _, title, _ in toc]
    last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    position = 0
    chapters: set[str] = set()
    blocks: list[tuple] = []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or (toc and toc_start <= index < toc_end):
            continue
        if stripped.startswith("|"):
            if not _MD_TABLE_RULE_RE.match(stripped):
                cells = [_md_inline(c) for c in stripped.strip("|").split("|")]
                if row := " | ".join(c for c in cells if c):
                    blocks.append(("para", row))
            continue
        line = _md_inline(stripped)
        key = title_key(line)
        if not line or (index == last and key == "конец"):
            continue
        match = next((i for i in range(position, len(keys)) if keys[i] == key), None)
        if match is not None and len(line) <= 160:
            level, title, chapter = toc[match]
            if level == 2 and chapter and chapter not in chapters:
                blocks.append(("heading", 1, chapter, False))
                chapters.add(chapter)
            if level == 1:
                chapters.add(title)
            blocks.append(("heading", level, title if level == 1 else line, True))
            position = match + 1
            continue
        blocks.append(("para", line))
    return blocks


def extract_md(data: bytes) -> dict[str, Any]:
    text, _ = decode_bytes(data)
    return {"blocks": _md_blocks(text), "metadata": {}, "fragment": False}


# ---------------------------------------------------------------------------
# DjVu XML (Internet Archive OCR layer), sections from a curated printed ToC
# ---------------------------------------------------------------------------


def _djvu_pages(root: ET.Element) -> list[list[list[str]]]:
    pages = []
    for obj in root.iter("OBJECT"):
        paragraphs = []
        for paragraph in obj.iter("PARAGRAPH"):
            lines = [
                clean("".join(word.text or "" for word in line.iter("WORD")))
                for line in paragraph.iter("LINE")
            ]
            if lines := [line for line in lines if line]:
                paragraphs.append(lines)
        pages.append(paragraphs)
    return pages


def _hyphen_join(left: str, right: str, compounds: set[str]) -> str:
    """Join a line-end hyphenation; keep the hyphen only for compounds seen in the book."""
    left_words, right_word = _WORD_RE.findall(left[:-1]), _WORD_RE.match(right)
    candidate = (left_words[-1] + "-" + right_word.group(0)).casefold() if (
        left_words and right_word
    ) else ""
    return left if candidate in compounds else left[:-1]


def _join_ocr_lines(lines: list[str], compounds: set[str]) -> str:
    out = ""
    for line in lines:
        if out.endswith("-") and out[-2:-1].isalpha() and line[:1].islower():
            out = _hyphen_join(out, line, compounds) + line
        else:
            out = (out + " " + line) if out else line
    return out


def _djvu_blocks(root: ET.Element, toc: list[dict[str, Any]]) -> list[tuple]:
    pages = _djvu_pages(root)
    compounds = {
        m.group(0).casefold()
        for page in pages
        for paragraph in page
        for line in paragraph
        for m in _COMPOUND_RE.finditer(line.removesuffix("-"))
    }
    by_page: dict[int, list[dict[str, Any]]] = {}
    for item in toc:
        by_page.setdefault(int(item["page"]), []).append(item)
    blocks: list[tuple] = []
    last_text: int | None = None
    for index, paragraphs in enumerate(pages):
        texts = [_join_ocr_lines(lines, compounds) for lines in paragraphs]
        # The printed running number is a lone number at the top or bottom of the page.
        while texts and re.fullmatch(r"\d{1,3}", texts[-1]):
            texts.pop()
        while texts and re.fullmatch(r"\d{1,3}", texts[0]):
            texts.pop(0)
        blocks.append(("page", index))
        placed: dict[int, list[dict[str, Any]]] = {}
        for item in by_page.get(index, []):
            key = title_key(item.get("match") or item["title"])[:14]
            found = next((i for i, t in enumerate(texts) if title_key(t).startswith(key)), 0)
            placed.setdefault(found, []).append(item)
        if not texts:
            for item in placed.get(0, []):
                blocks.append(("heading", int(item["level"]), item["title"], False))
            continue
        for position, text in enumerate(texts):
            for item in placed.get(position, []):
                blocks.append(("heading", int(item["level"]), item["title"], False))
            kind = "para"
            if position == 0 and not placed.get(0) and text[:1].islower() and last_text is not None:
                previous = blocks[last_text]
                kind = "cont"
                if previous[1].endswith("-") and previous[1][-2:-1].isalpha():
                    blocks[last_text] = (previous[0], _hyphen_join(previous[1], text, compounds))
                    kind = "join"
            blocks.append((kind, text))
            last_text = len(blocks) - 1
    return blocks


def extract_djvu_xml(data: bytes, *, toc: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = safe_xml(data)
    if root.tag != "DjVuXML":
        raise DataError("not a DjVuXML document")
    return {"blocks": _djvu_blocks(root, toc or []), "metadata": {}, "fragment": False}


# ---------------------------------------------------------------------------
# HTML saved from Microsoft Word
# ---------------------------------------------------------------------------


class _BookHTML(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template", "head", "xml"})
    _BLOCK = frozenset(
        {"p", "div", "li", "tr", "td", "th", "table", "blockquote", "pre", "dd", "dt", "br"}
    )
    _HEADING = {f"h{n}": n for n in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple] = []
        self.title_parts: list[str] = []
        self._buffer: list[str] = []
        self._skip = 0
        self._in_title = False
        self._heading: int | None = None
        self._body = False

    def _flush(self) -> None:
        text = clean("".join(self._buffer))
        self._buffer = []
        if text:
            self.blocks.append(
                ("heading", self._heading, text, True) if self._heading else ("para", text)
            )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "body":
            self._body = True
        elif tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip += 1
        elif tag in self._HEADING:
            self._flush()
            self._heading = self._HEADING[tag]
        elif tag in self._BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._HEADING:
            self._flush()
            self._heading = None
        elif tag in self._BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._body and not self._skip:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def extract_html(data: bytes) -> dict[str, Any]:
    text, _ = decode_bytes(data)
    parser = _BookHTML()
    parser.feed(text)
    parser.close()
    title = clean("".join(parser.title_parts))
    return {
        "blocks": parser.blocks,
        "metadata": {"title": title} if title else {},
        "fragment": False,
    }


# ---------------------------------------------------------------------------
# PDF with a text layer (print layout, optionally two book pages per sheet)
# ---------------------------------------------------------------------------

_PRINT_FOOTER_RE = re.compile(r"^\s*(?:\d+\s*/\s*\d+|Powered by TCPDF \(www\.tcpdf\.org\))\s*$")
_PAGE_HEADER_RE = re.compile(r"^\s*(\d{1,3})(?:\s+(\d{1,3}))?\s*$")
_RUNNING_NUMBER_RE = re.compile(r"^(\d{1,3})\s+\S|\S\s+(\d{1,3})$")
_PARAGRAPH_END = (".", "!", "?", ":", ";", "»", "…", '"')
_LIST_START_RE = re.compile(r"^(?:\d{1,2}[.)]|[a-zа-я][.)]|[–—•])\s")
_SPACED_HYPHEN_RE = re.compile(r"(?<=[^\W\d_]) -(?=[^\W\d_]|$)")


def pdf_page_texts(data: bytes) -> list[str]:
    import io
    import logging

    import pypdf

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding chatter only
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DataError("encrypted PDF books are not processed")
        return [page.extract_text() or "" for page in reader.pages]
    except pypdf.errors.PyPdfError as exc:
        raise DataError("malformed PDF book: " + type(exc).__name__) from exc


def _sheet_lines(texts: list[str]) -> list[list[str]]:
    """Normalized lines per sheet without print footers or per-page watermark lines."""
    pages = []
    for text in texts:
        lines = [" ".join(line.split()) for line in text.split("\n")]
        pages.append([line for line in lines if line and not _PRINT_FOOTER_RE.match(line)])
    counts = Counter(line for lines in pages for line in set(lines))
    # A short line printed on most sheets (a distributor watermark) is not book text.
    boilerplate = {
        line for line, n in counts.items() if n > 0.5 * len(pages) and len(line) < 80
    }
    suffixes = tuple(" " + line for line in boilerplate if len(line) >= 6)

    def strip(line: str) -> str:
        for suffix in suffixes:  # the watermark sometimes lands on the last text line
            if line.endswith(suffix):
                return line[: -len(suffix)]
        return line

    return [[strip(line) for line in lines if line not in boilerplate] for lines in pages]


def _running_number(line: str) -> int | None:
    pure = _PAGE_HEADER_RE.match(line)
    if pure:
        return int(pure.group(1))
    match = _RUNNING_NUMBER_RE.search(line)
    return int(match.group(1) or match.group(2)) if match else None


def _pdf_sheets(texts: list[str], layout: str) -> list[tuple[tuple[int, int], list[str]]]:
    """Drop footers, watermarks and repeated sheets; label sheets with printed pages.

    ``spreads``: two book pages per sheet with a bare ``"10 11"`` header; sheets are
    reordered by those numbers. ``pages``: one page per sheet with a running header
    (``"16 Title"`` or ``"Title 17"``); a first line counts as a header only when its
    number fits the sequence, so ``"Глава 1"`` on a chapter opening stays text."""
    unique: list[tuple[int, list[str]]] = []  # original sheet index keeps page arithmetic
    seen: set[str] = set()
    for index, lines in enumerate(_sheet_lines(texts)):
        key = "\n".join(lines)
        if lines and key not in seen:
            seen.add(key)
            unique.append((index, lines))
    if layout == "spreads":
        spans: list[tuple[tuple[int, int], list[str]]] = []
        previous: tuple[int, int] | None = None
        for _, lines in unique:
            header = _PAGE_HEADER_RE.match(lines[0])
            numbers = [int(g) for g in header.groups() if g] if header else []
            if header:
                lines = lines[1:]
            if len(numbers) == 2:
                span = (numbers[0], numbers[1])
            elif numbers:
                n = numbers[0]
                span = (n, n + 1) if n % 2 == 0 else (n - 1, n)
            else:  # unnumbered sheet keeps its place after the previous one
                span = (previous[1] + 1, previous[1] + 2) if previous else (1, 1)
            previous = span
            spans.append((span, lines))
        return sorted(spans, key=lambda item: item[0])
    candidates = [(index, _running_number(lines[0])) for index, lines in unique]
    offsets = Counter(n - i for i, n in candidates if n is not None)
    offset = offsets.most_common(1)[0][0] if offsets else 1
    sheets = []
    for (index, lines), (_, number) in zip(unique, candidates, strict=True):
        expected = index + offset
        if number is not None and abs(number - expected) <= 1:
            lines = lines[1:]
            expected = number
        sheets.append(((expected, expected), lines))
    return sheets


def _toc_lines(lines: list[str], items: list[dict[str, Any]]) -> dict[int, tuple[dict, int]]:
    """Locate printed ToC titles that span one to three consecutive lines."""
    found: dict[int, tuple[dict, int]] = {}
    cursor = 0
    for item in items:
        key = title_key(item.get("match") or item["title"])
        for start in range(cursor, len(lines)):
            joined = [title_key(" ".join(lines[start : start + n])) for n in (1, 2, 3)]
            size = next(
                (n for n, candidate in zip((1, 2, 3), joined, strict=True) if candidate == key),
                None,
            )
            if size and start + size <= len(lines):
                found[start] = (item, size)
                cursor = start + size
                break
    return found


def _pdf_blocks(sheets: list[tuple[tuple[int, int], list[str]]], toc: list[dict]) -> list[tuple]:
    compounds = {
        m.group(0).casefold()
        for _, lines in sheets
        for line in lines
        for m in _COMPOUND_RE.finditer(line.removesuffix("-"))
    }
    blocks: list[tuple] = []
    open_paragraph = False
    for (first, last), lines in sheets:
        blocks.append(("page", str(first) if first == last else f"{first}–{last}"))
        items = [item for item in toc if first <= int(item["page"]) <= last]
        headings = _toc_lines(lines, items)
        placed = {id(item) for item, _ in headings.values()}
        for item in items:
            if id(item) not in placed:  # title not found verbatim: place at the sheet start
                blocks.append(("heading", int(item["level"]), item["title"], False))
        lines = [_SPACED_HYPHEN_RE.sub("-", line) for line in lines]
        lengths = sorted(len(line) for line in lines if len(line) > 20)
        typical = lengths[int(len(lengths) * 0.75)] if lengths else 60
        paragraph, kind = "", "para"

        def flush() -> None:
            nonlocal paragraph, kind
            if paragraph:
                blocks.append((kind, paragraph))
            paragraph, kind = "", "para"

        index = 0
        while index < len(lines):
            if index in headings:
                flush()
                item, size = headings[index]
                blocks.append(("heading", int(item["level"]), item["title"], True))
                index += size
                open_paragraph = False
                continue
            line = lines[index]
            if not paragraph and open_paragraph and line[:1].islower():
                previous = max(i for i, b in enumerate(blocks) if b[0] in TEXT_BLOCKS)
                text = blocks[previous][1]
                kind = "cont"
                if text.endswith("-") and text[-2:-1].isalpha():
                    blocks[previous] = (blocks[previous][0], _hyphen_join(text, line, compounds))
                    kind = "join"
            elif paragraph and _LIST_START_RE.match(line):
                flush()
            if paragraph.endswith("-") and paragraph[-2:-1].isalpha() and line[:1].islower():
                paragraph = _hyphen_join(paragraph, line, compounds) + line
            else:
                paragraph = f"{paragraph} {line}" if paragraph else line
            open_paragraph = True
            if line.endswith(_PARAGRAPH_END) and len(line) < 0.8 * typical:
                flush()
                open_paragraph = False
            index += 1
        flush()
    return blocks


def extract_pdf(data: bytes, *, options: dict[str, Any]) -> dict[str, Any]:
    texts = pdf_page_texts(data)
    if not any(t.strip() for t in texts):
        raise DataError("PDF has no text layer; OCR is required")
    sheets = _pdf_sheets(texts, options.get("pdf_layout", "pages"))
    return {
        "blocks": _pdf_blocks(sheets, options.get("toc") or []),
        "metadata": {"pdf_pages": len(texts), "unique_sheets": len(sheets)},
        "fragment": False,
    }


# ---------------------------------------------------------------------------
# Catalog-driven structure repair
# ---------------------------------------------------------------------------

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}
_INLINE_NUMBER_RE = re.compile(
    r"(?<![\w.])(I{1,3}|IV|V|VI{1,3}|IX)\.((?:\s?\d{1,2}\.)+)(?=\s|[^\W\d_])"
)
_CHAPTER_NUMBER_RE = re.compile(r"^(I{1,3}|IV|V|VI{1,3}|IX)\.\s")


def _successors(previous: tuple[int, ...]) -> set[tuple[int, ...]]:
    """Numbers that may follow ``previous``: its first child or the next sibling of any
    ancestor. Cross-references (``см. II. 6. 1``) break this order and stay text."""
    following = {previous + (1,)}
    following.update(previous[:k] + (previous[k] + 1,) for k in range(len(previous)))
    return following


def split_inline_headings(blocks: list[tuple]) -> list[tuple]:
    """Recover ``III. 1. 2.`` headings that a converter flattened into running text."""
    repaired: list[tuple] = []
    previous: tuple[int, ...] | None = None
    for block in blocks:
        if block[0] == "heading":
            match = _CHAPTER_NUMBER_RE.match(clean(block[2]))
            previous = (_ROMAN[match.group(1)],) if match else previous
            repaired.append(block)
            continue
        if block[0] not in TEXT_BLOCKS or previous is None:
            repaired.append(block)
            continue
        text, cursor, kind = block[1], 0, block[0]
        matches = list(_INLINE_NUMBER_RE.finditer(text))
        for position, match in enumerate(matches):
            number = (_ROMAN[match.group(1)], *map(int, re.findall(r"\d+", match.group(2))))
            if number not in _successors(previous):
                continue
            if text[cursor : match.start()].strip():
                repaired.append((kind, text[cursor : match.start()]))
                kind = "para"
            stop = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            words = text[match.end() : stop].split()
            label = f"{match.group(1)}." + "".join(f"{n}." for n in number[1:])
            preview = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
            repaired.append(("heading", len(number), f"{label} {preview}".strip(), False))
            previous, cursor = number, match.start()
        if text[cursor:].strip():
            repaired.append((kind, text[cursor:]))
    return repaired


def limit_heading_levels(blocks: list[tuple], max_level: int) -> list[tuple]:
    """Treat deeper headings (figure labels exported as ``h5``) as ordinary paragraphs."""
    limited: list[tuple] = []
    for block in blocks:
        if block[0] == "heading" and block[1] > max_level:
            if block[3]:
                limited.append(("para", block[2]))
            continue
        limited.append(block)
    return limited


def extract(fmt: str, data: bytes, *, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize one book and return text, sections, pages and quality evidence."""
    options = options or {}
    if fmt == "fb2":
        result = extract_fb2(data)
    elif fmt == "doc":
        result = extract_doc(data)
    elif fmt == "md":
        result = extract_md(data)
    elif fmt == "djvu_xml":
        result = extract_djvu_xml(data, toc=options.get("toc"))
    elif fmt == "html":
        result = extract_html(data)
    elif fmt == "pdf":
        result = extract_pdf(data, options=options)
    else:
        raise DataError("unsupported book format: " + fmt)
    blocks = result["blocks"]
    if options.get("inline_headings") == "roman_decimal":
        blocks = split_inline_headings(blocks)
    elif options.get("inline_headings"):
        raise DataError("unsupported inline heading scheme")
    if options.get("max_heading_level"):
        blocks = limit_heading_levels(blocks, int(options["max_heading_level"]))
    if options.get("join_split_words"):
        blocks = join_split_words(blocks)
    blocks, removed = exclude_sections(blocks, options.get("exclude_sections", []))
    return {
        **assemble(join_inner_hyphens(blocks)),
        "metadata": result["metadata"],
        "fragment": result["fragment"],
        "excluded_sections": removed,
        "tool": result.get("tool"),
    }
