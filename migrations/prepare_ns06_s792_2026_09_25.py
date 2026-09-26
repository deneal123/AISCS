(
    "Prepare the journal extension of the NS-06 pain adaptation family."
)

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / (
                  "data/staging/inbox/S792.json"
              )
DATA = json.loads(PATH.read_text(encoding=(
                                              "utf-8"
                                          )))
KEYS = list(DATA)
THESIS = (
             "https://espace.etsmtl.ca/id/eprint/3267/1/RAJASEKHAR_Gnana_Praveen.pdf"
         )
ETS = (
          "https://pure.etsmtl.ca/en/publications/deep-domain-adaptation-with-ordinal-regression-"
          "for-pain-assessmen/"
      )
ARXIV = (
            "https://arxiv.org/html/2008.06392"
        )

values = {
    2: (
           "Gnana Praveen Rajasekhar; Eric Granger; Patrick Cardinal"
       ),
    3: 2021,
    4: (
           "Image and Vision Computing 110 (June 2021), article 104167"
       ),
    5: (
           "Facial video"
       ),
    6: (
           "Weakly supervised pain intensity estimation with cross-domain adaptation and ordinal "
           "regression"
       ),
    7: (
           "I3D, deep adversarial domain adaptation, multiple-instance regression, Gaussian "
           "ordinal labels, adaptive MIL pooling"
       ),
    8: (
           "RECOLA fully labeled source; UNBC-McMaster weakly labeled target (25 people, 200 "
           "videos, 47,398 frames); BioVid Part A (87 people, 8,700 videos, sequence labels 0-4) "
           "additional target evaluation; private fatigue data are not pain outcomes."
       ),
    9: (
           "UNBC LOSO: 15 train, 9 validation, 1 test participant per fold. BioVid evaluation "
           "randomly holds out 20 of 87 participants. For BioVid sequence-level evaluation, "
           "proposed DA reports PCC 0.341, ICC 0.317, MAE 1.162; comparisons use separate setups."
       ),
    10: (
            "Yes. UNBC uses LOSO by participant; BioVid test uses 20 held-out participants "
            "selected from 87."
        ),
    11: 5,
    12: (
            "This is the ordinal-regression journal extension of the authors' FG 2020 WSDA "
            "paper, not an independent mechanism family. It uses real labeled RECOLA source data "
            "and weak pain labels in target videos; target annotation remains necessary. No "
            "synthetic pain generation or unlabeled-target-only training is shown. Video "
            "expression scores do not establish clinical pain, SCS, or ECAP validity."
        ),
    13: json.loads((ROOT / (
                               "data/vocabularies.json"
                           )).read_text(encoding=(
                                                                            "utf-8"
                                                                        )))[(
                                                                                      "source_type"
                                                                                  )][8],
}
for i, value in values.items():
    DATA[KEYS[i]] = value

DATA[(
         "identifiers"
     )].update(
    {
        (
            "doi"
        ): (
                   "10.1016/j.imavis.2021.104167"
               ),
        (
            "arxiv_id"
        ): (
                        "2008.06392"
                    ),
        (
            "exact_url"
        ): (
                         "https://doi.org/10.1016/j.imavis.2021.104167"
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
                             "NS-06 primary full-text and version-family search"
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
                             "exact title; DOI 10.1016/j.imavis.2021.104167; author Gnana "
                             "Praveen Rajasekhar; arXiv 2008.06392"
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
                          "UNBC-McMaster shoulder-pain archive; RECOLA source participants; "
                          "BioVid Part A participants"
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
                           "UNBC: 25 people, 200 videos, 47,398 frames. BioVid Part A: 87 "
                           "people, 8,700 videos; 20 held out for testing. Fatigue: 18 people, "
                           "27 sessions, non-pain target."
                       ),
        (
            "target_construct"
        ): (
                                "experimental_pain_class"
                            ),
        (
            "target_label"
        ): (
                            "UNBC PSPI frame scores 0-15 quantized to five ordinal levels; "
                            "BioVid pain levels 0-4 assigned at subsequence level"
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
                                   "yes"
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
                     "Full author thesis chapter reproduces the IVC 2021 journal paper and its "
                     "experiments. ETS publisher-affiliated record and arXiv confirm article "
                     "metadata/version. UNBC WSDA-OR reports frame PCC 0.705, ICC 0.696, MAE "
                     "0.530 and sequence PCC 0.745, ICC 0.750, MAE 0.443 (Table 3.3). BioVid "
                     "Part A sequence DA reports PCC 0.341, ICC 0.317, MAE 1.162 (Table 3.4). "
                     "Separate datasets and protocols must not be pooled."
                 ),
    }
)
DATA[(
         "relations"
     )] = [
    {
        (
            "type"
        ): (
                    "version_of"
                ),
        (
            "target_id"
        ): (
                         "S791"
                     ),
        (
            "external_id"
        ): None,
        (
            "note"
        ): (
                    "The author thesis lists both FG 2020 and IVC 2021 papers as outputs of the "
                    "same pain-domain-adaptation contribution; the journal version adds Gaussian "
                    "ordinal regression and adaptive MIL pooling."
                ),
    }
]
DATA[(
         "risk_flags"
     )] = [(
                          "claim_not_supported"
                      )]

