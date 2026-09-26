(
    "Prepare an NS-06 candidate for FG 2020 pain domain-adaptation prior art."
)

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / (
                       "data/staging/inbox/S791.json"
                   )
SOURCE = (
             "https://arxiv.org/html/1910.08173v1"
         )
DATA = json.loads(CANDIDATE.read_text(encoding=(
                                                   "utf-8"
                                               )))
KEYS = list(DATA)

# The canonical schema has legacy Russian field names. Use their generated order
# so this preparation script remains ASCII-safe in Windows PowerShell too.
values = {
    2: (
           "R. Gnana Praveen; Eric Granger; Patrick Cardinal"
       ),
    3: 2020,
    4: (
           "2020 15th IEEE International Conference on Automatic Face and Gesture Recognition "
           "(FG), pp. 473-480; arXiv:1910.08173"
       ),
    5: (
           "Facial video"
       ),
    6: (
           "Weakly supervised cross-domain pain-intensity localization from facial video; "
           "transfer from RECOLA to UNBC-McMaster"
       ),
    7: (
           "I3D, multiple-instance learning, adversarial weakly supervised domain adaptation; "
           "source, target and domain losses"
       ),
    8: (
           "Fully labeled RECOLA source videos; weakly labeled UNBC-McMaster target videos. "
           "UNBC: 25 participants, 200 videos, 47,398 frames."
       ),
    9: (
           "LOSO reported: 15 train, 9 validation, 1 test subject each fold; separate "
           "one-target-subject experiment. Tables I-II report differing PCC/MAE setups; do not "
           "combine."
       ),
    10: (
            "Yes: UNBC leave-one-subject-out is reported; a separate one-target-subject "
            "experiment is also described."
        ),
    11: 5,
    12: (
            "No synthetic pain generation. Transfers real fully labeled RECOLA source video to "
            "weakly labeled UNBC target video. Pain-domain-adaptation prior art, distinct from "
            "S149 synthetic-source unlabeled-target adaptation; facial video results do not "
            "validate SCS/ECAP."
        ),
    13: json.loads((ROOT / (
                               "data/vocabularies.json"
                           )).read_text(encoding=(
                                                                            "utf-8"
                                                                        )))[(
                                                                                      "source_type"
                                                                                  )][8],
}
for index, value in values.items():
    DATA[KEYS[index]] = value

DATA[(
         "identifiers"
     )].update(
    {
        (
            "doi"
        ): (
                   "10.1109/FG47880.2020.00139"
               ),
        (
            "arxiv_id"
        ): (
                        "1910.08173"
                    ),
        (
            "exact_url"
        ): (
                         "https://doi.org/10.1109/FG47880.2020.00139"
                     ),
    }
)
DATA[(
         "provenance"
     )].update(
    {
        (
            "import_source"
        ): (
                             "NS-06 primary full-text search"
                         ),
        (
            "retrieved_at"
        ): (
                            "2026-09-25"
                        ),
        (
            "search_stream"
        ): (
                             "NS-06 synthetic pain/domain adaptation"
                         ),
        (
            "query_or_seed"
        ): (
                             "pain domain adaptation synthetic pain; exact-title search: Deep "
                             "Weakly-Supervised Domain Adaptation for Pain Localization in Videos"
                         ),
        (
            "iteration"
        ): 1,
    }
)
DATA[(
         "evidence"
     )].update(
    {
        (
            "species"
        ): (
                       "Homo sapiens"
                   ),
        (
            "population"
        ): (
                          "RECOLA source-video participants and UNBC-McMaster shoulder-pain "
                          "archive participants"
                      ),
        (
            "subject_domain"
        ): (
                              "mixed"
                          ),
        (
            "modalities"
        ): [(
                           "video_face"
                       )],
        (
            "sample_size"
        ): (
                           "UNBC: 25 participants, 200 videos, 47,398 frames. RECOLA N not "
                           "reported in reviewed text."
                       ),
        (
            "target_construct"
        ): (
                                "experimental_pain_class"
                            ),
        (
            "target_label"
        ): (
                            "Frame-level PSPI 0-15, quantized to five ordinal levels; weak "
                            "sequence labels for target-domain training"
                        ),
        (
            "access_status"
        ): (
                             "open"
                         ),
        (
            "evidence_role"
        ): (
                             "method_baseline"
                         ),
    }
)
DATA[(
         "validation"
     )].update(
    {
        (
            "status"
        ): (
                      "verified_primary"
                  ),
        (
            "screening_status"
        ): (
                                "included_core"
                            ),
        (
            "full_text_status"
        ): (
                                "checked"
                            ),
        (
            "checked_at"
        ): (
                          "2026-09-25"
                      ),
        (
            "split_unit"
        ): (
                          "participant"
                      ),
        (
            "cross_subject"
        ): (
                             "yes"
                         ),
        (
            "external_validation"
        ): (
                                   "no"
                               ),
        (
            "calibration"
        ): (
                           "not_reported"
                       ),
        (
            "uncertainty"
        ): (
                           "not_reported"
                       ),
        (
            "notes"
        ): (
                     "ArXiv full text: source=fully labeled RECOLA, target=weakly labeled UNBC. "
                     "Table I is a one-target-subject experiment; Table II reports separate "
                     "frame and sequence metrics. No synthetic pain."
                 ),
    }
)
DATA[(
         "risk_flags"
     )] = [(
                          "claim_not_supported"
                      )]

