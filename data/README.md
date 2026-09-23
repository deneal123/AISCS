# Data layout

This directory is the only runtime data root of the research sidecar.

- `records.json`, `aliases.json` — canonical sources and legacy-ID redirects;
- `clusters.json` — thematic projections over canonical source IDs;
- `ST.json` — tools, software and dataset resources;
- `source-record.schema.json`, `vocabularies.json` — machine contract;
- `audit-report.json`, `validation-log.json` — dated results of the current audit pass;
- `archive/` — immutable source and pre-publication snapshots with SHA-256 manifests;
- `staging/` — candidate template and ignored local inbox.

Do not edit archived files. Do not add a source directly to `records.json`: use
`researchctl stage` and `researchctl publish` so duplicate checks, snapshots and
integrity gates remain reproducible.