resolution_keys = list(DATA[(
                                "field_resolution"
                            )])
primary = (
              "Chapter 3, Sections 3.3-3.4 and Tables 3.1-3.4, pp. 114-132; full author thesis "
              "reproducing the article"
          )
for pos, index in enumerate((2, 3, 4, 5, 6, 7, 8, 9, 10, 12)):
    DATA[(
             "field_resolution"
         )][resolution_keys[pos]].update(
        {
            (
                "state"
            ): (
                         "reported"
                     ),
            (
                "value"
            ): DATA[KEYS[index]],
            (
                "reason"
            ): (
                          "Verified in the full author thesis chapter for this journal article; "
                          "claims retain the study-specific scope."
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
                          ): THESIS, (
                                             "locator"
                                         ): primary}],
        }
    )

for key, value, url, locator in (
    ((
         "identifiers.doi"
     ), DATA[(
                                 "identifiers"
                             )][(
                                                "doi"
                                            )], ETS, (
                                                             "DOI and journal record"
                                                         )),
    (
        (
            "identifiers.arxiv_id"
        ),
        DATA[(
                 "identifiers"
             )][(
                                "arxiv_id"
                            )],
        ARXIV,
        (
            "arXiv record; notes overlap with arXiv:1910.08173"
        ),
    ),
    ((
         "identifiers.exact_url"
     ), DATA[(
                                       "identifiers"
                                   )][(
                                                      "exact_url"
                                                  )], ETS, (
                                                                         "DOI identifier"
                                                                     )),
    ((
         "evidence.species"
     ), (
                             "Homo sapiens"
                         ), THESIS, (
                                                     "Chapter 3, Section 3.4"
                                                 )),
    (
        (
            "evidence.population"
        ),
        DATA[(
                 "evidence"
             )][(
                             "population"
                         )],
        THESIS,
        (
            "Chapter 3, Sections 3.4.1 and 3.4.6"
        ),
    ),
    (
        (
            "evidence.sample_size"
        ),
        DATA[(
                 "evidence"
             )][(
                             "sample_size"
                         )],
        THESIS,
        (
            "Chapter 3, Sections 3.4.1 and 3.4.6"
        ),
    ),
    (
        (
            "evidence.target_label"
        ),
        DATA[(
                 "evidence"
             )][(
                             "target_label"
                         )],
        THESIS,
        (
            "Chapter 3, Sections 3.4.1 and 3.4.6"
        ),
    ),
    ((
         "validation.notes"
     ), DATA[(
                                  "validation"
                              )][(
                                                "notes"
                                            )], THESIS, (
                                                                  "Chapter 3, Tables 3.3-3.4"
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
                          "Confirmed by a primary or publisher-affiliated bibliographic source "
                          "and the author's full thesis chapter."
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
                          ): url, (
                                          "locator"
                                      ): locator}],
        }
    )

PATH.write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + (
                                                                     "\n"
                                                                 ), encoding=(
                                                                                    "utf-8"
                                                                                ))
