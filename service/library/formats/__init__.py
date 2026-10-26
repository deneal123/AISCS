"""Book normalizers: FB2, Word 97 via antiword, Markdown, DjVu XML, Word HTML and PDF.

Each extractor yields ordered blocks (see ``blocks``); ``extract`` applies catalog-driven
structure repair and assembles one text with exact heading and page offsets.
"""

from __future__ import annotations

from typing import Any

from ...common.errors import DataError
from .blocks import assemble, exclude_sections
from .djvu import extract_djvu_xml
from .doc import extract_doc
from .fb2 import extract_fb2
from .html import extract_html
from .markdown import extract_md
from .pdf import extract_pdf
from .repair import (
    join_inner_hyphens,
    join_split_words,
    limit_heading_levels,
    split_inline_headings,
)

PARSER_VERSION = "library-normalizer-v1"
FORMATS = ("fb2", "doc", "md", "djvu_xml", "html", "pdf")


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
