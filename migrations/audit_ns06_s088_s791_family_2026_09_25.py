(
    "Record the S088 access limits and the newly verified pain-adaptation family."
)

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / (
                  "data/ns06-prior-art-audit.json"
              )
DATA = json.loads(PATH.read_text(encoding=(
                                              "utf-8"
                                          )))
S088 = next(x for x in DATA[(
                                "analogue_decisions"
                            )] if x[(
                                                           "source_id"
                                                       )] == (
                                                                           "S088"
                                                                       ))
S088.update(
    {
        (
            "mechanism"
        ): (
                         "Third-party Semantic Scholar abstract reports four physiological "
                         "channels (skin temperature, EDA, ECG, EMG), DANN plus cross-attention "
                         "Transformer, supervised contrastive warmup and test-time augmentation; "
                         "source=PainMonit with labels, target=BioVid without labels. Full paper "
                         "protocol remains inaccessible."
                     ),
        (
            "relation_to_s149"
        ): (
                                "Secondary abstract indicates real labeled-source to real "
                                "unlabeled-target adaptation, not an entirely synthetic pain "
                                "source. It remains distinct from S149 diffusion-generated "
                                "multimodal source plus contrastive/adversarial/consistency "
                                "alignment. Details below are index-reported, not "
                                "primary-verified."
                            ),
        (
            "certainty"
        ): (
                         "primary_metadata_secondary_abstract"
                     ),
    }
)
S088[(
         "secondary_abstract_review"
     )] = {
    (
        "checked_at"
    ): (
                      "2026-09-25"
                  ),
    (
        "primary_access"
    ): {
        (
            "crossref"
        ): {
            (
                "url"
            ): (
                       "https://api.crossref.org/works/10.1109/ISDA70544.2026.11606012"
                   ),
            (
                "result"
            ): (
                          "HTTP 200 metadata; exact title, authors, venue and pages; no "
                          "abstract; PDF link marked similarity-checking."
                      ),
        },
        (
            "publisher_document"
        ): {
            (
                "url"
            ): (
                       "https://ieeexplore.ieee.org/document/11606012/"
                   ),
            (
                "result"
            ): (
                          "HTTP 202 with empty body; direct and slash URL both returned 0 bytes."
                      ),
        },
        (
            "publisher_pdf"
        ): {
            (
                "url"
            ): (
                       "https://ieeexplore.ieee.org/ielx8/11605974/11605976/11606012.pdf?arnumber"
                       "=11606012"
                   ),
            (
                "result"
            ): (
                          "HTTP 418 access/bot challenge. Crossref-listed xplorestaging PDF also "
                          "returned HTTP 418."
                      ),
        },
        (
            "author_copy_search"
        ): {
            (
                "locators"
            ): [
                (
                    "https://arxiv.org/search/?query=10.1109%2FISDA70544.2026.11606012&searchtype"
                    "=all"
                ),
                (
                    "https://github.com/SamiaBCH"
                ),
                (
                    "https://r.jina.ai/https://ieeexplore.ieee.org/document/11606012/"
                ),
            ],
            (
                "result"
            ): (
                          "No author manuscript found in bounded arXiv/GitHub/repository search. "
                          "Jina proxy returned landing page and contents headings, but the PDF "
                          "reports access denied and no methods text was obtained. CORE returned "
                          "429 and BASE denied this environment; absence claims remain bounded."
                      ),
        },
    },
    (
        "secondary_index"
    ): {
        (
            "url"
        ): (
                   "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/ISDA70544.2026.116"
                   "06012"
               ),
        (
            "result"
        ): (
                      "HTTP 200, abstract available; index labels paper closed access. The "
                      "abstract reports skin temperature, EDA, ECG, EMG; DANN/cross-attention "
                      "Transformer; 20-epoch supervised contrastive warmup; Focal/ordinal loss, "
                      "weighted sampling, and threshold-calibrated test-time augmentation; "
                      "PainMonit labeled source to BioVid unlabeled target."
                  ),
        (
            "limit"
        ): (
                     "Third-party abstract only, not checked against version-of-record full "
                     "text. Do not treat its metrics, split, cohort, or implementation details "
                     "as primary-verified."
                 ),
    },
    (
        "decision"
    ): (
                    "Full primary methods remain unavailable. Replace title_only with "
                    "metadata_plus_secondary_abstract; retain protocol metrics and cohort "
                    "details as unverified and preserve the synthetic-source distinction from "
                    "S149."
                ),
}

