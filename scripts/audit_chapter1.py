"""Check the bounded review, bibliography and imported evidence independently."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> None:
    proof = read_json("data/chapter1-evidence.json")
    meta = proof["meta"]
    path = ROOT / meta["chapter"]
    chapter = path.read_text(encoding="utf-8")
    assert sha256(path) == meta["chapter_sha256"], "Stale chapter evidence map"
    assert sha256(ROOT / "data/bibliography.json") == meta["bibliography_sha256"]
    assert sha256(ROOT / "data/research-snapshot/snapshot.json") == meta["snapshot_sha256"]
    entries = read_json("data/bibliography.json")["entries"]
    by_key = {entry["key"]: entry for entry in entries}
    assert len(entries) == len(by_key) == 300
    assert [entry["number"] for entry in entries] == list(range(1, 301))
    assert by_key["ecapmodel"]["number"] == 122
    assert by_key["posture"]["number"] == 121
    groups = re.findall(r"\\cite\{([^}]+)\}", chapter)
    keys = {key.strip() for group in groups for key in group.split(",")}
    assert keys <= by_key.keys(), "Unresolved citation"
    refs = {by_key[key]["id"] for key in keys}
    assert len(refs) == meta["source_count"] == 38
    assert refs == {source["id"] for source in proof["sources"]}
    snapshot = read_json("data/research-snapshot/snapshot.json")
    snapshot_sources = {source["id"]: source for source in snapshot["sources"]}
    assert refs <= set(snapshot["selected_refs"])
    for source in snapshot["sources"]:
        material = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(material).hexdigest().upper() == snapshot["item_hashes"][source["id"]]
    for source in proof["sources"]:
        assert source["validation"]["status"] != "rejected"
        record = snapshot_sources[source["id"]]
        assert source["validation"] == record["validation"]
        assert all(record[key] == value for key, value in source["record_evidence"].items())
        assert source["primary_locators"]
        assert any(
            urlsplit(locator.get("url", "")).scheme in {"http", "https"}
            for locator in source["primary_locators"]
        )
    for context in proof["retrieval"]["reread_registered_contexts"]:
        assert sha256_bytes(context["excerpt"]) == context["excerpt_sha256"]
        assert context["generation"] == meta["generation"]
    assert proof["retrieval"]["unreviewed_included"] is False
    assert all(
        query["generation"] == meta["generation"]
        and not query["errors"]
        and query["mode"] == "hybrid"
        for query in proof["retrieval"]["queries"]
    )
    headings = re.findall(r"\\section\{([^}]+)\}", chapter)
    assert headings == [item["title"] for item in proof["section_map"]]
    assert len(headings) == 6
    ipr = ROOT.parent / "docs/material/IPR_chistovoi-tekst_2026-2030.md"
    if ipr.is_file():
        assert sha256(ipr) == meta["ipr_sha256"], "The IPR changed after this review"
        ipr_text = ipr.read_text(encoding="utf-8")
        assert all(heading in ipr_text for heading in headings)
    assert len(re.findall(r"\\subsection\{", chapter)) == 12
    assert "\\ResultPending" not in chapter
    assert len(re.findall(r"\\begin\{longtable\}", chapter)) == 5
    assert len(re.findall(r"\\begin\{figure\}", chapter)) == 1
    assert len(re.findall(r"\\begin\{equation\}", chapter)) == 5
    labels = re.findall(r"\\label\{([^}]+)\}", chapter)
    assert len(labels) == len(set(labels))
    for label in labels:
        if label.startswith(("tab:", "fig:", "eq:")):
            assert re.search(r"\\(?:eq)?ref\{" + re.escape(label) + r"\}", chapter)
    illustrations = (ROOT / "document/backmatter/illustrations.tex").read_text(encoding="utf-8")
    assert all(label in illustrations for label in labels if label.startswith(("tab:", "fig:")))
    # The six tasks must stay aligned with the governing IPR, not just retain a count.
    introduction = (ROOT / "document/chapters/00-introduction.tex").read_text(encoding="utf-8")
    tasks = re.findall(r"\\item (.+)", introduction)
    assert len(tasks) == 6
    if ipr.is_file():
        ipr_tasks = re.findall(r"^[1-6]\. (.+)$", ipr_text, re.MULTILINE)
        assert tasks == ipr_tasks, "Introduction tasks drifted from the IPR"
    all_tex = "\n".join(
        item.read_text(encoding="utf-8")
        for item in (ROOT / "document").rglob("*.tex")
        if "build" not in item.relative_to(ROOT / "document").parts
    )
    all_labels = re.findall(r"\\label\{([^}]+)\}", all_tex)
    all_refs = re.findall(r"\\(?:eqref|pageref|ref)\{([^}]+)\}", all_tex)
    assert set(all_refs) <= set(all_labels), "Unresolved source cross-reference"
    assert len(all_labels) == len(set(all_labels)), "Duplicate source labels"
    for group in re.findall(r"\\cite\{([^}]+)\}", all_tex):
        assert all(key.strip() in by_key for key in group.split(","))
    appendices = (ROOT / "document/backmatter/appendices.tex").read_text(encoding="utf-8")
    appendix_tables = re.findall(r"\\label\{(tab:[^}]+)\}", appendices)
    assert len(appendix_tables) == 3
    assert all(label in illustrations for label in appendix_tables)
    assert len(re.findall(r"\\item\b", chapter.split("\\section*{Выводы по главе}")[-1])) == 6
    numbers = (ROOT / "document/backmatter/bibliography-numbers.tex").read_text(encoding="utf-8")
    bib = (ROOT / "document/backmatter/references.bib").read_text(encoding="utf-8")
    draft = (ROOT / "document/backmatter/bibliography-draft.tex").read_text(encoding="utf-8")
    for entry in entries:
        assert f"bibnumber@{entry['key']}\\endcsname{{{entry['number']}}}" in numbers
        assert f"@misc{{{entry['key']}," in bib
        assert f"\\item[{entry['number']}.]" in draft
        if " // " in entry["description"]:
            description = entry["description"]
            assert description.index("Текст : электронный") < description.index(" // ")
    print(
        json.dumps(
            {
                "ok": True,
                "sections": 6,
                "sources": len(refs),
                "citation_groups": len(groups),
                "tables": 5,
                "figures": 1,
                "equations": 5,
                "bibliography": 300,
            },
            ensure_ascii=False,
        )
    )


def sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


if __name__ == "__main__":
    main()
