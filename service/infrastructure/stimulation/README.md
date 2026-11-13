# Stimulation infrastructure

- `field/`: field-summary computation and audit, graph export and preview.
- `population/`: population archives, event transport, target responses and diagnostics.
- `feedback/`: synapse discretization, observation audits and feedback checkpoints.
- `recording/`: current archives, replay exports and verified target recordings.
- `geometry_cache/`: authenticated geometry snapshots and bounded selected reads.
- `experimental_arbor/`: fail-closed mapping between tagged morphology edges,
  control volumes and vector-probe geometry, plus bounded sample and spike
  harvesting; not connected to published runs.

Selected reads authenticate the complete chunk and every source entry before
decoding only requested geometries. The optimized decoder is tied to the
reviewed `chunk.py` fingerprint; changes fall back to the original full reader.
- `contacts/`: verified contact screening, cable clearances and conservative broad phase.

The remaining modules at this level implement shared numerical field, geometry
and search primitives. In particular, several are part of the geometry-cache
producer fingerprint. Moving or editing them changes cache identity and requires
an explicit migration or rebuild, not a silent hash substitution.

Feedback checkpoint identity hashes service source paths and contents. A code
reorganization changes that identity: old checkpoints are rejected for resume,
while published artifacts remain readable under their recorded provenance.

During a feedback run, a bounded in-memory cache can reuse synapse observations
already checked against the index and source graph. The observation audit still
checks each scheduled pair and its projection onto the target morphology, and
rechecks source/index file identities before and after cache use. A cache miss
uses the verified index normally; no cache is reused across runs. This does not
establish synaptic transmission or physiological validity.

The synapse index can also fetch up to 128 exact source/target pairs in one
bounded scan. Pair membership and each graph-edge count are checked separately;
if its row limit is reached, population matching uses the existing per-target
query path. Source-row order is retained for every pair.

`swc_reference.py` also has the explicitly selected internal
`experimental_virtual_current` coupling. It permits nonuniform segment counts,
synaptic events and membrane-current recording. It is not exposed by the
simulation API or selected by default: its numerical and geometric validity,
network feedback and performance must be established for each intended use.
The source configuration records the coupling method. It does not run NEURON
on a GPU or imply biological calibration.

An additional internal `solver_backend='experimental_coreneuron'` is available
only with that coupling and fixed-step integration. It runs on CPU, requires an
isolated NEURON process, and records the solver choice in provenance. It is not
enabled by the service API or the standard population pipeline. Recorded
stimulus fractions are reconstructed from the specified pulse and recorded
time grid because CoreNEURON does not record the scalar playback used by the
reference path. Validate time, membrane currents, recording and events for the
intended configuration before considering this backend for a full run.
