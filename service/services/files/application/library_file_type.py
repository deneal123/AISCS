"""Bounded Library display kinds, independent of storage mode or content parsing.

The suffix is only a display hint. It must not authorize execution, choose a
parser, or assert that an archive is a verified repository. No file bytes,
storage keys, message metadata, or provider calls are needed here.
"""

from pathlib import PurePosixPath

_TYPE_BY_SUFFIX = {
    suffix: kind
    for kind, suffixes in (
        ("text", (".txt", ".md", ".markdown", ".rst", ".log")),
        ("pdf", (".pdf",)),
        ("docx", (".docx",)),
        ("doc", (".doc",)),
        ("odt", (".odt",)),
        ("rtf", (".rtf",)),
        ("csv", (".csv",)),
        ("tsv", (".tsv",)),
        ("json", (".json",)),
        ("jsonl", (".jsonl", ".ndjson")),
        ("xlsx", (".xlsx",)),
        ("xls", (".xls",)),
        ("ods", (".ods",)),
        ("pptx", (".pptx",)),
        ("ppt", (".ppt",)),
        ("image", (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")),
        ("audio", (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")),
        ("video", (".mp4", ".webm", ".mov", ".mkv", ".avi")),
        ("archive", (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")),
        (
            "code",
            (
                ".tex",
                ".bib",
                ".cls",
                ".sty",
                ".py",
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
                ".java",
                ".go",
                ".rs",
                ".cpp",
                ".cc",
                ".c",
                ".h",
                ".hpp",
                ".cs",
                ".rb",
                ".php",
                ".sql",
                ".sh",
                ".bash",
                ".kt",
                ".swift",
                ".scala",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
            ),
        ),
    )
    for suffix in suffixes
}


def library_file_type(name: str) -> str:
    """Project only the already-safe name; unknown extensions remain binary."""
    suffix = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    return _TYPE_BY_SUFFIX.get(suffix, "binary")
