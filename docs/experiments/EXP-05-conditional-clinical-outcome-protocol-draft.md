# EXP-05 conditional clinical-outcome protocol (draft)

**Status: operational STOP-H3-A hold for the clinical branch; no final project-level STOP decision has been made.** On the 2026-09-26 audit snapshot, `human-ecap-scs-access-audit.json` records `no_owner_confirmed_usable_dataset`; none of five candidates has owner-confirmed access, linkage, consent scope, or a usable delivery route. Do not access participant-level data, train or evaluate clinical predictors, or claim clinical SCS-response prediction while the hold is active. The literature/registry search is not complete and owner requests have not been sent. Reassess after the remaining search and owner responses, then verify separate ethics/IRB, legal/consent, linkage, and delivery requirements. Keep TODO EXP-05 and RES-05 open; this is a temporary operational hold, not proof of permanent unavailability or a final STOP-H3 decision.

## 1. Question and claim boundary

If RES-05 later selects an authorized, participant-linked cohort, test whether a frozen model using pre-specified ECAP/SCS telemetry and permitted baseline covariates predicts one patient-level clinical outcome at one fixed follow-up, and whether it adds predictive value over a pre-specified clinical baseline and the corresponding no-transfer model. Use the same split and paired comparisons from TODO EXP-03 and the inference rules in TODO EXP-04.

This is a **prognostic prediction** protocol. An association or accurate prediction in observational data does not show that the model caused pain relief, that changing stimulation according to its prediction improves outcomes, or that SCS is efficacious. ECAP is a neural recruitment/dose signal, not a direct measure of pain. Do not infer subjective pain, analgesia, treatment benefit, or causal efficacy from ECAP alone, waveform properties, simulated activity, or within-patient controller stability.

No clinical outcome, scale, responder threshold, population, landmark, or follow-up window is selected in the current record. `research/data/scs-outcome-audit.json` contains candidate instruments and outcome definitions, but none is selected for this analysis. The exact target remains `null` until an owner-confirmed data dictionary and RES-05 decision establish which linked fields are actually available. Do not pick the endpoint after examining test associations.

## 2. Current STOP-H3-A gate

The contract trigger for STOP-H3-A is that no legally and ethically available human dataset links SCS telemetry/ECAP to a pre-specified patient-level clinical outcome and follow-up. Current evidence supports an operational hold while that condition remains unverified: the meta decision is `no_owner_confirmed_usable_dataset`, all five candidates have `owner_confirmation_received=false`, and the registry audit decision is `registry_outcomes_identified_patient_linkage_and_data_access_unconfirmed`. The search still has outstanding registry screening and no owner requests have been sent. Treat STOP-H3-A as armed and block the clinical branch; do not yet record a final project-level STOP decision or close RES-05.

