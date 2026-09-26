"""Resolve S148 article locator against the deposited primary JATS record."""

# ruff: noqa: E501 -- exact source locators and audit decisions are preserved.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
JATS = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13367641/fullTextXML"
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/42454002/"
DOI = "https://api.crossref.org/works/10.2147%2FJPR.S617733"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    retry = json.loads((DATA / "src07-crossref-retry-2026-09-25.json").read_text(encoding="utf-8"))
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    source = next(s for s in records["sources"] if s["id"] == "S148")
    assert source["identifiers"]["doi"] == "10.2147/JPR.S617733"
    assert source["издание"] == "Journal of Pain Research"
    citation = "Journal of Pain Research 19:617733"
    source["издание"] = citation
    field = source["field_resolution"]["издание"]
    field.update({
        "state": "reported", "value": citation,
        "reason": "Deposited primary JATS specifies volume 19 and elocation 617733; PubMed displays 19:617733. Crossref separately reports page 1-18; its meaning is unresolved.",
        "checked_at": DATE,
        "locators": [
            {"url": JATS, "locator": "front/article-meta/volume=19 and elocation-id=617733"},
            {"url": PUBMED, "locator": "Citation: 2026 Jul 10;19:617733"},
            {"url": DOI, "locator": "message.volume='Volume 19'; message.page='1-18'"},
        ],
    })
    flag = next(f for f in retry["manual_review_flags"] if f["source_id"] == "S148")
    assert flag["status"] == "edition_not_applied"
    flag.update({
        "status": "resolved_primary_article_identifier",
        "boundary": "JATS and PubMed identify 19:617733; Crossref separately reports page 1-18, whose meaning remains unresolved. Do not substitute it for the article identifier.",
        "locators": field["locators"],
    })
    retry["meta"]["reviewed_edition_updates"] += 1
    note = {
        "source_id": "S148", "checked_at": DATE,
        "decision": "Use primary JATS/PubMed volume 19, article identifier 617733; retain Crossref page 1-18 as unresolved conflicting metadata.",
        "locators": field["locators"],
        "remaining": "SRC-07 full 2026 corpus and later dated refresh remain open.",
    }
    needle = "- [ ] **SRC-08.**"
    assert todo.count(needle) == 1
    todo = todo.replace(needle, "  Для `S148` сверены JATS и PubMed: Journal of Pain Research 19:617733; Crossref отдельно сообщает `1–18`, смысл этой пагинации не установлен. Библиография исправлена, конфликт метаданных сохранён (`data/src07-s148-citation-resolution-2026-09-25.json`). Общий `SRC-07` остаётся открытым.\n" + needle)
    readme = readme.replace("- `archive/`", "- `src07-s148-citation-resolution-2026-09-25.json` — JATS/PubMed article identifier and unresolved Crossref page metadata;\n- `archive/`")
    if not args.apply:
        print("Dry run: S148 19:617733; Crossref page metadata retained separately")
        return
    snapshot = snapshot_repository(DATA, label="pre-s148-citation-resolution")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-crossref-retry-2026-09-25.json", retry)
    atomic_write_json(DATA / "src07-s148-citation-resolution-2026-09-25.json", note)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Resolved S148 primary citation; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
