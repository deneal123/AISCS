---
name: aspa-research-curation
description: Safely collect, validate, deduplicate, and publish dissertation evidence into the Aspa research knowledge base.
---

# Aspa research curation

## Purpose

Use this workflow when adding or reviewing sources in this directory. The canonical
contract is defined by `data/source-record.schema.json` and `data/vocabularies.json`; never
reconstruct a competing ad-hoc schema in chat.

## Required reading

Before changing data, read:

1. `README.md` for commands and current corpus status;
2. `docs/data-contract.md` for evidence boundaries;
3. `docs/curation-workflow.md` for screening and publication rules;
4. `data/source-record.schema.json` and `data/vocabularies.json` for exact machine values.

## Scientific boundaries

- Keep noxious stimulus, nociceptive response, protective behavior, human
  self-reported pain, ECAP recruitment, and clinical SCS response distinct.
- Never label a Drosophila simulation target as subjective human pain.
- Never treat ECAP as a direct pain measure.
- Never infer human or SCS transfer from simulation results alone.
- Do not use one-person self-experimentation as evidence of effectiveness or
  cross-subject generalization.
- An unverified or pending record is a work item, not evidence for a claim.

## Source collection

For every candidate, preserve the exact search query or seed, retrieval date, and
origin. Prefer primary publications, official dataset pages, and official code
repositories. Search snippets, news, vendor copy, and homepage-only URLs cannot
validate a technical claim.

Verify at least:

- exact title, authors, year, venue, DOI/PMID/dataset ID, and exact URL;
- species/population, sample size, target construct and target label;
- modalities, dataset access, method, metrics and limitations;
- split unit, cross-subject or external validation where reported;
- whether full text or only metadata was checked.

Schema 2.0 requires a `field_resolution` entry for every nullable scientific field.
Use `reported`, `not_reported`, `not_applicable`, or `unavailable_after_search` with
a reason, date, and locator. Never leave `unknown`, an empty string, an unexplained
`null`, or `Не указано`; never invent a metric or upgrade a status without primary evidence.

## Safe write workflow

Generate a candidate with the next free ID:

```powershell
uv run --frozen researchctl new "Exact source title" --output data/staging/inbox/source.json
```

Fill the candidate, then run:

```powershell
uv run --frozen researchctl stage data/staging/inbox/source.json
uv run --frozen researchctl publish data/staging/inbox/source.json
```

Both commands above are non-mutating. Review all same-title warnings manually.
Publish only after that review:

```powershell
uv run --frozen researchctl publish data/staging/inbox/source.json --apply
```

Publishing creates a hashed pre-change snapshot and adds new records to the
unclustered queue. Only the two newest rollback snapshots and explicitly pinned
migration baselines are retained under `data/archive/`. Do not assign a cluster automatically merely because terms
overlap.

## Deduplication

Match in this order:

1. DOI, PMID, patent ID, dataset ID;
2. normalized exact title;
3. title plus authors/year/venue;
4. manual comparison of preprint, conference, and journal versions.

Do not delete traceability. A confirmed duplicate becomes an entry in
`data/aliases.json`. Keep uncertain semantic matches canonical and flag them for manual
review. Do not rerun `migrations/rebuild_2026_09_21.py` to add a source: it is a one-time,
reproducible migration from the frozen 2026-09-21 snapshot.

## Required gates

Before handing off any data change, run:

```powershell
.\scripts\check.ps1
```

The handoff must report:

- new or changed canonical IDs;
- validation and screening statuses;
- duplicate or same-title decisions;
- snapshot path if publication was applied;
- integrity, lint, and test results;
- remaining evidence limitations.

Do not describe the corpus as validated merely because JSON integrity passes.