resolution_keys = list(DATA[(
                                "field_resolution"
                            )])
for position, data_key in enumerate((2, 3, 4, 5, 6, 7, 8, 9, 10, 12)):
    DATA[(
             "field_resolution"
         )][resolution_keys[position]].update(
        {
            (
                "state"
            ): (
                         "reported"
                     ),
            (
                "value"
            ): DATA[KEYS[data_key]],
            (
                "reason"
            ): (
                          "Verified in the primary author full text; value limited to its "
                          "reported scope."
                      ),
            (
                "checked_at"
            ): (
                              "2026-09-25"
                          ),
            (
                "locators"
            ): [{(
                              "url"
                          ): SOURCE, (
                                             "locator"
                                         ): (
                                                        "Sections III-A-III-B and IV-A-IV-B"
                                                    )}],
        }
    )

for key, value, locator in (
    ((
         "evidence.species"
     ), (
                             "Homo sapiens"
                         ), (
                                             "Section IV-A"
                                         )),
    ((
         "evidence.population"
     ), DATA[(
                                     "evidence"
                                 )][(
                                                 "population"
                                             )], (
                                                                "Abstract and Section IV-A"
                                                            )),
    ((
         "evidence.sample_size"
     ), DATA[(
                                      "evidence"
                                  )][(
                                                  "sample_size"
                                              )], (
                                                                  "Section IV-A"
                                                              )),
    ((
         "evidence.target_label"
     ), DATA[(
                                       "evidence"
                                   )][(
                                                   "target_label"
                                               )], (
                                                                    "Sections III-A and IV-A"
                                                                )),
):
    DATA[(
             "field_resolution"
         )][key].update(
        {
            (
                "state"
            ): (
                         "reported"
                     ),
            (
                "value"
            ): value,
            (
                "reason"
            ): (
                          "Reported in the primary full text."
                      ),
            (
                "checked_at"
            ): (
                              "2026-09-25"
                          ),
            (
                "locators"
            ): [{(
                              "url"
                          ): SOURCE, (
                                             "locator"
                                         ): locator}],
        }
    )

DATA[(
         "field_resolution"
     )][(
                             "validation.notes"
                         )].update(
    {
        (
            "state"
        ): (
                     "reported"
                 ),
        (
            "value"
        ): DATA[(
                          "validation"
                      )][(
                                        "notes"
                                    )],
        (
            "reason"
        ): (
                      "Summary of the primary full text and metric-scope limitation."
                  ),
        (
            "checked_at"
        ): (
                          "2026-09-25"
                      ),
        (
            "locators"
        ): [{(
                          "url"
                      ): SOURCE, (
                                         "locator"
                                     ): (
                                                    "Sections IV-A-IV-B, Tables I-II"
                                                )}],
    }
)
CANDIDATE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + (
                                                                          "\n"
                                                                      ), encoding=(
                                                                                         "utf-8"
                                                                                     ))
