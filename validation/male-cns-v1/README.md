# Frozen synthetic recognition check

This bundle distinguishes three model-input conditions from E1−REF for a known
registered input region. It does not recognize subjective pain, validate fly
nociception or establish human ECAP performance.

`protocol.json` was fixed before signal generation. Eight regions × 20 independent
seed/parameter groups × three paired conditions produced 480 signals. Whole groups
were assigned to train/validation/test: 288/96/96 signals and 96/32/32 groups.
All seven features use only the signal. Each regional logistic regression was fit
on training data; regularization was selected on validation data. `candidate.json`
and its SHA-256 in `frozen.json` precede creation of the test signals. No weights
or features were retuned after test access.

Primary held-out balanced accuracy: **71.875% (69/96)**; 95% bootstrap interval
over whole groups: **61.46–81.25%**. Recall: none 78.125%, strong 84.375%, weak
53.125%. A constant response scores 33.33%. The secondary pooled signal-only
classifier scores 72.917%; an advantage of conditioning on region was not shown.
Only four test groups per region are available. Errors and all 20 shuffled-label
controls are retained in `evaluation.json`; no biological generalization is claimed.

`dataset-registry.json` records configurations, partitions, features and raw-signal
hashes. Raw Parquet signals remain in ignored evaluation storage. `verification.json`
records an independent check of all 480 signals, 96 test predictions, partition
separation, and unchanged pretest weights. Recheck the public bundle from `generator/`:

```sh
uv run python scripts/verify_recognition_bundle.py --bundle validation/male-cns-v1
```

For a new evaluation use a new protocol and directory. `generatorctl evaluate-cns`
executes development first, then a separately requested test phase; it resumes
validated existing records. The numerical source/runtime identity, graph and
protocol are bound to the classifier. Missing, incompatible or out-of-domain
models return no prediction with a reason; the recording remains available.
