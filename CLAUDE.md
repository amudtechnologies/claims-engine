# Claims engine — project instructions

Detection of liquid claims (money that already belongs to an identifiable
beneficiary) from Colombian public data. First radar: expiring judicial deposits
published semiannually by the Rama Judicial.

Full background, legal context, glossary and decision log: @docs/project-context.md

## Current phase

Storage and enrichment only. Commercial exploitation is explicitly out of scope —
do not build outreach, scoring-for-sales, or contact workflows yet.

Exception: `web/` (see below) includes a NIT search — a search bar in the home
hero, submitting to a consolidated `/resultados/` page — rather than behind a
separate nav destination — it's the only working feature so far and should be
visible on arrival, not one click away. This is an informational self-lookup —
someone enters a NIT and sees only what's on record for it — the same D24
self-lookup pattern, for legal entities instead of natural persons, not outbound
outreach or sales scoring. `/resultados/` renders one row per radar (today, only
Depósitos judiciales has real data; other radars are listed as "En desarrollo"
with no numbers — never fabricated placeholder figures). It deliberately omits
any probability/validation scoring split: that's the inference layer (Phase 6),
explicitly out of the active plan (§7), and any "which finding is worth acting on"
signal is a scoring-for-sales judgment this phase doesn't build. It queries
`core/*` directly (`judicial_deposits/party_search.py`), recomputing a
`marts.party_summary`-shaped aggregation at request time — there is no
materialized marts table yet (marts/Phase 6 is still deferred, per §7). It reads
from a local Parquet cache (`judicial_deposits/core_cache.py`, synced from S3 by
`python manage.py sync_core_cache`, decoupled from the request path) rather than
live S3: `core/` Parquet isn't partitioned by `party_id`, so a filtered read
against the real bucket range-scans most of the file over HTTP (15-50s per
query, measured); the same query against a local copy is sub-100ms.

Phases 0–4 (profiling → canonical model → ingestion → identity → lifecycle) are
done. Phase 5 (external enrichment) is in progress. Phase 6 (role inference) is
removed from the active plan for now — see `docs/project-context.md` §7 for why.

Phase 0 (profiling) findings are in `docs/project-context.md` §3; the full column ×
file matrix is `docs/phase0_schema_matrix.csv`, produced by `claims-engine
profile-s3-prefix`.

## Non-negotiable rules

These are architectural commitments. If a task seems to require breaking one, stop
and raise it instead of working around it.

1. **`raw/` is immutable.** Never write to, edit, or delete anything under `raw/`.
   It is the irreplaceable source of truth.
2. **Every normalization must be a pure function of (raw file + code version).**
   Full reprocessing from raw must always be possible. No manual patches to
   downstream tables.
3. **Deterministic IDs.** All surrogate keys are hashes of the natural key, never
   sequences. Reprocessing from scratch must produce identical IDs.
4. **No silent row loss.** Rows that fail normalization go to a rejects table with
   the raw row and a reason. Invariant: `rows_ok + rows_rejected == rows_read`.
   Assert it, don't assume it.
5. **Facts and inferences never share a table.** What the source asserts is a fact.
   What we conclude (economic role, deadline, priority) is an inference, stored with
   a probability and a `rule_id`.
6. **Procedural role is not economic role.** `plaintiff` / `defendant` is a fact from
   the source. `creditor` / `debtor` is an inference. Never collapse them.
7. **Before adding a column to a `core` table, ask whether it would make sense for
   the insolvency radar.** If not, it belongs in the `attributes` JSONB field.
   Source-specific fields never become canonical columns.
8. **RUES is the classifier, and enrichment has no document-type discrimination.**
   Every `document_number` is queried against RUES — never pre-filtered by a guessed
   `legal_entity`/`natural_person` split. RUES's own `Categoria` field is the sole
   source of truth for `party.document_type`; it is never inferred from the NIT
   check-digit algorithm. Every RUES match is enriched (name, status, `attributes`),
   regardless of category. A party with no RUES match is a valid, permanent
   unenriched state — not a TODO. This still touches Law 1581 the moment a national
   ID is joined to money and enriched with a name — see D23/D24 and the privacy
   section in the context doc (D26 records why the old NIT-only assumption was
   wrong).

## Stack

- Python only. `uv` for envs, `ruff` for lint, `pytest` for tests.
- `polars` with the `calamine` engine for Excel reads (source files are large,
  multi-sheet, with title blocks above the header row).
- `duckdb` as the analytical engine — an in-process library, not a service.
- Parquet on S3, Hive-partitioned by publication period.
- `dbt-duckdb` for transformations.
- `pandera` for data contracts at layer boundaries.
- `pydantic` for radar configuration and contracts, `typer` for the CLI.
- `httpx` + `tenacity` for external API calls (RUES).
- `unidecode`, `rapidfuzz` for text normalization and fuzzy grouping.
- Postgres is the **serving layer only** — materialized `marts` tables plus the
  system's own transactional tables. It is not part of the pipeline.

Deliberately excluded as oversized for this data volume: Spark, EMR, Glue jobs,
Redshift, Snowflake, Airflow, Dagster, Kafka, Iceberg. Do not introduce them.
Total data volume across all radars is measured in tens of millions of rows.

