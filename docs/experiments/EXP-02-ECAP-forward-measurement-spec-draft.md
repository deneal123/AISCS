# EXP-02 — ECAP forward and measurement specification (draft)

**Status:** design draft; not a validated ECAP model and not executable as a participant-level experiment. `EXP-01` remains open, so this specification is conditional and does not close the dependency. No simulations or clinical analyses were run to prepare it.

## 1. Scope and claim boundary

Specify an observation chain that maps a declared neural recruitment state to a differential epidural recording:

```text
stimulator output → volume-conductor field → fiber activation and propagation
  → single-fiber extracellular potentials → lead/reference measurement
  → stimulus-artifact handling → acquisition/filtering → observed ECAP features
```

The recorded voltage is an evoked neural signal mixed with stimulus artifact, electrode/tissue effects, amplifier behavior, filtering and measurement noise. An ECAP can support estimates of an electrically evoked response under a specified setup. It is not a direct measure of pain, analgesia, subjective experience, or clinical benefit. This draft specifies only the human ECAP observation layer; the Drosophila model is a separate upstream hypothesis and cannot be used to label human pain.

## 2. Primary evidence and limits

| Source | What its primary methods support | Evidence class and limit |
|---|---|---|
| [S766 — Anaya et al., DOI 10.1111/ner.12965](https://pmc.ncbi.nlm.nih.gov/articles/PMC6920600/) | Methods: “FEM of SCS”, “Multicompartment cable model”, “Assessment of the direct axonal response”, “Calculation of ECAP recordings”; Table 1; Results Fig. 2C. Lower-thoracic FEM, eight-contact lead, current-controlled monophasic cathodic 210-µs pulses at 50 Hz, multicompartment sensory axons, reciprocity projection from membrane currents to lead voltage. | Model-only. Fig. 2C compares one model waveform with one previously published clinical trace (200 vs 216 µV P2–N1); no held-out-patient validation. Assumed threshold/recruitment and canonical anatomy do not identify actual human axon counts. |
| [S768 — Zhang et al., DOI 10.7507/1001-5515.202007016](https://pmc.ncbi.nlm.nih.gov/articles/PMC9927682/) | §§1.1–1.4, Table 3, Figs. 7–9: T10 volume conductor, NEURON sensory-fiber models, 210-µs pulse and reciprocity-based differential ECAP calculation. | Model-only. Geometry reuses measurements from an earlier 15-volunteer MRI study; those volunteers are not a validation cohort for this model. Reported fiber activation fractions are simulated outputs, not patient measurements. |
| [S764 — Wu et al., DOI 10.1371/journal.pone.0345287](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0345287) | Methods “Simulation model of SCS-induced electric field”, “Multi-compartment cable model”, “Calculation of simulated ECAP signals”; Figs. 1–5, Tables 1–2. Eight-layer human thoracic FEM; traditional and segmented directional leads; 210-µs modeled pulse; reciprocity calculation. | Model-only. At 8 mA, the article reports model outputs of 244.8 µV and 363.6 µV and modeled activation fractions for two lead configurations. These are not measured patient outcomes or a validation set. |
| [S765 — Ramadan et al., DOI 10.3389/fpain.2023.1072786](https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1072786/full) | §§2–3 and Figs. 2–5, 7–11: two externalized human trial participants; asymmetric biphasic charge-balanced waveform; stimulation/recording montage, artifact fitting, filters and acquisition chain. | A human measurement-method study, not a biophysical forward-model validation. Twenty analysis observations are repeated within two participants; they are not 20 independent patients. |
| [S105 — König et al., DOI 10.1088/1741-2552/adbfbe](https://iopscience.iop.org/article/10.1088/1741-2552/adbfbe) | Methods §§2.2–2.5 and §3.6: 32-kHz, 24-bit acquisition; multiple artifact-fit families; 0.375–8-ms artifact fit; pulse-level classification. | Fifteen participants were recruited; 30 sessions were selected from eight participants and two sessions were excluded for unconfirmable electrode alignment, leaving 28 analyzed sessions (§2.2). N1 was detected in 220,081 ECAPs (§3.6); these waveforms are repeated measures, not independent participants. A high-confidence ROC discarded 43.6% of waveforms; this is not independent validation of a biophysical forward model. |
| [S767 — Brucker-Hahn et al., DOI 10.1088/1741-2552/aceca4](https://iopscience.iop.org/article/10.1088/1741-2552/aceca4) | §2.1 experimental data acquisition, §2.2 ECAP processing, Results and Fig. 8: clinical growth curves, artifact processing and modelled recruitment sensitivity to dorsal-CSF thickness. | 284 growth curves from 45 participants (56 recruited; 11 did not contribute analyzable curves). Repeated curves are not independent participants. Modelled axon counts remain model outputs. |
| [S787 — Gmel et al., DOI 10.3389/fnins.2021.673998](https://pmc.ncbi.nlm.nih.gov/articles/PMC8320888/) | Methods “Artifact Reduction” and “Growth Curve”; Figs. 1, 5–7: 14 participants, 112 ECAP curves, 50-response averaging and a defined P2–N1 threshold/growth analysis. | Human ECAP/perception/discomfort measurements. They do not quantify axon counts or pain relief; reported curves are repeated measurements within 14 people. |
| [S789 — Gmel et al., DOI 10.3389/fnins.2021.625835](https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2021.625835/full) | Methods “Experiment Setup”, Results Figs. 2–4: frequency sweeps, amplifier blanking and ECAP/sensation observations. | 20 recruited patients; analyzable ECAP sweeps from 16 people. ECAP amplitude and reported sensation moved differently across frequency; no pain-relief endpoint. |
| [S363 — Brucker-Hahn et al., DOI 10.1016/j.neurom.2025.06.008](https://pubmed.ncbi.nlm.nih.gov/40767809/) | Abstract, “Materials and Methods”, “Results”: anatomy-driven FEM/cable/reciprocity model with imaging and epidural recordings from six swine. | Animal, not human validation. The abstract supports qualitative anatomy/configuration dependence; no held-out-animal or patient test is reported. |

The source-specific methods conflict in clinically consequential ways. S766/S764 model monophasic 210-µs pulses; S765/S767/S787 measure human responses with different biphasic waveforms. They also use different lead montages, reference contacts, blanking/averaging and peak windows. These values must remain tagged to their source and setup; do not merge them into a fictitious universal ECAP protocol.

## 3. Forward model contract

For recording contact pair `$m$`, define the observed waveform as

\[
y_m(t)=\mathcal{A}_m\{\mathcal{R}_m[\sum_i v_i(t;\theta_{field},\theta_{fiber},\theta_{stim})]+a_m(t)\}+n_m(t),
\]

where `$v_i$` is the extracellular contribution of fiber `$i$`, `$\mathcal{R}_m$` is the recording transfer operator (including contact/reference geometry and, if justified, reciprocity), `$a_m$` is the stimulus/electrode artifact at the recording input, `$n_m$` is post-amplifier acquisition noise, and `$\mathcal{A}_m$` is the documented amplifier/digitizer/filter chain, including clipping and blanking behavior. The equation is a bookkeeping contract, not evidence that components are independently identifiable or that the operator is calibrated.

### 3.1 Stimulus and timing

Record the actual commanded and delivered waveform per trial: phase polarity/order, phase widths, interphase interval, current/voltage mode, amplitude, repetition rate, pulse timing, stimulation contacts, compliance/clipping and firmware/device version. Derive time zero from an observed pulse marker or a documented signal rule; preserve the original time axis. Timing definitions are source-specific: S765 uses the largest artifact derivative at the trailing edge and baseline-corrects against −5 to −2 ms; S767 defines N1/P2 windows relative to the leading edge; S787 applies a 200-µs post-stimulus delay (time zero = end of stimulus + 200 µs) to blank the stimulus-coincident artifact and uses N1/P2 windows 0.3–0.6/0.7–1.1 ms; S789 reports amplifier blanking from 0 to 1 ms. S765 fits artifact in 0.375–4 ms and searches N1/P2 in 0.375–2.1875 ms; S105 uses a 0.375–8-ms artifact fit and 0.375–2.375-ms feature interval. Do not assume 50 Hz, 210 µs, monophasic, a 30-µs gap, or a universal peak window: these are different source/device settings. A model input should match the target recording protocol or the waveform mismatch must be an explicit domain limitation.

Examples show why waveform bounds must stay tied to their source: S766 model uses current-controlled monophasic cathodic pulses, 210 µs, 50 Hz, 1–10 mA; S764 model uses bipolar monophasic 210-µs stimulation at 8 mA total (±4 mA/contact); S767 human recordings use cathodic-leading symmetric biphasic pulses, 30-µs interphase interval and 90–300-µs phase widths at 50 Hz; S765 uses an asymmetric charge-balanced biphasic waveform with a 1-ms charge-balance phase and alternates polarity per pulse; S787 tests guarded-cathode tripolar stimulation at 50 Hz and 60/90/120-µs widths; S789 uses biphasic tripolar stimulation and 30/100/240-µs widths in sweeps from 2–455 Hz. These are protocol examples, not interchangeable settings or a recommended universal waveform.

For one more source-specific timing example, S767 locates N1 at 0.75–1.05 ms and P2 at 1.05–1.45 ms after the leading edge, with windows shifted when ECAP onset is delayed by pulse width (Methods §2.2). Its 30-µs interphase interval is reported in Methods §2.1. S787 uses a 200-µs post-stimulus delay and N1/P2 windows at 0.3–0.6/0.7–1.1 ms (Methods “Artifact Reduction”).

### 3.2 Geometry and volume conduction

Freeze the lead type, contact dimensions and spacing, orientation, stimulation/reference/recording contacts, contact polarity, inter-lead offset, spinal level, and the source of anatomical geometry. Examples that must stay study-specific: S766's lower-thoracic eight-contact modeled lead is 1.3 mm diameter, 3-mm contacts, 4-mm spacing, with C7 stimulation and C0 reference (Methods “FEM of SCS”/“Calculation of ECAP recordings”); S764 uses an eight-contact, 1.3-mm-diameter percutaneous lead with 3-mm contacts, 4-mm inter-contact spacing and 300-µm modeled scar layer, plus three-segment directional contacts (Methods, Fig. 1); S765 records two externalized eight-contact leads with 1–2-contact offsets, stimulates caudal contacts 7/8 and records from a rostral channel, uses on-lead reference #9 and different ground arrangements in its two participants (Methods §§3.1–3.3/Tables 1–2); S768's model reports differential E8−E7 recording against E2 (Methods §§1.3–1.4/Fig. 3); S787 uses staggered overlapping externalized leads and guarded-cathode stimulation at one end with recording at the other (Methods “Leads, Stimulating, and Recording System”); S789 uses two eight-contact leads with 8-mm contact spacing, overlapping 2–4 contacts around T9/T10 (Methods/Table 1). These configurations are examples, not interchangeable montages.

Use a subject-specific image/mesh only when it is available and authorized; otherwise label the anatomy as canonical or borrowed. Record each tissue compartment and conductivity tensor/scalar, boundary conditions, solver/version, mesh/convergence criteria, electrode encapsulation/impedance assumption, and any transformation from stimulating to recording contacts.

Prior models use FEM volume conductors and multicompartment axons; S766/S768/S764 use reciprocity to calculate a recording potential from membrane currents. S766 uses a purely resistive lower-thoracic model and reports an encapsulation conductivity of 0.11 S/m selected to match a modeled mean impedance of 359 Ω; S768 uses a different parameterization (for example, dura conductivity 0.03 S/m versus 0.60 S/m in S766). These are model assumptions, not measured patient-specific tissue properties. Keep parameter sets versioned per source/model; do not average conflicting conductivity or encapsulation values. Demonstrate mesh and solver convergence before interpreting waveform differences.

### 3.3 Recruitment, propagation, and neural source

Represent the stimulation field as input to a declared fiber model and distribution. Record axon class/diameter distribution, paths, density, membrane model, temperature, node parameters, propagation delay, and activation criterion. Separate empirical variables (stimulation current, recorded growth curve, N1 latency) from latent outputs (number/percentage of activated axons, diameter composition, thresholds inferred by a model). The 10%-of-dorsal-column activation “sensory threshold” and a 1.4× discomfort-threshold rule used in model papers are conventions, not patient-level axon counts.

S767's Fig. 8E–F modelling shows that a fixed 25-µV ECAP can require 94% more modelled axons at 4.4-mm versus 2.0-mm dorsal-CSF thickness. S363 reports swine waveform dependence on anatomy/contact configuration at similar modelled activation. S766 Fig. 5 reports morphology/amplitude changes with longitudinal position or CSF thickness and weak changes with a 2-mm lateral shift. Therefore, ECAP amplitude alone does not identify a unique recruited-fiber count; geometry can be weakly identifiable from waveform shape. Any latent recruitment estimate must carry geometry/fiber uncertainty and be tested against measurements across current levels, recording contacts and/or configurations.

### 3.4 Electrode interface, artifact, and amplifier recovery

Store raw recordings before artifact correction. Preserve separate channels for stimulation, recording and reference, plus pulse markers. Record amplifier input range, recovery/blanking duration, gain, digitizer range/resolution, sample rate, online filters and hardware saturation flags. Treat blanked/clipped intervals as missing observations; do not replace them with zero-valued neural data. Preserve polarity-specific sweeps: S765 reports anodic/cathodic ECAP timing and amplitude differ, so polarity averaging can erase neural differences.

Use artifact handling as an explicit, versioned observation component: source-specific blanking/gating, baseline correction, fit window, model family, optimizer, residual diagnostics and excluded-data rule. S765 compared single/double exponentials and a second-order polynomial on two participants, fitting 0.375–4 ms after stimulation and analysing anodic/cathodic signals separately; the best fit depended on polarity/feature, and polynomial fitting was faster. S105 compared exponential and polynomial families on a larger repeated-waveform collection, with a 0.375–8-ms fit window; 99.2% of waveforms fit at least one exponential, while its high-confidence procedure discarded 43.6% of waveforms. Neither establishes a universally valid artifact model. Other sources use 200-µs digital blanking or a 0–1-ms amplifier blank. These approaches have different blind windows and should not be collapsed. S786's saline bench result concerns electrode double-layer pulse tails; it does not set a human neural-response recovery time.

### 3.5 Sampling, filters, noise, and missingness

The acquisition chain must be part of the forward specification, not an unmodelled post-processing step. In S765 the raw recording was 24-bit over ±132 mV at 32 kHz; the stored online-filtered file was 16-bit with a user-defined ±100 mV range. S105 also reports 32-kHz/24-bit acquisition over ±132 mV. The stimulator waveform clock was 40 kHz while recording was 32 kHz in S765, causing pulse-phase drift/beating in artifact timing; the authors recommend matching rates where possible. That study recommends at least 8 kHz for its ECAP metrics; down-sampling to 2 kHz changed P2–N1 materially, and sampling at 4 kHz or below degraded signal quality. A 0.1-Hz online high-pass was enabled after a railing event; offline options included a 100-ms median filter, 80-Hz high-pass and 3-kHz low-pass. The low-pass produced ringing and altered waveform metrics in that study. These settings are evidence about those systems and datasets, not universal device specifications.

The cited primary methods do not report a common CMRR, input-referred noise density, or universal noise distribution. S767 reports a 4-µV detectability floor; 156/479 trials had no measurable ECAP and 4/56 participants had no measurable response in any tested configuration. S765 documents a saturation/railing event and a 60-Hz component in one ground configuration. Record measured pre-stimulus and no-stimulation residuals by participant/session/configuration; estimate noise empirically when available. Do not impose Gaussian/white noise or a single fixed noise floor without calibration. Store missingness reasons separately: no response above floor, blanking overlap, saturation, channel rejection, or processing failure.

## 4. Prespecified output vector and comparison

For each source-compatible stimulation setting and recording pair, retain the complete differential waveform and the following predeclared features:

1. P2–N1 peak-valley amplitude and N1 latency, using only that source's stated post-stimulus window/zero-time convention.
2. Presence/absence of measurable response with an explicit detection limit and a separate missingness code.
3. Amplitude-versus-current growth curve and its threshold/spread parameters only where the human protocol supports their operational definition.
4. Across-contact or across-configuration waveform changes and propagation latency only where those channels and geometry are actually available.
5. Artifact-fit residual/error and the time interval masked or excluded; pre/post-filter waveform preservation.

Freeze units, windowing, filters, polarity grouping, detection floor, feature extraction code, and acceptance bounds before the independent test. Because published protocols use different windows and processing, report both raw/source-compatible outputs and any harmonized derived values. Do not compare harmonized values as if the acquisition protocols were identical. S765 specifically shows that filtering and sampling can change peak timing/amplitude and that some fits leave peaks undetectable.

## 5. Identifiability and required sensitivity checks

The observation model is underdetermined unless the acquisition geometry and recording chain are constrained. Similar measured amplitudes can result from changes in recruited population, fiber size/conduction velocity, dorsal-CSF thickness, lead position/orientation, reference montage, stimulation waveform, electrode interface, artifact subtraction, filtering, and noise. Several of these are not independently measured in existing datasets. Thus waveform fit alone cannot establish the latent axon count or prove a unique physiological explanation.

Before estimating any latent quantity:

- profile sensitivity to anatomy/CSF thickness, contact position/orientation, conductivity/encapsulation, fiber distribution, waveform, artifact model, filter and detection floor;
- test parameter recovery on synthetic data generated from known parameters and report non-identifiable/equivalent parameter regions;
- evaluate contact/configuration and stimulation-current changes not used for fitting;
- where human data are authorized, split by participant and hold out at least one participant plus a configuration or setting; repeated sweeps from one participant are not a participant-level test;
- report uncertainty and abstain from absolute recruitment claims when posterior/profile intervals span materially different recruited populations.

These are proposed requirements, not completed tests. Existing sources do not establish a calibrated, uniquely identifiable human recruitment inverse model.

## 6. Validation ladder and falsification

Use separate evidence labels for (a) numerical/mesh checks, (b) bench saline/electrode-interface checks, (c) animal recordings, (d) human measurement-method checks, and (e) independent human forward-model validation. Passing one level does not imply the next. In particular, S764/S766/S768 are simulations; S363 is a six-swine study without a reported held-out-animal test; S765 is a two-participant acquisition/artifact-method study; S767/S787 provide human ECAP measurements but do not independently validate the full forward operator. S766's single previously published trace comparison is not a participant-level test.

The model fails its declared scope if any pre-registered, source-matched required waveform feature, latency, growth curve, artifact residual, calibration or uncertainty criterion misses its bound on the independent participant/configuration test; if it only fits participants/settings used to tune it; or if plausible geometry/noise alternatives produce equally good waveforms but materially different recruitment estimates. Set numeric bounds from the authorized training/reference data before unblinding a test set. No numeric universal tolerance is asserted here because the source protocols and acquisition chains differ and the available audits do not provide one validated common reference.

## 7. Execution gates and explicit non-claims

- `EXP-01` remains open; the Drosophila H1 model cannot be counted as an ECAP measurement result.
- Obtain an authorized human ECAP dataset and documented participant/session/electrode split before participant-level calibration or independent testing. Existing publications and aggregate curves do not authorize raw-data access.
- Freeze hardware/firmware, geometry, waveform, preprocessing, missingness policy, numeric tolerances, and validation split before running the forward-model comparison. Record exact code/data/environment hashes.
- No experiment has been conducted for this draft. It does not establish that ECAP measures subjective pain, predicts pain relief, validates Drosophila-to-human transfer, or demonstrates SCS efficacy.

## 8. Evidence pointers

- Local summary: [ECAP/SCS primary-source audit](../../data/ecap-scs-audit.json), especially `ns07_forward_model_review`, `ns08_artifact_review`, and `ns09_recruitment_review`.
- Existing human-data constraints: [human ECAP/SCS access audit](../../data/human-ecap-scs-access-audit.json). Access, consent, linkage and participant-level independence remain separate gates.
- This is a methods specification only. Novelty/saturation and H1 dependencies remain governed by [TODO](../../TODO.md).
