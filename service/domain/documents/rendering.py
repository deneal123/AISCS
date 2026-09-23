"""Trusted LaTeX renderers for the semantic document graph."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Protocol

from .draft import BlockKind, DocumentDraft, DraftBlock
from .intent import DocumentIntent
from .outline import section_role

_BEGIN = "\\begin{document}"
_END = "\\end{document}"
_SECTION_BLOCK_KIND: BlockKind = "section"
_SAFE_EQUATION = re.compile(r"^[A-Za-z0-9\s+\-*/=^_{}()[\].,:\\]+$")
_EQUATION_COMMAND = re.compile(r"\\([A-Za-z]+)")
_SAFE_EQUATION_COMMANDS = frozenset(
    {
        "Delta",
        "Omega",
        "alpha",
        "beta",
        "cdot",
        "cos",
        "delta",
        "frac",
        "gamma",
        "geq",
        "infty",
        "int",
        "lambda",
        "leq",
        "lim",
        "log",
        "mu",
        "neq",
        "nu",
        "omega",
        "partial",
        "phi",
        "pi",
        "prod",
        "rho",
        "sigma",
        "sin",
        "sqrt",
        "sum",
        "tan",
        "text",
        "theta",
        "times",
    }
)


class CitationResolver(Protocol):
    def key_for(self, source_id: int) -> str | None: ...


@dataclass(frozen=True, slots=True)
class RenderedSourceBundle:
    files: dict[str, str]
    authoring_version: int
    draft_digest: str


def _required_section_id(title: str, occupied: set[str]) -> str:
    """Return a stable trusted ID without accepting model-controlled identifiers."""

    digest = hashlib.sha256(title.casefold().encode("utf-8", errors="replace")).hexdigest()[:12]
    base = f"required_{digest}"
    candidate = base
    ordinal = 2
    while candidate in occupied:
        candidate = f"{base}_{ordinal}"
        ordinal += 1
    occupied.add(candidate)
    return candidate


def _enforce_required_sections(
    intent: DocumentIntent,
    draft: DocumentDraft,
) -> DocumentDraft:
    """Keep profile-owned headings present in the exact rendered semantic graph.

    Outline and section parsing already create these headings.  This final
    boundary is intentionally defensive: a later bounded repair may replace a
    heading block, but it must never weaken a locked profile requirement.
    """

    if intent.kind == "presentation" or not intent.required_sections:
        return draft
    titles = {
        block.title.strip().casefold()
        for block in draft.blocks
        if block.kind == "section" and block.title.strip()
    }
    occupied = {block.block_id for block in draft.blocks}
    additions: list[DraftBlock] = []
    for value in intent.required_sections:
        title = str(value or "").strip()[:300]
        if not title or title.casefold() in titles:
            continue
        additions.append(
            DraftBlock(
                block_id=_required_section_id(title, occupied),
                kind=_SECTION_BLOCK_KIND,
                title=title,
            )
        )
        titles.add(title.casefold())
    if not additions:
        return draft
    return replace(draft, blocks=(*draft.blocks, *additions))


def latex_escape(value: str) -> str:
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
    return "".join(replacements.get(character, character) for character in str(value))


def _text(value: str) -> str:
    return "\n\n".join(latex_escape(part) for part in str(value).split("\n\n"))


def _section(block: DraftBlock, *, report: bool, article: bool) -> str:
    title = block.title or block.text
    if article and title.strip().casefold() in {"abstract", "аннотация"}:
        return f"\\begin{{abstract}}\n{_text(block.text)}\n\\end{{abstract}}"
    command = "chapter" if report and block.level == 1 else "section"
    if block.level == 2:
        command = "subsection"
    elif block.level == 3:
        command = "subsubsection"
    heading = f"\\{command}{{{latex_escape(title)}}}"
    return heading + (f"\n{_text(block.text)}" if block.title and block.text else "")


def _table(block: DraftBlock, *, compact: bool = False) -> str:
    if not block.columns:
        return _text(block.text)
    caption = latex_escape(block.title)
    header = " & ".join(latex_escape(item) for item in block.columns) + r" \\"
    rows = [" & ".join(latex_escape(item) for item in row) + r" \\" for row in block.rows]
    if len(rows) > 24 and len(block.columns) <= 5 and not compact:
        width = max(0.12, 0.9 / len(block.columns))
        spec = "@{}" + "".join(f"p{{{width:.3f}\\linewidth}}" for _ in block.columns) + "@{}"
        lines = [f"\\begin{{longtable}}{{{spec}}}"]
        if caption:
            lines.append(f"\\caption{{{caption}}} \\\\")
        lines.extend(["\\toprule", header, "\\midrule", "\\endfirsthead"])
        lines.extend(["\\toprule", header, "\\midrule", "\\endhead"])
        lines.extend(rows)
        lines.extend(["\\bottomrule", "\\end{longtable}"])
        return "\n".join(lines)
    spec = "@{}" + ("X" * len(block.columns)) + "@{}"
    lines: list[str] = []
    if not compact:
        lines.extend(["\\begin{table}[htbp]", "\\centering"])
        if caption:
            lines.append(f"\\caption{{{caption}}}")
    lines.extend([f"\\begin{{tabularx}}{{\\linewidth}}{{{spec}}}", "\\toprule"])
    lines.append(header)
    lines.append("\\midrule")
    lines.extend(rows)
    lines.extend(["\\bottomrule", "\\end{tabularx}"])
    if not compact:
        lines.append("\\end{table}")
    return "\n".join(lines)


def _equation(value: str) -> str:
    commands = frozenset(_EQUATION_COMMAND.findall(value))
    if not _SAFE_EQUATION.fullmatch(value) or not commands.issubset(_SAFE_EQUATION_COMMANDS):
        raise ValueError("authoring_unsupported")
    return value


def _render_block(
    block: DraftBlock,
    *,
    report: bool,
    article: bool,
    citations: CitationResolver | None,
    enforce_evidence: bool,
) -> str:
    if block.kind == "section":
        return _section(block, report=report, article=article)
    if block.kind == "paragraph":
        return _text(block.text)
    if block.kind == "list":
        items = "\n".join(f"\\item {_text(item)}" for item in block.items)
        return f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}"
    if block.kind == "table":
        return _table(block)
    if block.kind == "figure":
        caption = latex_escape(block.title or block.text)
        path = block.asset_path
        return (
            (
                "\\begin{figure}[ht]\n\\centering\n"
                f"\\includegraphics[width=0.92\\linewidth]{{{path}}}\n"
                f"\\caption{{{caption}}}\n\\end{{figure}}"
            )
            if path
            else f"\\DocumentCallout{{{caption}}}"
        )
    if block.kind == "equation":
        return f"\\begin{{equation}}\n{_equation(block.text)}\n\\end{{equation}}"
    if block.kind == "callout":
        return f"\\begin{{quote}}\\textbf{{{_text(block.text)}}}\\end{{quote}}"
    if block.kind == "signature":
        left = block.items[0] if block.items else "{{PARTY_ONE}}"
        right = block.items[1] if len(block.items) > 1 else "{{PARTY_TWO}}"
        return f"\\SignatureLine{{{latex_escape(left)}}}{{{latex_escape(right)}}}"
    if block.kind == "citation":
        key = citations.key_for(block.source_id) if citations and block.source_id else None
        if key is None:
            if enforce_evidence:
                raise ValueError("citation_unknown")
            return r"\DocumentCallout{Citation source required}"
        prefix = _text(block.text)
        return f"{prefix} \\cite{{{key}}}" if prefix else f"\\cite{{{key}}}"
    if block.kind == "slide":
        body_parts = [_text(block.text)] if block.text else []
        if block.items:
            items = "\n".join(f"\\item {_text(item)}" for item in block.items)
            body_parts.append(f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}")
        if block.columns:
            body_parts.append(_table(block, compact=True))
        if block.asset_path:
            body_parts.append(
                "\\begin{center}\n"
                f"\\includegraphics[width=0.88\\linewidth,height=0.52\\textheight,keepaspectratio]"
                f"{{{block.asset_path}}}\n"
                "\\end{center}"
            )
        if block.source_id is not None:
            key = citations.key_for(block.source_id) if citations else None
            if key is None:
                if enforce_evidence:
                    raise ValueError("citation_unknown")
                body_parts.append(r"\scriptsize Citation source required")
            else:
                body_parts.append(f"\\par\\scriptsize Source: \\cite{{{key}}}")
        return (
            f"\\begin{{frame}}{{{latex_escape(block.title)}}}\n"
            + "\n".join(body_parts)
            + "\n\\end{frame}"
        )
    raise ValueError("authoring_unsupported")


def _trusted_preamble(scaffold: str, title: str) -> str:
    at = scaffold.find(_BEGIN)
    if at < 0 or scaffold.rfind(_END) <= at:
        raise ValueError("invalid_scaffold")
    preamble = scaffold[:at]
    preamble = re.sub(r"\\title\{[^{}]*\}", "", preamble)
    required_packages = ("graphicx", "booktabs", "tabularx", "longtable")
    additions = [
        f"\\usepackage{{{package}}}"
        for package in required_packages
        if not re.search(
            rf"\\usepackage(?:\[[^\]]*\])?\{{[^}}]*\b{package}\b[^}}]*\}}",
            preamble,
        )
    ]
    return preamble.rstrip() + "\n" + "\n".join(additions) + f"\n\\title{{{latex_escape(title)}}}\n"


def _bibliography_commands(intent: DocumentIntent, scaffold: str) -> str:
    if intent.kind == "presentation":
        return (
            "\\begin{frame}[allowframebreaks]{References}\n"
            "\\bibliographystyle{plain}\n"
            "\\bibliography{bibliography/references}\n"
            "\\end{frame}"
        )
    if "biblatex" in scaffold:
        return r"\printbibliography"
    style = {
        "ieee_journal": "IEEEtran",
        "aaai_conference": "plainnat",
    }.get(intent.profile_id, "plain")
    return f"\\bibliographystyle{{{style}}}\n\\bibliography{{bibliography/references}}"


def render_document(
    intent: DocumentIntent,
    draft: DocumentDraft,
    *,
    scaffold_source: str,
    citations: CitationResolver | None = None,
    bibliography: str = "",
    enforce_evidence: bool = True,
) -> RenderedSourceBundle:
    """Render only semantic blocks; class, packages and geometry stay profile-owned."""

    if intent.kind == "unsupported":
        raise ValueError("authoring_unsupported")
    draft = _enforce_required_sections(intent, draft)
    report = intent.kind == "report"
    article = intent.kind == "article"
    if intent.kind == "presentation" and any(block.kind != "slide" for block in draft.blocks):
        raise ValueError("authoring_unsupported")
    block_files: dict[str, str] = {}
    includes: list[str] = []
    provenance: dict[str, str] = {}
    for index, block in enumerate(draft.blocks, 1):
        path = f"content/{index:03d}-{block.block_id}.tex"
        rendered_block = (
            ""
            if article and block.kind == "section" and section_role(block.title) == "references"
            else _render_block(
                block,
                report=report,
                article=article,
                citations=citations,
                enforce_evidence=enforce_evidence,
            )
        )
        block_files[path] = rendered_block + "\n"
        includes.append(f"\\input{{{path}}}\n\\label{{gpthub:block:{block.block_id}}}")
        provenance[path] = block.block_id
    body = "\n".join(includes)
    if intent.literal_text is not None:
        # A literal document is an exact-content artifact, not a miniature
        # article.  The generic scaffold title would add unrequested visible
        # text and the sparse title-plus-paragraph composition is prone to
        # inconsistent visual-audit results.  Keep the editable managed block,
        # but place that block alone on a balanced, unnumbered page.
        body = (
            "\\thispagestyle{empty}\n"
            "\\vspace*{\\fill}\n"
            "\\begin{center}\\Large\n" + body + "\n\\end{center}\n"
            "\\vspace*{\\fill}"
        )
    elif intent.kind != "presentation":
        body = "\\maketitle\n\n" + body
    if intent.requires_bibliography and not bibliography.strip() and enforce_evidence:
        raise ValueError("evidence_required")
    if bibliography.strip() and (intent.requires_bibliography or draft.cited_source_ids):
        body += "\n\n" + _bibliography_commands(intent, scaffold_source)
    main_tex = (
        _trusted_preamble(scaffold_source, draft.title) + _BEGIN + "\n" + body + "\n" + _END + "\n"
    )
    authoring = {
        "schema_version": 1,
        "draft_version": draft.version,
        "draft_digest": draft.digest,
        "draft": draft.payload(),
        "intent_version": intent.schema_version,
        "profile_id": intent.profile_id,
        "intent": {
            "kind": intent.kind,
            "profile_id": intent.profile_id,
            "locale": intent.locale,
            "mode": intent.mode,
            "title": intent.title,
            "audience": intent.audience,
            "length_class": intent.length_class,
            "required_sections": list(intent.required_sections),
            "citation_policy": intent.citation_policy,
            "presentation_density": intent.presentation_density,
            "legal_fields": [
                {"name": item.name, "value": item.value, "required": item.required}
                for item in intent.legal_fields
            ],
            "user_requirements": list(intent.user_requirements),
        },
        "block_files": provenance,
    }
    return RenderedSourceBundle(
        files={
            "main.tex": main_tex,
            "bibliography/references.bib": bibliography.strip()
            + ("\n" if bibliography.strip() else ""),
            ".gpthub-authoring.json": json.dumps(authoring, sort_keys=True, separators=(",", ":")),
            **block_files,
        },
        authoring_version=draft.version,
        draft_digest=draft.digest,
    )


__all__ = ["RenderedSourceBundle", "latex_escape", "render_document"]