family_entry = {
    (
        "source_id"
    ): (
                     "S791"
                 ),
    (
        "related_version_ids"
    ): [(
                                "S792"
                            )],
    (
        "family"
    ): (
                  "Praveen-Rajasekhar / Granger / Cardinal pain-domain adaptation family"
              ),
    (
        "mechanism"
    ): (
                     "FG 2020 WSDA: I3D plus multiple-instance learning and adversarial domain "
                     "adaptation; fully labeled real RECOLA source to weakly labeled real "
                     "UNBC-McMaster target. The 2021 IVC version S792 adds Gaussian "
                     "ordinal-label modeling and adaptive MIL pooling; the authors report "
                     "additional BioVid Part A evaluation."
                 ),
    (
        "relation_to_s149"
    ): (
                            "Direct pain-domain-adaptation prior art, but no synthetic pain "
                            "generation and no unlabeled-only target protocol. Target pain "
                            "labels are required (weak sequence labels), so it is "
                            "mechanistically distinct from S149 synthetic-source UDA while "
                            "precluding novelty claims around pain-domain adaptation alone."
                        ),
    (
        "certainty"
    ): (
                     "primary_full_text_and_author_version_family"
                 ),
    (
        "locator"
    ): {
        (
            "url"
        ): (
                   "https://arxiv.org/html/1910.08173v1"
               ),
        (
            "section"
        ): (
                       "Sections III-A-III-B and IV-A-IV-B; primary author manuscript accepted "
                       "in FG 2020"
                   ),
    },
    (
        "locators"
    ): [
        {
            (
                "url"
            ): (
                       "https://arxiv.org/html/1910.08173v1"
                   ),
            (
                "section"
            ): (
                           "Abstract; Sections III-A-III-B and IV-A-IV-B; accepted in FG 2020"
                       ),
        },
        {
            (
                "url"
            ): (
                       "https://arxiv.org/abs/1910.08173"
                   ),
            (
                "section"
            ): (
                           "arXiv metadata confirms FG 2020 acceptance; submitted 2019-10-17"
                       ),
        },
        {
            (
                "url"
            ): (
                       "https://arxiv.org/abs/2008.06392"
                   ),
            (
                "section"
            ): (
                           "arXiv v3 abstract notes overlap with 1910.08173; journal-submission "
                           "version"
                       ),
        },
        {
            (
                "url"
            ): (
                       "https://pure.etsmtl.ca/en/publications/deep-domain-adaptation-with-ordina"
                       "l-regression-for-pain-assessmen/"
                   ),
            (
                "section"
            ): (
                           "Publisher-affiliated bibliographic record; DOI "
                           "10.1016/j.imavis.2021.104167; author abstract and version metadata"
                       ),
        },
        {
            (
                "url"
            ): (
                       "https://espace.etsmtl.ca/id/eprint/3267/1/RAJASEKHAR_Gnana_Praveen.pdf"
                   ),
            (
                "section"
            ): (
                           "Author dissertation Chapter 3, Sections 3.3-3.4, Tables 3.1-3.4, pp. "
                           "114-132; Chapter 0 lists FG 2020 and IVC 2021 outputs together"
                       ),
        },
    ],
    (
        "family_resolution"
    ): (
                             "S791 is the FG 2020 proceedings article (DOI "
                             "10.1109/FG47880.2020.00139) with arXiv author manuscript "
                             "1910.08173. S792 is the peer-reviewed IVC 2021 journal article "
                             "(DOI 10.1016/j.imavis.2021.104167), with arXiv manuscript "
                             "2008.06392. The author dissertation lists both publications as "
                             "outputs of the same contribution; the journal version explicitly "
                             "improves the earlier WSDA with ordinal modeling and adaptive "
                             "pooling. Keep distinct source IDs linked by version_of; do not "
                             "count them as separate mechanism families."
                         ),
    (
        "scope_limits"
    ): (
                        "S791/S792 predict facial-expression pain labels, not subjective "
                        "clinical pain, SCS response, or ECAP. RECOLA source labels and weak "
                        "target pain labels are used. BioVid results are separate sequence-level "
                        "experiments; the private Fatigue dataset is not a pain validation "
                        "cohort."
                    ),
}
existing = next((x for x in DATA[(
                                     "analogue_decisions"
                                 )] if x[(
                                                                "source_id"
                                                            )] == (
                                                                                "S791"
                                                                            )), None)
