"""Render the checked bibliography identically for draft LaTeX and Biber."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def render_description(value: str) -> str:
    # Biber reads usera as a macro argument before \url runs: protect TeX specials here.
    pieces = re.split(r"(https?://[^\s]+)", value)
    return "".join(
        r"\url{" + escape(piece) + "}" if piece.startswith(("http://", "https://"))
        else escape(piece) for piece in pieces
    )


def main() -> None:
    catalog = json.loads((ROOT / "data/bibliography.json").read_text(encoding="utf-8"))
    entries = catalog["entries"]
    assert len(entries) == catalog["meta"]["count"] == 300
    assert [entry["number"] for entry in entries] == list(range(1, 301))
    assert len({entry["key"] for entry in entries}) == 300
    bib, numbers, items = [], [], []
    for entry in entries:
        description = render_description(entry["description"])
        bib.append(
            "@misc{" + entry["key"] + ",\n  title = {" + escape(entry["title"])
            + "},\n  sortkey = {" + f"{entry['number']:04d}"
            + "},\n  usera = {" + description + "}\n}\n"
        )
        numbers.append(
            r"\expandafter\def\csname bibnumber@" + entry["key"]
            + r"\endcsname{" + str(entry["number"]) + "}"
        )
        items.append(r"\item[" + str(entry["number"]) + ".] " + description)
    outputs = {
        "references.bib": "\n".join(bib),
        "bibliography-numbers.tex": "\n".join(numbers) + "\n",
        "bibliography-draft.tex": (
            "\\begingroup\n\\fontsize{12}{20.7}\\selectfont\n\\raggedright\n"
            "\\begin{list}{}{\\setlength{\\leftmargin}{10mm}"
            "\\setlength{\\labelwidth}{8mm}\\setlength{\\labelsep}{2mm}"
            "\\setlength{\\itemsep}{0pt}\\setlength{\\parsep}{0pt}"
            "\\setlength{\\topsep}{0pt}}\n" + "\n".join(items)
            + "\n\\end{list}\n\\endgroup\n"
        ),
    }
    for name, content in outputs.items():
        (ROOT / "document/backmatter" / name).write_text(
            content, encoding="utf-8", newline="\n",
        )


if __name__ == "__main__":
    main()
