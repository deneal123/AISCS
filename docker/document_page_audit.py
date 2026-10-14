"""Bounded Poppler page inventory; no PDF content or raw diagnostics escape."""

from __future__ import annotations

import math
import re

_PAGES = re.compile(r"^Pages:\s*([0-9]{1,5})\s*$", re.MULTILINE)
_SIZE = re.compile(
    r"^Page\s+([0-9]{1,5})\s+size:\s*([0-9.]{1,24})\s+x\s+([0-9.]{1,24})\s+pts(?:\s.*)?$",
    re.MULTILINE,
)
_ROTATION = re.compile(r"^Page\s+([0-9]{1,5})\s+rot:\s*([0-9]{1,3})\s*$", re.MULTILINE)
MAX_INSPECTED_PAGES = 10_000


def page_count(report: str) -> int:
    matches = _PAGES.findall(report)
    if len(matches) != 1 or not 1 <= int(matches[0]) <= MAX_INSPECTED_PAGES:
        raise ValueError("pdf_invalid")
    return int(matches[0])


def page_inventory(report: str, expected_pages: int) -> tuple[tuple[float, float, int], ...]:
    """Each numbered page must have exactly one finite positive size and rotation."""
    if len(report) > 4 * 1024 * 1024 or page_count(report) != expected_pages:
        raise ValueError("pdf_invalid")
    sizes = _SIZE.findall(report)
    rotations = _ROTATION.findall(report)
    expected = set(range(1, expected_pages + 1))
    if (
        len(sizes) != expected_pages
        or len(rotations) != expected_pages
        or {int(page) for page, *_ in sizes} != expected
        or {int(page) for page, _ in rotations} != expected
    ):
        raise ValueError("pdf_invalid")
    rotation_by_page = {int(page): int(value) for page, value in rotations}
    result = {}
    for page, raw_width, raw_height in sizes:
        width, height = float(raw_width), float(raw_height)
        rotation = rotation_by_page[int(page)]
        if not all(
            math.isfinite(value) and 0 < value <= 100_000 for value in (width, height)
        ) or rotation not in {0, 90, 180, 270}:
            raise ValueError("pdf_invalid")
        result[int(page)] = (width, height, rotation)
    return tuple(result[page] for page in sorted(expected))


def geometry_diagnostics(
    pages: tuple[tuple[float, float, int], ...], paper: str, orientation: str
) -> tuple[tuple[str, int], ...]:
    expected = {
        "a4": (595.3, 841.9),
        "letter": (612.0, 792.0),
        "slide_16_9": (453.5, 255.1),
    }.get(paper)
    geometry_errors = orientation_errors = 0
    for width, height, rotation in pages:
        physical_size = sorted((width, height))
        expected_size = sorted(expected) if expected else None
        geometry_errors += bool(
            expected_size
            and any(
                abs(actual - target) > 4.0
                for actual, target in zip(physical_size, expected_size, strict=True)
            )
        )
        visible_width, visible_height = (
            (height, width) if rotation in {90, 270} else (width, height)
        )
        orientation_errors += (orientation == "landscape" and visible_width <= visible_height) or (
            orientation == "portrait" and visible_height <= visible_width
        )
    return tuple(
        (code, min(count, 999))
        for code, count in (
            ("page_geometry", geometry_errors),
            ("page_orientation", orientation_errors),
        )
        if count
    )
