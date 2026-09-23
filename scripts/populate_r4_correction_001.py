"""Correct S060 after the exact JCDR primary article became identifiable."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, canonical

from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-correction-001.json"


def main() -> None:
    decision = canonical(
        "S060",
        "verified_primary",
        "Artificial Intelligence in Spinal Cord Stimulation and Neuromodulation: A Narrative Review of Clinical Applications, Emerging Evidence, and Future Directions",
        "https://www.jcdr.net/article_fulltext.asp?id=24236&issn=0973-709x&issue=9&page=UE01&volume=20&year=2026",
        doi="10.7860/JCDR/2026/86004.24236",
        authors="Chitra Kolla; Sheetal Madavi; Souvik Banik; Dhwani Sheth; Bhagyesh Sapkale",
        source="Journal of Clinical and Diagnostic Research",
        note="Narrative review, not a systematic review or clinical validation study. It explicitly characterizes the AI-SCS evidence as preliminary, heterogeneous, and lacking large prospective multicenter randomized trials.",
        target="scs_response",
        role="context_only",
        risks=["missing_cross_subject_validation"],
        claim="The narrative review maps proposed AI uses across SCS selection, programming and closed-loop control while documenting major validation and governance gaps.",
    )
    payload = {
        "meta": {
            "batch_id": "r4-correction-001",
            "schema_version": "1.2.0",
            "created_at": TODAY,
            "scope": "correction of r4-batch-002 decision after exact primary match",
            "status": "reviewed",
            "reviewed_at": TODAY,
        },
        "source_ids": ["S060"],
        "records": [
            {
                "id": "S060",
                "title": "Integration of AI into SCS: ethical and data-governance challenges",
                "year": 2026,
                "source_type": "XAI_этика",
            }
        ],
        "decisions": [decision],
    }
    atomic_write_json(PATH, payload)
    print({"batch": "r4-correction-001", "decisions": 1})


if __name__ == "__main__":
    main()
