---
name: aspa-research-curation
description: Safely collect, validate, deduplicate, and publish dissertation evidence into the Aspa research knowledge base.
---

# Aspa research curation

## Purpose

For evidence retrieval use `search_knowledge`, `graph_context`, `get_evidence`, and
`knowledge_status`; see [knowledge guide](knowledge/README.md). Inspect the returned
primary locator, verification status and scientific restrictions before using a hit.
Keep `include_unreviewed` disabled for scientific answers. Similarity and graph navigation
do not establish novelty, causal transfer, pain measurement or clinical validity.

Use this workflow when adding or reviewing sources in this directory. The canonical
contract is defined by `data/schema/source-record.schema.json` and `data/schema/vocabularies.json`; never
reconstruct a competing ad-hoc schema in chat.

## Required reading

Before changing data, read:

1. [README](README.md) for commands and current corpus status;
2. [Data contract](docs/reference/data-contract.md) for evidence boundaries;
3. [Curation workflow](docs/reference/curation-workflow.md) for screening and publication rules;
4. [Source schema](data/schema/source-record.schema.json) and [vocabularies](data/schema/vocabularies.json) for exact machine values.

Use [TODO](TODO.md) for current criteria and statuses. Read only the relevant task
section of the [decision ledger](docs/audits/todo-decision-ledger.md) when earlier
checks or superseded requirements are needed; historical open states do not
override the current TODO.

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

Pi workers are read-only reviewers of primary routes. If a query needs a raw
response for local inspection, put it under ignored `.work/pi-scratch/`, then
record only checked query parameters, dated dispositions and primary locators in
the living audit. Do not create raw query directories in `data/`.
For every Codex subagent and Pi worker task, state that the project directory is
`R:\Aspa\research` even if the bridge starts in `R:\Aspa`. Require the worker to
change to that directory before running commands and to write every temporary
download, probe, script, log, and intermediate file under `R:\Aspa\research\.work`.
Do not create scratch files in the superproject root.
Avoid bare `>nul`, `>NUL`, and similar discard redirections in worker shell
commands: under the bridge's Windows working directory they can create a real
`nul` file in the superproject. Redirect diagnostic output to `logs/` inside
the worker's assigned artifact directory instead.
For Picodex tasks, assign a unique folder
`.work/pi-workers/<bridge-id>/<task-id>/` before submission. The worker writes
`result.md` there with task ID, check date and the sections `Status`, `Primary
locators`, `Verified findings`, `Unresolved`, and `Saved files`; optional raw
responses go in `raw/` and logs in
`logs/`. Resume the same Pi thread in that folder. The Codex coordinator keeps
`.work/pi-workers/<bridge-id>/jobs.json` with `run_id`, `project`, and entries
containing `task_id`, `job_id`, `thread_id`, `status`, and `result_path`; it
writes each receipt immediately after submit, then independently checks the
result before updating canonical files. Missing receipts stay explicit with
null IDs; a saved result alone does not prove `agent_settled`.
Write the run registry and worker results as UTF-8 without a byte-order mark.
For failed, cancelled, or interrupted jobs without a worker result, the
coordinator writes a `result.md` status stub in that task folder and does not
integrate unfinished claims.
Prune unused raw downloads from failed/cancelled jobs after recording their
status; retain the stub, run registry and a small diagnostic log. Verify the
resolved task path before removing anything. If automatic approval review
rejects cleanup, retain the files and report the exact path and reason.

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

Publishing creates a hashed pre-change snapshot under ignored
`.work/research-snapshots/` and adds new records to the unclustered queue.
Only the two newest automatic rollback snapshots are retained there; explicit
snapshots and migration baselines remain under `data/archive/`. Do not assign a
cluster automatically merely because terms overlap.

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
