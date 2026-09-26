# Data layout

`data/` is the research sidecar's current information base. The top-level files have distinct roles:

- `records.json`, `aliases.json`, `clusters.json`, `ST.json`: canonical source, alias, cluster and resource records.
- `source-record.schema.json`, `vocabularies.json`, `scientific-contract.json`: machine contracts and controlled values.
- `evidence-matrix.json`, `human-dataset-matrix.json`, `novelty-landscape.json`, `dissertation-concept.json`: current claim, dataset, novelty and dissertation models. The scientific gate remains `G0_REVISE` until explicit author and supervisor decisions.
- `audit-report.json`, `validation-log.json`, `completeness-report.json`: the latest integrity and curation results.
- `search-protocol.json`, `src07-coverage-ledger-2026-09-25.json`: current search routes and unresolved 2026-source checks.
- `runtime-audit.json`, `drosophila-connectome-audit.json`, `drosophila-nociception-audit.json`, `synthetic-domain-audit.json`, `ecap-scs-audit.json`, `scs-outcome-audit.json`, `human-ecap-scs-access-audit.json`, `ecap-trial-registry-audit.json`, `ns04-perturbation-model-audit.json`, `ns06-prior-art-audit.json`, `ns11-prediction-audit.json`, `ns15-russian-prior-art-audit.json`, `forbidden-transfer-audit-2026-09-25.json`: living domain reviews. They preserve source-specific limits, access status and open questions.
- `evidence-review-ledger.json`: 27 earlier matrix-locator and correction reviews preserved as complete JSON objects. Each entry is keyed by its original filename and retains the SHA-256 of that original file. A reference of the form `evidence-review-ledger.json#name.json` means the `entries[name.json]` object, not a separate file.

`curation/` holds review batches and queues used by the curation workflow. `staging/` retains the source template and an empty inbox; published candidate JSON is removed once its IDs and primary locators are in the canonical registry. `archive/` keeps the two newest rollback snapshots plus two migration baselines; older full copies are pruned. Historical test inputs live under `tests/fixtures/history/`.

Use `researchctl stage`, `researchctl publish --apply`, and `researchctl validate` for source changes. A passing JSON integrity check establishes internal consistency; it does not confirm human data access, clinical effects or scientific novelty.
