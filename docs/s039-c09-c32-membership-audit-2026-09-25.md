# S039 membership audit — C09 (XAI for pain detection) and C32 (Subject-Incremental learning)

## Follow-up: official publisher-indexed article text reviewed

The initial route survey below recorded direct ScienceDirect access as blocked and did not locate article text. A subsequent search result for the **official ScienceDirect page** exposed the full indexed article sections and was checked on 2026-09-25: `https://www.sciencedirect.com/science/article/abs/pii/S174680942601815X`.

This changes the membership verdicts below. The indexed primary page includes:

- Abstract and Introduction describing subject-incremental training as sequential parameter transfer across training subjects without reinitialization, validation checkpoint selection, and frozen testing on unseen subjects.
- Discussion §B, **“Explainability analysis using SHAP,”** stating that SHAP was applied to the proposed network and that Fig. 5 presents mean SHAP values for the top ten features.
- The study boundary: 52 healthy participants and controlled graded thermal stimulation; the authors state that these results do not establish clinical generalizability.

Accordingly, **C09 is supported directly** by an explicitly reported SHAP analysis and Fig. 5, and **C32 is supported directly** by the described sequential subject-incremental protocol. Keep both memberships and count one work/one evidence row. The publisher landing page still returned HTTP 403 when opened directly, so conclusions are limited to the publisher-indexed article text; no claim is made that a locally accessible full-text PDF was inspected. The earlier “SHAP unlocatable” and “protocol unverified” conclusions in sections 4–6 are superseded by this follow-up.

Date: 2026-09-25. Mode: **membership audit**. The initial worker pass made no canonical edits. The follow-up kept all members and updated only S039's `multiple_membership_rationale` after the primary-source check above. This document records what the publisher-indexed primary text can support and the remaining access limit.

Subject: **S039** — Joshi R. C.; Kumar S.; Singh Gautam S. K.; Dutta M. K. (2026).
*Deep Multi-Head attention network with Subject-Incremental learning for Cross-Subject generalization in
objective pain monitoring using multimodal physiological signals.* Biomedical Signal Processing and Control
128:111261.

---

## 1. Scope and review rule

The question is narrow: does the canonical record of S039 support (a) membership in **C09 "XAI для детекции
боли"** at a *direct* level, i.e. an explanation method that is genuinely used and evaluated, or only a
*contextual* level; and (b) membership in **C32 "Subject-Incremental learning"**.

Per `SKILL.md` and `docs/data-contract.md`, cluster membership is navigational and is not independent
evidence. The review therefore compares the cluster title with the canonical record's title, method string,
`evidence.target_construct`, `evidence.evidence_role`, and the **primary locators** attached to S039 — not
with what the title of the article suggests the method might be.

---

## 2. Identity and one-paper accounting (no double counting)

| Item | Value | Location |
|---|---|---|
| Canonical ID | `S039` | `data/records.json` (1 occurrence of the string) |
| DOI | `10.1016/j.bspc.2026.111261` | `data/records.json` → `identifiers.doi` |
| PII | `S174680942601815X` | Elsevier coredata, `.work/s039_els_abs.json` |
| Scopus EID | `2-s2.0-105047163645` | Elsevier coredata, `.work/s039_els_abs.json` |
| Primary URL | `https://www.sciencedirect.com/science/article/pii/S174680942601815X` | `data/records.json` → `identifiers.exact_url` |
| Aliases → S039 | **10**: `S056, S089, S118, S132, S178, S225, S258, S353, S366, S407` | `data/aliases.json` → `aliases` |

The 10 aliases are pre-merge title variants of the same ScienceDirect record (archive titles such as
"Subject-Incremental learning (final)", "Deep Multi-Head attention (final extended)",
"Deep Multi-Head attention network for Cross-Subject pain monitoring"). `data/aliases.json` records their
reason as `confirmed_title_variant_of_same_primary_source` (validated 2026-09-22).

