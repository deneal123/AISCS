"""Bounded read-only projection of registered BibTeX entries; never evaluates TeX."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_BIBLIOGRAPHY_BYTES = 750_000

_ENTRY = re.compile(r"@([A-Za-z]+)\s*([\{(])")
_KEY = re.compile(r"src([0-9]{1,5})_[a-f0-9]{10}\Z")
_FIELD = re.compile(r"\s*([A-Za-z]+)\s*=\s*")
_ESCAPES = {
    r"\textbackslash{}": "\\",
    r"\textasciicircum{}": "^",
    r"\textasciitilde{}": "~",
    **{f"\\{value}": value for value in "{}#$%&_"},
}
_ESCAPE = re.compile("|".join(re.escape(value) for value in _ESCAPES))


def _balanced(text: str, start: int, *, comments: bool = False) -> int:
    stack = [text[start]]
    quoted = False
    position = start + 1
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "%" and comments and len(stack) == 1 and not quoted:
            newline = text.find("\n", position)
            position = len(text) if newline < 0 else newline + 1
            continue
        if char == '"' and len(stack) == 1:
            quoted = not quoted
        elif not quoted:
            if char == "{":
                stack.append("{")
            elif char == "}":
                if stack[-1] != "{":
                    raise ValueError("bibliography_invalid")
                stack.pop()
            elif text[start] == "(" and stack[-1] == "(":
                if char == "(":
                    stack.append("(")
                elif char == ")":
                    stack.pop()
            if not stack:
                return position
        position += 1
    raise ValueError("bibliography_invalid")


def _plain(value: str) -> str:
    # Invert only our trusted producer's text escapes. Arbitrary TeX commands,
    # macros and grouping are not converted into invented human metadata.
    tokens: list[str] = []
    position = 0
    for match in _ESCAPE.finditer(value):
        raw = value[position : match.start()]
        if any(char in raw for char in "\\{}"):
            return ""
        tokens.extend((raw, _ESCAPES[match.group()]))
        position = match.end()
    tail = value[position:]
    if any(char in tail for char in "\\{}"):
        return ""
    plain = " ".join("".join([*tokens, tail]).split())
    return plain if len(plain) <= 2000 else ""


def _fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    position = 0
    while position < len(body):
        if body[position].isspace() or body[position] == ",":
            position += 1
            continue
        if body[position] == "%":
            end = body.find("\n", position)
            position = len(body) if end < 0 else end + 1
            continue
        match = _FIELD.match(body, position)
        if match is None:
            raise ValueError("bibliography_invalid")
        name = match[1].lower()
        position = match.end()
        if position == len(body):
            raise ValueError("bibliography_invalid")
        if body[position] == "{":
            end = _balanced(body, position)
            value = _plain(body[position + 1 : end])
            position = end + 1
        elif body[position] == '"':
            start = position = position + 1
            while position < len(body) and body[position] != '"':
                position += 2 if body[position] == "\\" else 1
            if position >= len(body):
                raise ValueError("bibliography_invalid")
            value = _plain(body[start:position])
            position += 1
        else:
            end = body.find(",", position)
            end = len(body) if end < 0 else end
            literal = body[position:end].strip()
            value = literal if literal.isascii() and literal.isdigit() else ""
            position = end
        if name in fields:
            raise ValueError("bibliography_invalid")
        fields[name] = value
        tail = body[position:].lstrip()
        if tail and not tail.startswith(","):
            raise ValueError("bibliography_invalid")
    return fields


def registered_sources(bibliography: str) -> dict:
    if len(bibliography.encode("utf-8")) > MAX_BIBLIOGRAPHY_BYTES or "\x00" in bibliography:
        raise ValueError("bibliography_invalid")
    records: dict[int, dict] = {}
    ambiguous: set[int] = set()
    unresolved = 0
    position = 0
    while position < len(bibliography):
        if bibliography[position] == "%":
            newline = bibliography.find("\n", position)
            position = len(bibliography) if newline < 0 else newline + 1
            continue
        match = _ENTRY.match(bibliography, position)
        if match is None:
            position += 1
            continue
        end = _balanced(bibliography, match.end() - 1, comments=True)
        position = end + 1
        if match[1].lower() in {"comment", "string", "preamble"}:
            continue
        if match[2] != "{":
            unresolved += 1
            continue
        body = bibliography[match.end() : end]
        key, separator, fields = body.partition(",")
        identity = _KEY.fullmatch(key.strip())
        if not separator or identity is None or not 1 <= int(identity[1]) <= 10_000:
            unresolved += 1
            continue
        source_id = int(identity[1])
        if source_id in records or source_id in ambiguous:
            records.pop(source_id, None)
            ambiguous.add(source_id)
            unresolved += 1
            continue
        metadata = _fields(fields)
        url = metadata.get("url", "")
        try:
            parts = urlsplit(url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or any(char.isspace() for char in url)
            ):
                metadata.pop("url", None)
        except ValueError:
            metadata.pop("url", None)
        records[source_id] = {
            "source_id": source_id,
            "key": key.strip(),
            **{
                field: metadata[field]
                for field in ("title", "author", "year", "url", "doi")
                if metadata.get(field)
            },
        }
    return {"sources": list(records.values()), "unresolved_count": unresolved}
