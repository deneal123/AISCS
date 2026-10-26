"""Evidence-corpus preparation: parsing, identity, discovery, chunking."""

from ...common.errors import CorpusError
from .candidates import (
    DEFAULT_MAX_SCRATCH_FILES,
    DISCOVERY_EXTENSIONS,
    EXCLUDED_DIR_NAMES,
    STRUCTURAL_BASENAMES,
    discover_local_sources,
    normalize_candidates,
    scan_local_sources,
)
from .chunks import chunk_documents
from .identity import (
    DOI_RE,
    TITLE_STOPWORDS,
    extract_identifiers,
    load_canonical_identity,
    normalize_title,
    repository_view,
    validate_identity,
)
from .parsing import (
    SECTION_LABELS,
    build_sections,
    classify_heading,
    detect_error_page,
    parse_document,
)
from .prepare import (
    MANIFEST_ENTRY_STATUSES,
    load_documents,
    load_manifest,
    portable_manifest,
    prepare_corpus,
)
from .text import (
    WHITESPACE_RE,
    as_list,
    assert_within,
    detect_format,
    json_dumps,
    looks_like_markup,
    normalize_fragment,
    now_iso,
)

__all__ = [
    "CorpusError",
    "DEFAULT_MAX_SCRATCH_FILES",
    "DISCOVERY_EXTENSIONS",
    "DOI_RE",
    "EXCLUDED_DIR_NAMES",
    "MANIFEST_ENTRY_STATUSES",
    "SECTION_LABELS",
    "STRUCTURAL_BASENAMES",
    "TITLE_STOPWORDS",
    "WHITESPACE_RE",
    "as_list",
    "assert_within",
    "build_sections",
    "chunk_documents",
    "classify_heading",
    "detect_error_page",
    "detect_format",
    "discover_local_sources",
    "extract_identifiers",
    "json_dumps",
    "load_canonical_identity",
    "load_documents",
    "load_manifest",
    "looks_like_markup",
    "normalize_candidates",
    "normalize_fragment",
    "normalize_title",
    "now_iso",
    "parse_document",
    "portable_manifest",
    "prepare_corpus",
    "repository_view",
    "scan_local_sources",
    "validate_identity",
]