**One-paper accounting holds.** S039 is counted once:
- exactly **1** canonical source record;
- exactly **1** evidence-matrix row (`data/evidence-matrix.json`, `source_ids: ["S039"]`);
- exactly **1** ledger entry referencing it (`s036-s039-evidence-locator-review-2026-09-25.json`);
- exactly **1** validation-log decision (`data/validation-log.json`, `reviews[0].decisions[6]`);
- all 10 aliases are excluded from the matrix (verified: 0 matrix rows carry an alias ID).

Historical note: the 2026-09-21 archive `clusters.json` listed C32 with 13 members (`S039` + 12 title
variants, including `S418`/`S431` which have no records or alias entries in any snapshot). The live
`clusters.json` has already collapsed C32 to the single canonical member `S039`. That collapse is correct
one-paper accounting and is *not* part of this audit's recommendations.

S039 has `multiple_membership = 2` with rationale:
`The source supports distinct thematic projections; membership is navigational, not duplicate evidence.`
(`data/clusters.json` → `multiple_membership` / `multiple_membership_rationale`, checked 2026-09-23).

---

## 3. Locator inventory — what primary locators actually exist for S039

This is the crux of the C09 question. **S039 has no section, page, figure, or table locator anywhere in the
knowledge base.** Every `field_resolution` locator is a self-referential placeholder.

### 3.1 `records.json` → `field_resolution`

- Entries: **36** field keys, of which **36/36** carry a locator of the form `canonical field <name>`.
- Distinct URLs used across all 36 locators: exactly **one**,
  `https://www.sciencedirect.com/science/article/pii/S174680942601815X`.
- `checked_at` on all 36: `2026-09-23`. States: `reported` / `not_reported` / `not_applicable`.

Consequently there is **no primary locator** for:
- the modality list (`EDA; BVP; ECG; EMG; respiration`),
- the method string (`... deep fusion with SHAP`),
- the dataset string (`PainMonit PMED`),
- the performance string (`87.68% ± 0.41% ... four subject-independent outer folds`),
- the cross-subject protocol string (`subject-wise four-fold outer cross-validation`).

### 3.2 `evidence-matrix.json` → the single S039 row

| Field | Value |
|---|---|
| `claim` | "The method reports 87.68% participant-level accuracy for six-class recognition." |
| `verified_evidence` | "Elsevier full text reports 87.68% ± 0.41% across four subject-independent outer folds." |
| `locator.url` | `https://www.sciencedirect.com/science/article/abs/pii/S174680942601815X` |
| `locator.locator` | "Publisher abstract, Results: 87.68% ± 0.41% participant-level six-class accuracy across four subject-independent outer folds." |

This locator is **abstract-level only**. It names no section, no figure, no table, and no page. The word
"Results" here denotes the abstract's results sentence, not a numbered Results section.

### 3.3 `evidence-review-ledger.json` → `s036-s039-evidence-locator-review-2026-09-25.json`

```
status:   "two_primary_abstract_locators_reviewed"
boundary: "Publisher abstracts support the stated metrics only. They do not establish independent
           clinical validation or an unreported split unit for S036."
```

The ledger's own boundary statement is explicit: for S039 the only reviewed primary source is the
**publisher abstract**, and it supports the metric only.

### 3.4 `data/evd03-evidence-matrix-audit-2026-09-25.md` → line 24

The only S039 entry in that audit is: "repaired a corrupted replacement character to `±`." No content or
locator audit of S039 is recorded there.

### 3.5 Consistency conflict (recorded, not resolved here)

- `validation.full_text_status = "checked"`, `status = "verified_primary"`, `checked_at = 2026-09-22`,
  `notes = "Primary publisher record and article text checked."` (`data/records.json`).
- `data/validation-log.json` decision: search result `"Exact publisher article and full text metadata found."`,
  URL `https://www.sciencedirect.com/science/article/pii/S174680942601815X`.
