# EXP-01 — Drosophila H1 protocol (draft)

**Status:** design draft; not executable and not evidence of a result. H1 is a working label for the question below, not a registered hypothesis in the project contract. This draft uses the larval Class-IV fallback domain in `SIM-DOM-01`; it does not implement that contract's primary adult domain. The author must select the explicitly separate larval fallback or require a new adult-domain protocol before EXP-01 can close. `NOV-05` remains an explicit dependency. Do not close EXP-01 until the novelty decisions are final, the biological/model inputs are versioned, and this protocol is reviewed against the selected inputs. No simulation has been run for this draft.

## Question and claim boundary

**Working H1:** Can a connectome-constrained Drosophila neural-dynamics model reproduce a fixed set of stimulus-evoked neural and defensive-behavior observables better than matched topology/dynamics controls?

This is an in-domain fly-model question only. A positive result would not establish subjective pain in flies or people, equivalence between fly and human spinal cord, ECAP fidelity, transfer to human measurements, or SCS efficacy. Human ECAP is a separate model and a separate evaluation (EXP-02 onward).

## Preconditions and version bounds

0. The project's primary simulation domain is adult Drosophila (`SIM-DOM-01`). The contract permits a larval Class-IV escape/rolling circuit only as an explicitly different fallback experiment; adult and larval circuits must not be pooled. This draft is conditional on the author accepting that fallback. If the primary adult domain is retained, replace this target and its observables before execution; do not silently present S282 as adult-domain evidence.
1. Freeze and checksum the selected graph input, preprocessing/export code, simulator source, parameter table, stimulus protocol, and reference data before generating any replicate. Record immutable release/commit identifiers and SHA-256 for every local input in a run manifest. A filename, file timestamp, or matching graph size is not a version identifier.
2. The [connectome audit](../../data/drosophila-connectome-audit.json) currently records the four `S740` upstream matrix input releases as `not_reported`; the [runtime audit](../../data/runtime-audit.json) records ST107 at commit `5880d221e21b1f3385b7246a6ffc3b2cf0029c2c` and asset revision `03358c075000af5379e405b244dd31f1a0fd1401`, but only as a reproduced browser runtime. These are provenance bounds, not an approved nociception-model choice. Do not silently substitute either for a validated/versioned H1 input.
3. The currently audited source `S282` is bioRxiv v1 (DOI `10.1101/2025.09.30.679458`; versioned URL ends in `v1`; audited full-text SHA-256 is recorded in `drosophila-nociception-audit.json`). The latest live publisher fetch was rate-limited (HTTP 429), so current-version/correction status is not independently confirmed. The paper reports a first-instar EM connectome, third-instar ex-vivo imaging, and separate third-instar behavior cohorts. Neural imaging uses optical activation; the cited behavioral circuit assays use thermal/genetic activation or inhibition. Treat these as separate targets and interventions, never as matched observations from one animal, one graph, or one modality. Recheck the publisher version and any correction before freezing targets.
4. If no compatible, versioned connectome/dynamics implementation and primary target data can be identified after `NOV-05` and `SRC-03/04` review, record H1 as not executable with the reason and stop. Do not fill missing biology with synthetic labels.

## Prespecified observables (freeze after the compatibility gate)

Freeze one stimulus-by-endpoint table before tuning. The candidate endpoint set below is conditional on primary-data compatibility; an incompatible endpoint is excluded with a logged reason before any model evaluation.

| Endpoint family | Fixed observable | Unit of comparison |
|---|---|---|
| Neural response | Signed group contrast in the source-reported GCaMP ΔF/F summary for optical Ipsigoro activation→Goro response and optical MD-IV activation→Ipsigoro response. Preserve GCaMP6s and GCaMP8s as separate endpoints. The audit establishes the direction (increase) but not a numeric summary/window; retrieve and freeze those from the primary source before any quantitative run. | Independent biological preparation, not frames/cells as independent samples |
| Behavior | Rolling time or probability, separately for conditioned cue plus Basin activation, thermal/genetic Ipsigoro activation, and thermal/genetic MD-IV activation with Ipsigoro inhibition; for the learning assay use the source-defined first test and five-second window. Neural optical conditions are not equivalent to these behavioral interventions. Numeric group totals are not stated in the audited main text and must be retrieved from the complete primary report/supplement or marked unavailable. | Independent larva; preserve the source's group/condition structure |
| Negative/control conditions | No source-supported sham/no-activation values are present in the current `S282` audit. Include an inhibition/control condition only if the primary report or supplement supplies it and its compatibility is verified; otherwise mark this endpoint unavailable. | Same unit as its endpoint; no imputed control values |

For numerical targets, report signed bias, MAE, and a 95% interval across held-out synthetic model realizations; report calibration/reliability for probabilistic outputs. These intervals describe model-realization variability, not biological sampling uncertainty. Biological group sizes, missing values, and uncertainty must come from the source or be marked unavailable. Do not infer unreported sample sizes from figure appearance. If the complete primary source does not provide extractable numeric targets, restrict the corresponding endpoint to the source-reported direction-of-effect check and do not claim distributional reproduction. Freeze primary/secondary labels before execution; no post-hoc endpoint substitution.