if existing is None:
    DATA[(
             "analogue_decisions"
         )].append(family_entry)
else:
    DATA[(
             "analogue_decisions"
         )][DATA[(
                                        "analogue_decisions"
                                    )].index(existing)] = family_entry

refresh = next(
    row
    for row in DATA[(
                        "citation_search"
                    )][(
                                           "s149_forward"
                                       )][(
                                                           "dated_refreshes"
                                                       )]
    if row[(
               "date"
           )] == (
                          "2026-09-25"
                      )
)
refresh[(
            "new_direct_analogue"
        )] = True
refresh[(
            "new_mechanism_class"
        )] = False
refresh[(
            "status"
        )] = (
                        "first_later_dated_refresh_new_prior_art_family_found"
                    )
refresh[(
            "coverage_limit"
        )] += (

        " The 2026-09-25 expanded pain-domain search added one previously unindexed prior-art "
        "family (S791/S792); it does not cite S149."

)

for url, section in (
    (
        (
            "https://api.semanticscholar.org/graph/v1/paper/DOI:10.3389/frai.2026.1827727"
        ),
        (
            "2026-09-25 citation endpoint reports no indexed citing works; separate from the "
            "S088 paper abstract endpoint"
        ),
    ),
    (
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=CITES:10.3389/frai.202"
            "6.1827727&format=json"
        ),
        (
            "2026-09-25 Europe PMC cites query hitCount=0"
        ),
    ),
):
    if not any(x[(
                     "url"
                 )] == url for x in DATA[(
                                                 "citation_search"
                                             )][(
                                                                    "s149_forward"
                                                                )][(
                                                                                    "locators"
                                                                                )]):
        DATA[(
                 "citation_search"
             )][(
                                    "s149_forward"
                                )][(
                                                    "locators"
                                                )].append({(
                                                                        "url"
                                                                    ): url, (
                                                                                    "section"
                                                                                ): section})

DATA[(
         "remaining"
     )] = [
    (
        "S088 version-of-record full methods remain inaccessible; secondary abstract is recorded "
        "separately from primary evidence."
    ),
    (
        "Perform consecutive later-dated NS-06 refreshes after 2026-09-25. The 2026-09-25 "
        "expanded pass found the S791/S792 prior-art family, so saturation is not established; "
        "require two later dated refreshes with no new direct analogue or mechanism class."
    ),
    (
        "Link S759 reported-result runs to a code commit or manifest if exact provenance is "
        "required; executable protocol is resolved but the manuscript conflict remains "
        "documented."
    ),
]
DATA[(
         "next_refresh_plan"
     )][(
                              "earliest_date"
                          )] = (
                                                 "2026-09-26"
                                             )
for query in [
    (
        "Exact DOI/title and author search for FG 2020 WSDA family: 10.1109/FG47880.2020.00139, "
        "arXiv:1910.08173"
    ),
    (
        "Exact DOI/title and author search for journal extension: 10.1016/j.imavis.2021.104167, "
        "arXiv:2008.06392"
    ),
    (
        "Forward/backward citation search for newly indexed direct analogues and S149, retaining "
        "source-version distinctions"
    ),
]:
    if query not in DATA[(
                             "next_refresh_plan"
                         )][(
                                                  "queries"
                                              )]:
        DATA[(
                 "next_refresh_plan"
             )][(
                                      "queries"
                                  )].append(query)

PATH.write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + (
                                                                     "\n"
                                                                 ), encoding=(
                                                                                    "utf-8"
                                                                                ))
