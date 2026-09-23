"""Deterministic citation and BibTeX projection from private research evidence."""

from __future__ import annotations

from dataclasses import dataclass

from service.domain.subagents.research import ResearchArtifact, SourceRecord


def _escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    cleaned = str(value or "").replace("\x00", " ").strip()
    return "".join(replacements.get(character, character) for character in cleaned)


def _key(record: SourceRecord) -> str:
    return f"src{record.source_id}_{record.fingerprint[:10]}"


@dataclass(frozen=True, slots=True)
class CitationRegistry:
    artifact: ResearchArtifact

    def key_for(self, source_id: int) -> str | None:
        record = next((item for item in self.artifact.records if item.source_id == source_id), None)
        return _key(record) if record is not None else None

    def bibliography(self) -> str:
        entries: list[str] = []
        for record in self.artifact.records:
            fields = [
                f"  title = {{{_escape(record.title)}}}",
                f"  url = {{{_escape(record.canonical_url)}}}",
            ]
            if record.authors:
                fields.append(
                    f"  author = {{{' and '.join(_escape(item) for item in record.authors)}}}"
                )
            if record.year is not None:
                fields.append(f"  year = {{{record.year}}}")
            if record.doi:
                fields.append(f"  doi = {{{_escape(record.doi)}}}")
            fields.append(f"  note = {{Verified source {record.source_id}}}")
            entries.append(f"@misc{{{_key(record)},\n" + ",\n".join(fields) + "\n}")
        return "\n\n".join(entries)

    def prompt_context(self, *, max_chars: int = 18_000) -> str:
        blocks: list[str] = []
        total = 0
        for record in self.artifact.records:
            block = record.synthesis_block(max_chars=2_400)
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(blocks)


__all__ = ["CitationRegistry"]