- `src07-coverage-ledger-2026-09-25.json`: S039 `route = "crossref_metadata_screened"`, remaining
  `"ScienceDirect page blocked (403) ... on-page notices and preprint remain unverified."`
- `src07-relevance5-publisher-batch-2026-09-25.json`: access `"Publisher article text and issue information
  were visible in indexed ScienceDirect result; direct page fetch is CAPTCHA limited."`

So the canonical `full_text_status = "checked"` is a **2026-09-22 curation assertion** that is not backed by
any recorded S039 full-text audit, and it conflicts with the later SRC-07 artifacts, which record the page as
403/CAPTCHA-blocked and the route as Crossref-metadata-only. Review log C09 also keeps S039 disputed.

---

## 4. C09 "XAI for pain detection" — direct or contextual?

**Verdict: contextual/disputed — not direct.** No primary locator demonstrates that an explanation mechanism
is used and evaluated in S039.

Reasoning, source by source:

1. **The title does not advertise explainability.** The full title
   ("Deep Multi-Head attention network with Subject-Incremental learning for Cross-Subject generalization in
   objective pain monitoring using multimodal physiological signals") contains "attention" and "multimodal"
   but **no** "SHAP", "explainable", "interpretable", "saliency", or "attribution". Attention here is the
   classifier architecture named in the method, not a stated explanation method.
2. **The only XAI signal in the canonical record is the unverified method string**
   `"Subject-incremental multi-head attention and deep fusion with SHAP"`. Its `field_resolution` locator is
   `canonical field метод`, pointing at the ScienceDirect URL only. No section, figure, table, or page is
   attached. There is consequently no evidence that SHAP was applied, evaluated, or reported.
3. **The card's own `производительность` field contains no explanation result.** It reports accuracy only
   (`87.68% ± 0.41%`), unlike the C09 representative S008, whose performance field reports DeepSHAP frequency
   attribution ("beta 14-15 Hz was associated with high-pain decisions..."). S039 has no comparable
   reported attribution result.
4. **The only "XAI" keyword trace in the accessible metadata is a reference-list citation, not a method use.**
   Crossref reference list (`10.1016/j.bspc.2026.111261`, 30 references) contains
   Gouverneur et al. 2023, *"Explainable Artificial Intelligence (XAI) in Pain Research: Understanding the
   Role of Electrodermal activity for Automated Pain Recognition"*, Sensors 23(4):1959,
   DOI `10.3390/s23041959`. Citing an XAI paper does not establish that S039 itself performs or evaluates
   explanation.
5. **The provenance of the "SHAP" string is a search seed, not a primary read.** `provenance.query_or_seed =
   "Deep Multi-Head attention network" "Subject-Incremental"` (2026-09-22, relevance-5/batch-001). The archived
   2026-09-21 record already carried `метод: "Subject-incremental learning, SHAP"` with `авторы: "Не указано"`,
   `датасет: "Не указано"`, `ограничения: "Не указано"` — i.e. an unsourced screening note that later
   curation expanded into the current, more confident method string.
6. **Peer review of the KB agrees.** `docs/cluster-content-review-log-2026-09-25.md` line 21:
   "**S039, S046, S060** remain disputed: attention-based pain classification, explainable SCS-response
   prediction, and broad AI-in-SCS review, respectively." And the author decision packet lists
   "C09/S039/S046/S060" among disputed boundaries.

What *is* verifiable about S039 from primary/registry routes (and is therefore legitimately navigational):
multimodal physiological pain classification on PainMonit PMED; a six-class experimental-pain target; a
subject-wise outer cross-validation with a reported 87.68% ± 0.41% mean participant-level accuracy. That
evidence supports C09 only as *"attention-based pain classification in an XAI-labelled cluster"* — a
contextual adjacency — and the cluster is indeed titled "XAI для детекции боли", whose closest true fit is
the representative S008 (DeepSHAP, full-text audited).

**Recommendation (no removal):** keep S039 in C09 as a *disputed/contextual* member and record the boundary
rather than the claim. If the author wants C09 to mean "explanation is used and evaluated", S039 should be
downgraded from direct to contextual; removing it is not warranted because the SHAP method string is
unrefuted, only unlocatable.

---

## 5. C32 "Subject-Incremental learning" — direct or contextual?

**Verdict: title/scope-level direct; the tested protocol is unverified.**

- Live `clusters.json`: C32 "Subject-Incremental learning", `записей = 1`, members `["S039"]`,
  representative `S039`. The 12 former title-variant members have already been collapsed away, so C32 is a
  single-source cluster whose only support is S039's own title.
- The cluster title is a literal substring of the article title ("Subject-Incremental learning"), which is why
  the earlier review log called S039 the "exact-fit member" of C32.
- However, the **tested protocol recorded in the canonical card is a cross-subject cross-validation**, not an
  incremental-learning procedure: `кросс_субъект = "Да, subject-wise four-fold outer cross-validation"` and
  `производительность = "87.68% ± 0.41% mean participant-level accuracy across four subject-independent outer
  folds"`. Four subject-independent *outer* folds are a standard cross-subject evaluation. Whether the paper
  additionally performs a subject-incremental (sequential/subject-by-subject) training protocol, and whether
  that protocol is what produces the 87.68%, cannot be confirmed from any primary locator.
- The same locator gap applies: the protocol strings are backed only by `canonical field ...` placeholders and
  the abstract-level matrix locator.

**Recommendation (no removal):** C32 membership is defensible on title scope but should be annotated as
*unverified protocol* until the method section is read. It is not demonstrated double counting, because C09
and C32 are distinct thematic projections and S039 is counted once.

---

## 6. Primary access limits (source-specific rationale)

Every route attempted in this environment for the S039 primary text failed or returned metadata only:

| Route | URL / endpoint | Result |
|---|---|---|
| ScienceDirect article page | `https://www.sciencedirect.com/science/article/pii/S174680942601815X` | HTTP 403, CAPTCHA ("Are you a robot?") |
| ScienceDirect abstract page | `.../article/abs/pii/S174680942601815X` | HTTP 403, CAPTCHA |
| r.jina.ai rendering | `https://r.jina.ai/https://www.sciencedirect.com/science/article/abs/pii/S174680942601815X` | CAPTCHA page only (`.work/s039_jina.txt`); no article text |
| ScienceDirect PDF | (via `/pii/` route) | Not reachable without 403/CAPTCHA |
| Elsevier abstract API | `https://api.elsevier.com/content/abstract/scopus_id/105047163645` | Only `<coredata>`; `openaccess=0`, no abstract body (`.work/s039_els_abs.json`) |
| Elsevier text-mining links | `api.elsevier.com/content/...` full-text | API key required; not available |
| Crossref | `https://api.crossref.org/works/10.1016%2Fj.bspc.2026.111261` | Identity/VOR metadata + 30 references; **no abstract**; `relation {}`, `update_to []`, `updated_by []` (`.work/s039_crossref.json`) |
| OpenAlex | `W7202179652` | `abstract_inverted_index: null`, `has_fulltext: false` (`.work/s039_openalex_abs.json`) |
| Unpaywall | `.../10.1016/j.bspc.2026.111261` | `is_oa: false`, `oa_status: "closed"`, no repository copy (`.work/s039_unpaywall.json`) |
| Semantic Scholar | `graph/v1/paper/DOI:...` | `abstract: null`, `tldr: null`, `openAccessPdf.status: "CLOSED"` (`.work/s039_s2.json`) |
| Europe PMC | REST search | `hitCount 0` (`.work/s039_epmc.json`) |
| PubMed | esearch by DOI | `count 0`, no PMID (`.work/s039_pubmed.json`) |
| CORE | API v3 | 1 hit, `abstract: ""`, full text unavailable to public API (`.work/s039_core.json`) |
| OpenAIRE | API | `total 0` (`.work/s039_openaire.json`) |
| Altmetric | Details Page API | API key required (`.work/s039_altmetric.json`) |
| X-MOL / Scilit / sciencegate / ResearchGate | HTML | CAPTCHA or 403; no abstract |
| Colab.ws | `colab.ws/articles/10.1016%2Fj.bspc.2026.111261` | Bibliographic shell only; "Краткое описание" (abstract) empty |
| Wayback / CDX | `web.archive.org` | No snapshot of the abstract |
| Search engines (Bing/Mojeek) | exact-phrase `"87.68%" "subject-incremental"` | No cached abstract; results were unrelated (car listings) |

**Source-specific rationale for the verdict:** because the title omits any explainability term and no
accessible route yields the abstract or method text, the "with SHAP" claim cannot be independently located.
The audit therefore treats C09 membership as *contextual/disputed* and C32 membership as *title-scope direct,
protocol unverified*, while acknowledging that neither can be finally adjudicated without the method/results
text. The evidence-matrix and ledger already say the same thing in their own words: the abstract supports the
metric only.

---

## 7. Findings ledger (exact local anchors)

| # | Finding | Anchor |
|---|---|---|
| F1 | S039 counted once despite 10 aliases and dual membership | `data/records.json`; `data/aliases.json` → `aliases`; `data/evidence-matrix.json` |
| F2 | All 36 `field_resolution` locators for S039 are `canonical field <name>` with one URL | `data/records.json` → `S039.field_resolution` |
| F3 | No section/figure/table/page locator for S039 exists anywhere in the KB | `data/records.json`, `data/evidence-matrix.json`, `data/evidence-review-ledger.json` |
| F4 | Single matrix row is abstract-level only | `data/evidence-matrix.json`, `source_ids ["S039"]` |
| F5 | Ledger status is abstract-only | `data/evidence-review-ledger.json` → `s036-s039-evidence-locator-review-2026-09-25.json` |
| F6 | `full_text_status=checked` (2026-09-22) conflicts with 403/CAPTCHA and Crossref-only routes | `data/records.json` → `validation`; `data/src07-coverage-ledger-2026-09-25.json`; `data/src07-relevance5-publisher-batch-2026-09-25.json` |
| F7 | C09 keeps S039 disputed; C32 called exact-fit | `docs/cluster-content-review-log-2026-09-25.md` line 21; `docs/author-decision-packet-2026-09-25.md` |
| F8 | C32 live members = `["S039"]` only; 12 title variants collapsed | `data/clusters.json` → `clusters[C32]` |
| F9 | S039 multiple_membership = 2 (C09, C32), navigational rationale | `data/clusters.json` → `multiple_membership` / `multiple_membership_rationale` |
| F10 | Only XAI trace in metadata is a reference-list citation (Gouverneur 2023, Sensors) | Crossref `reference` list for `10.1016/j.bspc.2026.111261` |
| F11 | Modality lists disagree: card top-level includes `respiration`; `evidence.modalities` omits it | `data/records.json` → `S039.модальность` vs `S039.evidence.modalities` |
| F12 | `evidence.access_status = "open"` conflicts with observed closed access (`oa_status: closed`) | `data/records.json` → `S039.evidence.access_status`; `.work/s039_unpaywall.json` |

F11 and F12 are content-consistency observations that affected the reliability judgement; they were not
edited.

## 8. Open items (not resolved by this audit)

- The tested "Subject-Incremental" protocol is only title-attested; the four-fold cross-subject CV reported in
  the card may or may not be the incremental protocol (F: §5). Resolve only by reading Methods/Results.
- `full_text_status = "checked"` has no backing S039 full-text audit artifact and should be reconciled with
  SRC-07 or downgraded consistent with `EVD-03`.
- EVD-03 remains open: TODO notes 72 generic locators at the time of the s036/s039 repair; S039 is one of the
  still-generic rows.
- `evidence.modalities` should include `respiration` if the card's top-level modality list is correct, or the
  top-level list should drop it (F11).

**No members were removed. No canonical data was changed.**
