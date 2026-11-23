"""Keep the Mermaid diagrams in the materials folder structurally sound.

The diagrams are Markdown, so a broken fence or a stray backslash only shows up as a
rendering failure in a browser. The full check needs mermaid-cli and a headless browser,
which this suite deliberately does not pull in; what it does enforce is the set of mistakes
that actually happened while the folder was written:

* a fence that is opened and never closed,
* an empty diagram,
* a first line that is not a recognised diagram type,
* a literal backslash-n or a backslash-escaped <br/> inside a label: Mermaid renders those
  as a literal backslash instead of a line break.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DIAGRAMS = Path(__file__).resolve().parents[2] / "docs" / "Материалы" / "Схемы_симуляции_2026-11"
KINDS = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
         "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "mindmap", "timeline")
OPEN = re.compile(r"^\s*```mermaid\s*$")
CLOSE = re.compile(r"^\s*```\s*$")


def _diagrams():
    if not DIAGRAMS.is_dir():
        pytest.skip(f"diagrams folder is absent: {DIAGRAMS}")
    files = sorted(DIAGRAMS.glob("*.md"))
    assert files, f"no Markdown files under {DIAGRAMS}"
    return files


def _blocks(path: Path):
    """Yield (line number, body lines) for each fenced mermaid block."""
    body: list[str] = []
    start = 0
    for number, line in enumerate(path.read_text(encoding="utf8").splitlines(), start=1):
        if not body and not start and OPEN.match(line):
            body, start = [], number
            continue
        if start and CLOSE.match(line):
            yield start, body
            body, start = [], 0
            continue
        if start:
            body.append(line)
    if start:
        yield start, body


@pytest.mark.parametrize("path", _diagrams(), ids=lambda item: item.name)
def test_every_mermaid_block_is_closed_and_typed(path):
    blocks = list(_blocks(path))
    if path.name == "README.md":
        # The index is prose and a table on purpose; every other file must carry diagrams.
        return
    assert blocks, f"{path.name} declares no mermaid block"
    assert path.read_text(encoding="utf8").count("```") % 2 == 0, (
        f"{path.name} has an odd number of fences")
    for line, body in blocks:
        assert body, f"{path.name}:{line}: empty diagram"
        first = body[0].strip()
        assert first.split()[0] in KINDS, (
            f"{path.name}:{line}: diagram starts with {first!r}, not a known type")


@pytest.mark.parametrize("path", _diagrams(), ids=lambda item: item.name)
def test_labels_use_br_for_line_breaks(path):
    for line, body in _blocks(path):
        for offset, text in enumerate(body):
            assert "\\n" not in text, (
                f"{path.name}:{line + offset}: literal backslash-n in a label; use <br/>")
            assert "\\<br/>" not in text, (
                f"{path.name}:{line + offset}: escaped <br/> renders a backslash; drop it")