| Candidate | Published evidence | Unresolved before any EXP-05 use |
|---|---|---|
| EVOKE, NCT02924129 | Clinical outcomes and ECAP-controlled dosing are reported; article offers qualified-researcher request route | Registry says `IPD Sharing: NO`; released fields and stable ECAP/outcome linkage are unconfirmed; actual consent scope and DUA are not approved. |
| ECAP study, NCT04319887 | PROMIS-29/clinical response and objective ECAP metrics reported | Registry says `IPD Sharing: NO`; linked row-level data, pulse/visit granularity, consent scope and agreement unconfirmed. |
| UMN, NCT04938245 | ECAP analysis in eight participants; registry promises a future anonymized repository; two-week pain-relief correlation is listed as an other outcome | Exact-ID repository accession was not located in the audit; stable linkage, outcome contents, consent/license and DUA unconfirmed. The 2023 two-participant methods paper identifies its recordings as Abbott proprietary; do not conflate it with the separate 2025 paper or promised release. |
| Nijhuis real-world cohort, NL7889 / NCT05272137 / ISRCTN27710516 | Published VNRS and ECAP-controlled dose summaries; article says analyzed data are included in the paper | This is one multicountry study, not three independent cohorts. The abstract gives baseline VNRS n=135; full Results distinguish all-patient n=148 and stimulation-naive n=135. Dose-metric denominators are n=236/230/254. Cohort overlap, observation windows, stable patient linkage, raw/participant-level ECAP fields, external reuse consent and data-controller release route remain unconfirmed. |
| ENDLESS, DOI 10.3389/fpain.2026.1922595 / NCT07211308 | Protocol plans pain outcomes and, for closed-loop DTM-SCS participants, in-clinic ECAP streams collected through JSON files | ClinicalTrials.gov lists `RECRUITING`, `IPD Sharing: UNDECIDED`, and no posted results. The protocol says pseudonymised-data access may be considered after project completion under controlled conditions and a DUA; no current open or linked participant-level dataset is provided. ECAP JSON schema, participant overlap/linkage, stimulation/time fields, and externally deliverable pain outcomes are unconfirmed. Primary locators: [Frontiers protocol](https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2026.1922595/full) (Sections 3.4.3 and 6) and [ClinicalTrials.gov record](https://clinicaltrials.gov/api/v2/studies/NCT07211308) (status/IPD modules). |

The operational STOP-H3-A hold blocks clinical analysis and clinical claims pending completion of the remaining search and owner-route checks. RES-05 remains a separate open gate for any human technical or clinical dataset: the current literature/registry screen is not an exhaustive proof of universal unavailability, and owner requests have not been sent. Re-evaluate clinical eligibility after owner/controller responses and confirmation of ethics/IRB, legal/consent, fields/linkage, and target compatibility. If those checks establish that no qualifying clinical dataset is legally and ethically available, the project author may record the final STOP-H3-A decision; a later qualifying release can be assessed under the same contract criterion.

If no qualifying dataset is confirmed, report only the permitted reserve results in the contract: Drosophila simulation, ECAP-like physical observation modeling, or authorized non-clinical technical ECAP/SCS tasks. Do not run EXP-05 on aggregate figures or infer patient-level effects from published group summaries.

## 3. Entry contract for a future selected cohort

RES-05 must document each required item before any participant-level analysis. Missing a critical field keeps the clinical branch stopped.

| Input | Required contract |
|---|---|
| Owner/controller | Confirms the data controller/release authority, exact fields and granularity, linkage, and delivery route. An article author or registry contact is not presumed to control release. |
| Ethics/IRB | The responsible institution determines whether secondary-use review is required and records the applicable approval or exemption. Owner permission does not substitute for this determination. |
| Legal and consent | Executed DUA/license and participant-consent scope permit linkage, modeling and reporting; secure storage/access and retention are documented. Ethics/IRB approval does not substitute for these terms. |
| Cohort identity | Trial/site/device and cohort-family keys; recruitment and exclusion flow; overlap with prior reports; intended-care context; and data release/version provenance. Related reports from one cohort are deduplicated. |
| Participant linkage | Stable pseudonymous participant key linking ECAP/telemetry, covariates, baseline outcome, and follow-up outcome. No direct identifiers enter this project repository or model logs. |
| Predictor timing | Exact prediction landmark; every predictor must be available by that time. Freeze ECAP/telemetry features, stimulation settings, device/site variables, and permitted pre-specified covariates. Exclude future outcome information and post-landmark leakage. |
| Outcome | One named patient-level clinical instrument or endpoint, scoring/unit, direction, baseline definition, and one fixed follow-up time/window; define responder threshold only if a binary endpoint is justified and documented. Record source, validation/population fit, and missingness. |
| Longitudinal structure | Dates/relative times for repeated measures; visit windows; loss to follow-up, crossover, explant, discontinuation, and competing events; ascertainment method. These are handled by a pre-registered rule, not by dropping inconvenient observations. |
| Denominators | Counts at participant, visit and observation levels; reasons for exclusions and missing outcomes; linkage completeness; and separate denominator for every target/metric. |
| Analysis package | Data dictionary, locked endpoint and covariates, EXP-04 analysis plan, participant-disjoint split manifest, code/environment/model hashes, and independent-test access procedure. |

## 4. Conditional design after the gate reopens

1. **Population and time origin:** define the eligible SCS population, treatment/programming context, index date, prediction landmark and fixed outcome follow-up from the selected study. Do not combine cohorts with incompatible devices, treatment phases, instruments or follow-up windows without a pre-specified harmonization plan.
2. **One primary outcome:** choose the endpoint from the owner-confirmed fields before test access. Choose a continuous score or a binary responder outcome, not whichever performs best. A responder threshold must come from a cited clinical definition or the study protocol, never from optimizing this test set.
3. **Predictors and baselines:** freeze predictor availability and encoding. Compare (a) a pre-specified clinical/engineering baseline available at the same landmark, (b) the human-only/no-transfer model, and (c) the connectome-pretrained candidate; include EXP-03's required synthetic and randomized-connectome controls where implemented and available. Keep all arms on the same participants and identical outcome definitions. Add covariates only when clinically justified and available before the landmark.
4. **No causal design claim:** unless treatment allocation and intervention estimand are prospectively defined in a suitable randomized/causal design, estimate prediction only. A prognostic model comparison cannot establish that model-guided programming changes the outcome.
5. **Split and test:** assign by participant and cohort family. No visits, windows, pulses, or settings from one participant may cross train/validation/test. Fit transforms, feature selection, thresholds, missing-data rules, and tuning only within training/validation participants. Keep an external cohort or untouched participant set locked until the entire model and plan are frozen. Report cross-patient performance only on people absent from all model fitting and model selection; unseen-setting claims require a setting holdout as well.
6. **Small samples:** participant is the sample size. Sessions, follow-up visits, repeated pain scores, ECAP pulses, sites within a single trial, model seeds and graph nulls do not add independent patients. Before analysis, justify the target sample using clinically meaningful difference and participant-level precision/power assumptions from allowed development data. If the available independent participant count cannot support the registered precision, stop confirmatory claims and restrict output to descriptive estimates with uncertainty.

## 5. Outcomes, scoring and uncertainty

The precise score depends on the locked outcome type and remains unset. Register one primary metric, direction, comparator, smallest effect of interest if externally justified, and acceptance rule before test access.

- For a continuous outcome, use a pre-specified participant-level error measure and report calibration of predicted values or intervals, with uncertainty intervals. Any repeated time points require a declared participant-level summary or longitudinal estimand.
- For a binary responder outcome, report discrimination and proper probability scoring, plus calibration-in-the-large/slope and a calibration plot. AUC alone is not calibration or clinical usefulness.
- For either type, compare the candidate against each required baseline with paired participant-level contrasts and 95% confidence intervals. Resample participants, retaining all their repeated records; do not bootstrap windows or pulses as independent units. Separate participant uncertainty from model-seed and rewired-graph variability.
- Prespecify multiplicity control for required contrasts and outcome subgroups. Keep post hoc subgroups and alternate thresholds exploratory. Do not claim equivalence or no effect from a non-significant small-sample result.
- Report calibration and error by clinically justified subgroups only if the sample supports interpretable estimates and the subgroup analysis is authorized. Show denominators and missingness; do not conceal failure in a subgroup behind an overall average.
- Assess clinical utility only if a decision threshold and action are specified prospectively, and report decision-analytic results as a separate analysis. Prediction alone does not show utility or benefit.

## 6. Falsification, reporting and audit trail

Withhold the clinical prediction claim if any required condition fails: no authorized linked dataset; unresolved participant linkage or outcome timing; outcome unavailable for enough eligible participants to support the registered analysis; test leakage; model gain absent versus the registered baselines; calibration inadequate under the registered criterion; or performance disappears on unseen patients. STOP-H3-B applies when performance exists only for seen-patient windows or vanishes under patient holdout.

Before test access, hash and archive the RES-05 decision, protocol/endpoint version, approved data dictionary and dataset release, participant/cohort-family split, code/environment, preprocessing, predictor/outcome definitions, model weights/configuration, seed manifest, scoring/calibration code and run manifest. Publish only aggregate results allowed by the DUA and consent; report negative results and deviations.

No simulation or patient analysis has been run for this draft. It does not create a clinical conclusion, evidence-matrix update, or data record.

## 7. Source and gate locators

- `research/data/scientific-contract.json`: machine EXP-04 (`scs_programming_and_evaluation`); ENT-06; STOP-H3-A/B; meta invariants; pending decisions.
- `research/data/human-ecap-scs-access-audit.json`: `meta.decision`; all five `candidates[].owner_confirmation_received`; `checks.access_procedure`, `consent_dua`, `patient_linkage`, `outcomes`, and `ecap_signal`. ENDLESS (`10.3389/fpain.2026.1922595`, NCT07211308) is recruiting with IPD `UNDECIDED`; the protocol plans in-clinic ECAP JSON files but provides no current participant-linked release/results ([Frontiers protocol](https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2026.1922595/full), Sections 3.4.3 and 6; [ClinicalTrials.gov record](https://clinicaltrials.gov/api/v2/studies/NCT07211308), status/IPD modules).
- `research/data/scs-outcome-audit.json`: candidate clinical instruments/outcomes and their current unselected status.
- `research/data/ecap-trial-registry-audit.json`: registry `meta.decision`, trial `ipd_sharing`, outcome registry fields, and `remaining` checks.
- `research/docs/RES-04-05-secondary-candidate-screen-2026-09-25.md`: candidate limits and explicit caution against final dataset selection/STOP from literature-only evidence.
- `research/docs/data-requests/*.md`: draft questions only; none sent or approved.
- `research/data/forbidden-transfer-audit-2026-09-25.json`: FT-04, FT-06, FT-07; ECAP is not a direct pain measure; repeated observations/reports are not independent participants/cohorts.
- Primary records in `research/data/records.json`: EVOKE/NCT02924129 (S779–S781), NCT04319887 (S237), NCT04938245/ECAP feature paper (S105), Ramadan (S765), and Nijhuis/NL7889 (S793). Primary locator details are preserved in each card and the access audit.
- Independent Pi read-only audits checked the clinical claim boundary and current dataset/STOP-H3 status. They made no repository changes or data access.

**Current decision:** the operational STOP-H3-A hold is active for clinical prediction; the final criterion is armed but unfired pending owner-route resolution. RES-05 and TODO EXP-05 remain open. No claim is made that ECAP measures pain or that the model improves clinical outcomes.
