# Staging area

`inbox/` is a local, ignored drop zone for candidate JSON batches. Files placed
there are not evidence and are not visible through the HTTP API until they pass
review and are explicitly published.

Workflow:

1. Copy `source-record.template.json` and fill every field.
2. Run `researchctl stage data/staging/inbox/<file>.json` from the repository root.
3. Resolve every error and manually inspect warnings, especially same-title hits.
4. Record a screening decision and provenance in the candidate.
5. Dry-run `researchctl publish <file>`.
6. Publish with `researchctl publish <file> --apply` only after review.

Publishing creates a timestamped, hashed pre-change snapshot. New records enter
the canonical registry as unclustered; thematic cluster assignment is a separate
expert decision.
