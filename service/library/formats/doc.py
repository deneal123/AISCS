"""Word 97 (.doc) extraction through antiword with printed page marks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ...common.errors import DataError
from .blocks import NOTES_TITLE, TOC_TITLES, title_key

ANTIWORD_CANDIDATES = (Path(r"C:\Program Files\Git\mingw64\bin\antiword.exe"),)


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
