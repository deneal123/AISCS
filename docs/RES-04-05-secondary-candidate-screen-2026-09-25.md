# RES-04/RES-05 supplemental candidate screen — 2026-09-25

Scope: add evidence for human epidural SCS ECAP datasets with possible patient-linked pain outcomes. This is a literature-level screen. It does not establish owner-confirmed access. No owner was contacted.

Across all four candidates, `ethics_secondary_use` is separately `unconfirmed` in the access audit. Ethics review and consent for each source study do not establish permission for this project's secondary analysis; owner/controller release, ethics/IRB determination, and legal/consent terms must each be resolved.

## Newly screened records

### European multicenter real-world cohort (NL7889, NCT05272137, ISRCTN27710516)

- Primary source: Nijhuis et al., *Durability of ECAP-Controlled Closed-Loop SCS in a Real-World European Chronic Pain Population*, Pain and Therapy (2024), DOI `10.1007/s40122-024-00628-z`, https://link.springer.com/article/10.1007/s40122-024-00628-z . Full-text data-availability statement: “All data generated or analyzed during this study are included in this published article.”
- The paper reports patient-reported VNRS pain and ECAP/device metrics across 13 centers. Its abstract gives baseline VNRS `n=135`; the full Results distinguish all-patient baseline `n=148` from the stimulation-naive subgroup baseline `n=135`. The three objective dose metrics use `n=236/230/254`. These denominators must remain separate; the unit, overlap and observation windows need owner clarification before the summaries can define a linked cohort. It is relevant as an analysis target and as published aggregate evidence.
- The article's statement does not establish a downloadable row-level dataset, raw/pulse-level waveforms, a stable cross-table patient key, participant consent for independent reuse, a DUA, or owner delivery route. It therefore does not currently meet RES-04's owner-confirmation criterion. Treat article tables/figures as published aggregate evidence only.
- The publisher's Ethical Approval section explicitly names NL7889 for the Netherlands, NCT05272137 for Germany, and ISRCTN27710516 for the UK. These are registrations of the reported multicountry study, not evidence for three independent cohorts. The article reports written consent for study data use; it does not establish consent for this independent secondary analysis or a DUA.
- The publisher names Harold Nijhuis as corresponding author. A question draft is available at `docs/data-requests/nijhuis-rwe-owner-request-2026-09-25.md`; no message was sent. The responsible data controller and authority to release patient-linked records still require confirmation.
- Owner-confirmed access: absent. Patient linkage: not established. Outcomes in study: reported; inclusion in an externally released linked table: not established. ECAP in study: reported; externally released granularity: not established. The candidate is now tracked in `data/human-ecap-scs-access-audit.json` as `HES-NIJHUIS-RWE-2024`.

### University of Minnesota / Abbott ECAP recording study (NCT04938245; overlap with existing HES-UMN candidate)

- Primary source: Ramadan et al., *Methods and system for recording human physiological signals from implantable leads during spinal cord stimulation*, Frontiers in Pain Research (2023), DOI `10.3389/fpain.2023.1072786`, https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1072786/full . Publisher full text, sections 3.1 and 3.4, reports two consented participants, repeated ECAP recordings and 20 repeated observations; section “Data availability statement” says the data were funded by Abbott and are Abbott's proprietary and confidential property, and Abbott is under no obligation to release to third parties.
- This is not a separate independent cohort from the existing NCT04938245 candidate. It establishes technical recording evidence and a restrictive data-rights statement for this two-participant article dataset. Do not generalize the two-participant sample or the Abbott statement to every later NCT04938245 analysis/release without owner confirmation.
- Patient-linked clinical pain-outcome suitability: this 2023 article is a signal-processing study, not a patient-level clinical pain-outcome dataset. It cannot by itself satisfy the RES-04 endpoint.

## RES-05 decision status

No primary dataset is selected. The European cohort offers the broadest published real-world ECAP-plus-pain summary among the newly screened records, but its paper does not demonstrate access to linked individual-level data. NCT04938245 has a documented future repository/request route in the existing audit, while this 2023 paper documents Abbott's proprietary data position for its technical recordings; the later 2025 eight-participant paper and planned registry release remain separate items requiring owner confirmation. Existing Saluda EVOKE/ECAP request routes also remain in conflict with the trial registry's `IPD Sharing: NO` entries. A final dataset selection or STOP-H3 would overstate the present evidence.

## Search and review trail

- Search date: 2026-09-25.
- Queries: `human epidural ECAP spinal cord stimulation dataset raw waveforms patient pain outcome data availability`; `"Durability of Evoked Compound Action Potential" "Data availability" real-world European`; `"Clinical utility of ECAP dosing" "Data are available"`.
- Primary publisher pages checked: Frontiers full text for DOI `10.3389/fpain.2023.1072786`; Springer Nature full text for DOI `10.1007/s40122-024-00628-z`.
- Limits: this screen is not an exhaustive search of all SCS trials or repositories; it has not inspected consent forms, DUAs, owner data dictionaries, or actual data packages. Search-result discovery is not treated as evidence of access.
