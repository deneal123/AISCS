"""Bounded Cyrillic support for the two built-in pdfLaTeX publisher profiles."""

import re

_LATIN_ENCODING = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\\usepackage\[T1\]\{fontenc\}"
    r"(?P<suffix>[ \t]*(?:%[^\n]*)?)$"
)
_BABEL = re.compile(r"(?m)^[ \t]*\\usepackage(?:\[[^\]\n]*\])?\{[^}\n]*\bbabel\b")
_FONT_SPEC = re.compile(r"(?m)^[ \t]*\\usepackage(?:\[[^\]\n]*\])?\{[^}\n]*\bfontspec\b")


def publisher_language(scaffold: str, *, profile_id: str, locale: str) -> str:
    """Keep class/engine/geometry, and never reinterpret an arbitrary vendor preamble."""
    if profile_id not in {"ieee_journal", "aaai_conference"} or locale not in {"ru", "ru-RU"}:
        return scaffold
    head, begin, body = scaffold.partition(r"\begin{document}")
    if not begin or _FONT_SPEC.search(head) or not _LATIN_ENCODING.search(head):
        return scaffold
    language = "\\usepackage[english,russian]{babel}" if not _BABEL.search(head) else ""
    result = _LATIN_ENCODING.sub(
        lambda match: (
            match["indent"]
            + r"\usepackage[T2A,T1]{fontenc}"
            + match["suffix"]
            + ("\n" + language if language else "")
        ),
        head,
        count=1,
    )
    return result + begin + body