## Synthetic-individual generation and split

“Synthetic individual” means one complete simulator realization, not a fly and not a biological replicate. Freeze 20 parameter/graph-perturbation families (`SF-0001`…`SF-0020`) and generate five stochastic replicate IDs per family (`SI-0001`…`SI-0100`): 12 families (60 realizations) train, 4 (20) validation, and 4 (20) locked test. Keep all five replicates and every trajectory, stimulus, and repeated measurement from a family in that same partition. Compute each family split key as `SHA-256(manifest_sha256 || family_id)`, sort by the hex key (ID is a tie-breaker), then assign the first 12 families to train, next 4 to validation, and final 4 to locked test. This avoids splitting a parameter family across partitions; the four held-out families, not 20 runs, are the split-level units.

Use the fixed master seed `20260925`; derive each family and replicate seed with SHA-256 of `master_seed || family_id || replicate_id || stream_name`. If the simulator accepts 64-bit seeds, use the first 64 bits; for a smaller seed range, use rejection sampling into that range and record the mapping. Record RNG algorithm/version. Separate streams for graph perturbation, initial state, process noise, and observation noise. Test families/seeds remain unopened until the model, preprocessing, scoring code, and decision rules are frozen. Do not tune on the test partition. This split measures simulation robustness only; it does not substitute for held-out animals, connectomes, participants, or independent cohorts.

If the chosen model cannot instantiate meaningful independent parameter tuples, reduce the claim to deterministic parameter-sensitivity analysis and revise the protocol before running; do not label repeated seeds as independent synthetic individuals.

## Falsification and decision rules

H1 is not supported if any of the following occurs:

1. For any endpoint with extractable numeric primary-source targets, the complete model fails the frozen scoring/tolerance table on locked test families. For endpoints where only direction is extractable, a predicted contrast with the wrong sign falsifies that endpoint; do not describe this as reproducing its distribution. If neither numeric target nor a source-supported direction can be extracted, the endpoint is not evaluable and the H1 execution gate stays closed.
2. The connectome-constrained model does not improve the predeclared primary score over the matched degree-preserving rewired-connectome ensemble, or its uncertainty/calibration is worse. Compare at identical initialization, parameter budget, training data, optimizer budget, and seeds. Also report shuffled-dynamics and naive-synthetic controls; superiority over only one weak baseline is insufficient.
3. Results change sign or fall outside the prespecified robustness interval under the declared seed/parameter perturbations, or the test result depends on leakage from test realization IDs.
4. Provenance cannot be reproduced from the frozen manifest, or the target/reference cohort is incompatible with the selected graph/model stage or intervention.

Before any execution, fill a versioned decision table with the primary-score formula, tolerance/acceptance limits, uncertainty method, control-generation algorithm, and parameter ranges, citing the primary source for each empirical target. Thresholds must be determined without viewing locked-test outputs. Since the current audits do not establish all those inputs, no numeric pass threshold is asserted in this draft.

## Required run record

Store the protocol version/hash, source IDs and exact versions, graph and code hashes, environment lock, parameter/split manifest, all seeds/RNG versions, stimulus table, exclusions, per-realization predictions, scoring script hash, and complete results including failed runs. Keep biological observations separate from simulated observations. A successful software/runtime smoke test is not biological validation.

## Open gates

- `NOV-05`: final unranked novelty decisions, including direct-analogue disposition.
- `SRC-03/04`: exact model/connectome release and compatible nociception target provenance.
- Complete and version-check the primary `S282` report, including numeric target summaries and intervention details, before fixing a quantitative scoring table.
- EXP-02/03/04: observation model, baseline implementation, and formal statistical analysis plan remain separate downstream artifacts.

## Evidence pointers

- [Scientific contract](../../data/scientific-contract.json): `SIM-DOM-01` defines the adult primary domain and the explicitly separate larval Class-IV fallback. This protocol requires author selection of the fallback and does not satisfy the adult-domain protocol by itself.
- [Dissertation concept](../../data/dissertation-concept.json): `DEF-01` and `NOV-02` provide general model/control boundaries; the current `DEF-01` source list does not include `S282`. `H-DES-01` is the broader two-model transfer hypothesis, outside EXP-01.
- [Nociception audit](../../data/drosophila-nociception-audit.json), `S282`: currently audited bioRxiv v1 intervention, neural/behavior endpoints, and cohort/stage separation.
- [Connectome audit](../../data/drosophila-connectome-audit.json), `S740`: unresolved input graph release; `S783`: adult connectome/dynamics paper with graph release not pinned in verified text.
- [Runtime audit](../../data/runtime-audit.json), `ST107`: pinned browser runtime and stated limits; not a nociception validation.