GitHub Actions runs the pipeline commands — one workflow per phase under
`.github/workflows/`, manually triggered except `enrich-parties` (daily cron), which
now does both the RUES lookup/classification and the enrichment write in one pass —
`check-document-types` no longer exists as a separate workflow, folded into
`enrich-parties` per D26. `build-identity` runs automatically right after
`enrich-parties` succeeds (`workflow_run`), so newly-learned `document_type`
classifications land on `core/party` without a manual trigger. This is not an
exception to the Airflow/Dagster exclusion above: no DAG engine, no backfill UI,
just cron plus one `workflow_run` chain. See `docs/project-context.md` decisions
D25/D26/D27.

## Layer conventions

| Layer | Directory | Contains | May do |
|---|---|---|---|
| Raw | `s3://amud-technologies/raw/` | Source files, byte-for-byte | Nothing |
| Staging | `models/staging/` | One table per source | Shape only: types, headers, structural cleanup |
| Core | `models/core/` | Canonical shared model | Identity resolution, cross-source integration. Still facts |
| Marts | `models/marts/` | Query surface | Aggregates and inferences |

(These correspond to bronze / silver / gold in medallion terminology.)

Each layer may only do its own kind of work. Staging never decides who owns money.
Core never computes priorities. Marts never fixes parsing.

Raw lives only on S3, never as a local repo directory — there is nothing to check
out and nothing to gitignore. The `models/` subdirectories are created when a phase
actually starts writing to that layer, not pre-scaffolded ahead of need. Staging is
currently produced in Python (`src/claims_engine/normalize.py`) writing Parquet
straight to S3, not yet as `dbt-duckdb` models — `models/staging/` doesn't exist yet
for that reason.

## Radar contract

Every source implements the same four operations. Everything else — storage,
identity, inference, serving — is shared infrastructure the radar does not touch.

1. `discover()` — what is new at the source
2. `capture()` — fetch to `raw/`, immutable
3. `normalize()` — map to the canonical claim schema
4. `health()` — freshness, volume delta, rejection rate

Adding a radar should mean writing an adapter, not modifying the core.

## Web

`web/` is a Django project — the public-facing site, separate from the pipeline
layers above (it consumes what the pipeline produces; it never writes to
`raw/`/`staging/`/`core/`/`marts/`). Two apps so far:

- `home` — the Amud Technologies company page. Amud is the claims engine in
  general; judicial deposits is one radar under it, not the whole product. Its
  hero has the NIT search bar (`home/_search_form.html`, shared with the
  results page's own compact search bar), and its `results` view
  (`/resultados/`, `home/views.py`) renders the consolidated, cross-radar
  results page — the search's actual destination. `results` calls straight
  into `judicial_deposits.party_search`/`core_cache` for data; it's cross-radar
  by nature, so it lives here rather than inside one radar's app.
- `judicial_deposits` — owns the radar's query logic (`party_search.py`,
  `core_cache.py`), consumed by `home.views.results` above. Its own
  `/depositos-judiciales/` page is now an info-only landing page for the radar
  (what it is, aggregate stats) with a link back to the home hero search — it
  no longer renders a search box or results itself, to avoid two competing
  places search could happen. Queries `core/*` live via a local Parquet cache
  (see above) until a real marts aggregation exists to query instead.

Code (apps, views, templates, static files, variables, URL names) is named in
English like everything else in this repo. The exception is template *copy* —
the text a visitor actually reads — which is Spanish, since the site serves
Colombian visitors. URL slugs (e.g. `/depositos-judiciales/`) follow the copy,
not the code, and are Spanish too.

## Conventions

- **Every technical object is named in English** — tables, columns, functions,
  variables, files, directories, S3 paths, env vars, everything. No exceptions for
  domain terms: translate them too (`radicado` → `case_number`, `despacho` →
  `court_office`, `cuenta judicial` → `judicial_account`). The Spanish legal term is
  documentation, not an identifier — record the mapping in the glossary so the
  English name is traceable back to the source term. Comments and docs may use the
  Spanish term when quoting the law or the source file, but code never does.
- Currency stored as integer COP. Never floats.
- Currency parsing: decide the decimal separator by counting digits after the last
  separator. Three digits after → thousands separator. This is the single most
  expensive bug in this domain (off by 1000 or by 100, silently).
- National IDs stored twice: `*_raw` exactly as received, and normalized to digits
  only. NIT is stored without the check digit — this is the number one cause of
  failed RUES joins.
- Never hardcode the header row when reading source files. Detect it.
- Timestamps in UTC, business dates as dates.

## Commands

```bash
uv sync
ruff check .
pytest
```

Pipeline phases are `claims-engine` subcommands (`src/claims_engine/cli.py`) — see
`README.md` for the full table. Each has a matching GitHub Actions workflow under
`.github/workflows/` for running it against S3 directly, without a local checkout.

## When in doubt

The test for any core model change: could the insolvency radar (Supersociedades
creditor claims) use this table with only a new `type`, a new `source_id`, and
different `attributes` content? If it needs a new column or a new table, the model
is still shaped like judicial deposits wearing a generic name.
