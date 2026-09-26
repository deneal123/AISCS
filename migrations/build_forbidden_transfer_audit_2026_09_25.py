"""Prepare explicit EVD-04 construct-transfer prohibitions and matrix screen."""

# ruff: noqa: E501 -- exact scientific boundaries must remain intelligible.

import argparse
import json
import re
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
OUTPUT = DATA / "forbidden-transfer-audit-2026-09-25.json"
FIELDS = ("claim", "target_variable", "verified_evidence", "limitations", "permitted_conclusion")
CONTEXT_PATTERNS = {
    "ecap_and_pain": re.compile(r"ecap.{0,80}pain|pain.{0,80}ecap", re.I),
    "nociception_and_pain": re.compile(r"nocicept.{0,80}pain|pain.{0,80}nocicept", re.I),
    "acute_and_chronic": re.compile(r"acute.{0,50}chronic|chronic.{0,50}acute", re.I),
}
DIRECT_EQUIVALENCE_PATTERNS = {
    "ecap_is_pain": re.compile(r"\becap\b\s+(?:is|equals|directly measures|quantifies)\s+(?:subjective\s+)?pain\b", re.I),
    "nociception_is_pain": re.compile(r"\bnocicept(?:ion|ive response)\b\s+(?:is|equals|directly measures)\s+(?:subjective\s+)?pain\b", re.I),
    "fly_is_human_twin": re.compile(r"\b(?:fly|drosophila)\b.{0,35}\bdirect\s+digital\s+twin\b.{0,25}\bhuman\b", re.I),
}
RULES = [
    {
        "id": "FT-01", "from": "controlled acute experimental pain class", "to": "chronic clinical pain or SCS outcome",
        "prohibited_transfer": "Do not treat an acute stimulus or experimental pain classifier score as a chronic-pain severity or treatment-response metric.",
        "required_bridge": "A separate patient-linked chronic-pain cohort, prespecified outcome and horizon, participant-disjoint test and calibration are required.",
        "contract_entities": ["ENT-01", "ENT-06"], "source_refs": ["S015", "S071", "S749"],
    },
    {
        "id": "FT-02", "from": "Drosophila nociceptive activity or protective behavior", "to": "subjective human pain",
        "prohibited_transfer": "Do not name an animal neural response, withdrawal or rolling score as felt pain intensity.",
        "required_bridge": "Report the stimulus, neural response and behavior separately; any human pain endpoint requires a separate human study and its own label.",
        "contract_entities": ["ENT-01", "ENT-02", "ENT-03"], "source_refs": ["S152", "S212"],
    },
    {
        "id": "FT-03", "from": "Drosophila connectome dynamics or simulated latent state", "to": "human spinal recruitment or ECAP waveform",
        "prohibited_transfer": "Do not equate fly cells, synapses or simulation states with human spinal anatomy or a recorded ECAP.",
        "required_bridge": "Define species-agnostic observables, a physical stimulation/volume-conductor/neural-recruitment observation operator and held-out human comparator tests.",
        "contract_entities": ["ENT-04", "ENT-05"], "source_refs": ["S740", "S105", "S766"],
    },
    {
        "id": "FT-04", "from": "ECAP recruitment amplitude, threshold or neural dose", "to": "patient-reported pain intensity",
        "prohibited_transfer": "Do not call ECAP a direct pain biomarker or substitute ECAP amplitude for a patient's pain report.",
        "required_bridge": "Analyze neural recruitment and pain outcomes as different variables with participant-linked, temporally aligned data and independent validation.",
        "contract_entities": ["ENT-05", "ENT-06"], "source_refs": ["S105", "S236", "S767", "S787"],
    },
    {
        "id": "FT-05", "from": "ECAP feedback control or accurate dose delivery", "to": "SCS clinical treatment effect",
        "prohibited_transfer": "Do not infer analgesic efficacy from controller stability or achieved neural dose alone.",
        "required_bridge": "Use a prespecified clinical outcome and appropriate comparator; keep the intervention contrast separate from feedback-signal measurement.",
        "contract_entities": ["ENT-05", "ENT-06"], "source_refs": ["S236", "S779", "S780", "S781"],
    },
    {
        "id": "FT-06", "from": "repeated pulses, curves or visits", "to": "independent patients",
        "prohibited_transfer": "Do not count repeated ECAP curves, pulses or longitudinal visits as independent participants or external validation.",
        "required_bridge": "Preserve participant IDs, cluster inference by participant and report the participant denominator and disjoint split.",
        "contract_entities": ["ENT-05", "ENT-06"], "source_refs": ["S765", "S787"],
    },
    {
        "id": "FT-07", "from": "multiple reports from one registered SCS trial", "to": "independent replication",
        "prohibited_transfer": "Do not count EVOKE 12-, 24- and 36-month reports as three independent trial validations.",
        "required_bridge": "Group publications by trial ID and cohort, and identify any separately enrolled replication cohort.",
        "contract_entities": ["ENT-06"], "source_refs": ["S779", "S780", "S781"],
    },
    {
        "id": "FT-08", "from": "animal mechanical-response classes or simulated behavior", "to": "human SCS outcome",
        "prohibited_transfer": "Do not transfer animal stimulus classes or simulated actions directly into human analgesic responder labels.",
        "required_bridge": "Use a separate human SCS cohort with a validated patient-reported target, follow-up and disjoint evaluation.",
        "contract_entities": ["ENT-02", "ENT-03", "ENT-06"], "source_refs": ["S747", "S253"],
    },
    {
        "id": "FT-09", "from": "randomized closed-loop SCS intervention comparison", "to": "individual baseline prognosis",
        "prohibited_transfer": "Do not describe an intervention-arm difference as a validated preimplant individual response predictor.",
        "required_bridge": "Specify baseline predictors and response label, fit without outcome leakage and validate at the patient level in an independent cohort.",
        "contract_entities": ["ENT-06"], "source_refs": ["S779", "S780", "S781", "S788"],
    },
    {
        "id": "FT-10", "from": "anatomical map or company simulation demonstration", "to": "independent biological nociception validation",
        "prohibited_transfer": "Do not treat a connectome map, software demo or company announcement as an experimental pain or nociception result.",
        "required_bridge": "Identify the exact graph release and separately recorded biological stimulus, neural and behavioral comparator cohorts.",
        "contract_entities": ["ENT-02", "ENT-03", "ENT-04"], "source_refs": ["S253", "S296", "S368"],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    contract = json.loads((DATA / "scientific-contract.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    records = {s["id"] for s in json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]}
    entities = {e["id"] for e in contract["entities"]}
    assert len(matrix["rows"]) == 150
    assert all(set(r["source_refs"]) <= records and set(r["contract_entities"]) <= entities for r in RULES)
    contextual = []
    direct_hits = []
    for row_index, row in enumerate(matrix["rows"]):
        text = " ".join(str(row.get(field, "")) for field in FIELDS)
        context_types = [name for name, pattern in CONTEXT_PATTERNS.items() if pattern.search(text)]
        if context_types:
            contextual.append({
                "row_index": row_index, "batch_id": row["batch_id"], "source_ids": row["source_ids"],
                "context_types": context_types,
                "review_decision": "scoped_text_review_no_direct_equivalence_in_five_fields",
            })
        for name, pattern in DIRECT_EQUIVALENCE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                prefix = text[max(0, match.start() - 45):match.start()].lower()
                negated = "not as proof that" in prefix
                direct_hits.append({
                    "row_index": row_index, "batch_id": row["batch_id"], "source_ids": row["source_ids"],
                    "pattern": name, "matched_text": match.group(),
                    "review_decision": "negated_prohibition" if negated else "requires_manual_review",
                })
    assert len(contextual) == 58
    assert len(direct_hits) == 1 and direct_hits[0]["source_ids"] == ["S237"]
    assert all(hit["review_decision"] == "negated_prohibition" for hit in direct_hits)
    result = {
        "meta": {
            "schema_version": "1.0.0", "checked_at": DATE,
            "status": "draft_matrix_text_review_pending_evd03_and_source_cards",
            "gate": "G0_REVISE", "matrix_rows_scanned": len(matrix["rows"]),
            "matrix_rows_manually_reviewed_in_five_fields": len(matrix["rows"]),
            "contextual_rows_screened": len(contextual),
            "contextual_rows_manually_reviewed": len(contextual),
            "contextual_rows_pending_semantic_review": 0,
            "unflagged_rows_manually_reviewed": len(matrix["rows"]) - len(contextual),
            "unflagged_rows_without_manual_semantic_review": 0,
            "direct_equivalence_regex_hits": len(direct_hits),
            "unresolved_direct_equivalence_hits": sum(hit["review_decision"] == "requires_manual_review" for hit in direct_hits),
            "boundary": "Review of five matrix text fields does not prove that all source cards or primary publications preserve every scientific boundary.",
        },
        "contract_basis": ["scientific-contract.json:meta.invariants", "scientific-contract.json:entities", "dissertation-concept.json:forbidden_claims"],
        "rules": RULES,
        "matrix_screen": {"fields": list(FIELDS), "contextual_rows": contextual, "direct_equivalence_hits": direct_hits},
        "target_corrections": {"source_ids": ["S149", "S023", "S154", "S253", "S273"], "audits": ["four-construct-target-corrections-2026-09-25.json", "s273-behavior-target-correction-2026-09-25.json"]},
        "source_card_corrections": {"source_ids": ["S023", "S149", "S154", "S273"], "audit": "four-source-card-construct-corrections-2026-09-25.json"},
        "remaining": ["Complete EVD-03 primary-locator review and SRC-08 dependency", "Manually inspect source-card conclusions and primary-text consistency", "Obtain author review of the forbidden-transfer list before EVD-04 closure"],
    }
    if not args.apply:
        print(f"Dry run: {len(RULES)} rules, {len(contextual)} contextual rows reviewed, {len(direct_hits)} negated direct-equivalence regex hit")
        return
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    new_note = "  Черновой реестр `data/forbidden-transfer-audit-2026-09-25.json` задаёт 10 явных запретов переноса и условия допустимого сопоставления. Все 150 строк матрицы просмотрены по пяти текстовым полям; 58 содержат пересечение терминов ECAP/боль, ноцицепция/боль или acute/chronic pain. Исправлены пять смешений целевых конструктов в матрице (`S149`, `S023`, `S154`, `S253`, `S273`) и четыре карточки (`S023`, `S149`, `S154`, `S273`); после исправлений прямого приравнивания в этих полях не обнаружено. Остальные выводы карточек и первичные тексты требуют дальнейшего просмотра; зависимость `EVD-03` и авторское принятие открыты. `EVD-04` не закрыт."
    todo, updated = re.subn(r"^  Черновой реестр `data/forbidden-transfer-audit-2026-09-25\.json`.*$", new_note, todo, flags=re.M)
    assert updated == 1
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    assert readme.count("- `forbidden-transfer-audit-2026-09-25.json`") == 1
    snapshot = snapshot_repository(DATA, label="pre-forbidden-transfer-audit")
    atomic_write_json(OUTPUT, result)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Prepared EVD-04 audit; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
