# claims engine

Detection of liquid claims — money that already belongs to an identifiable
beneficiary — from Colombian public data. First radar: expiring judicial
deposits published semiannually by the Rama Judicial (Law 1743 of 2014).

Full background, legal context, glossary and decision log:
[`docs/project-context.md`](docs/project-context.md). Architectural rules and
conventions: [`CLAUDE.md`](CLAUDE.md).

## Status

Phases 0–4 (profiling → canonical model → ingestion → identity → lifecycle)
are done. Phase 5 (external enrichment via RUES) is in progress. Phase 6
(role inference) is deferred — see `docs/project-context.md` §7.

Current phase: **storage and enrichment only.** Commercial exploitation
(outreach, scoring-for-sales, contact workflows) is explicitly out of scope.

## Architecture

```
raw/ (S3, immutable)  →  staging/ (Parquet, one table per source)
                       →  core/ (canonical model: file, capture, claim,
                          observation, claim_party, party, court, enrichment)
                       →  marts/ (inferences + serving, not built yet)
```

Every radar implements the same four-operation contract — `discover()`,
`capture()`, `normalize()`, `health()` — over shared identity, lifecycle and
serving infrastructure. See `CLAUDE.md` for the full layer conventions and
non-negotiable rules (immutable raw, deterministic IDs, no silent row loss,
facts vs. inferences).

## Stack

Python, `uv`, `polars` (Excel via `calamine`), `duckdb`, `pandera` contracts,
`pydantic` + `typer` for the CLI, `httpx` + `tenacity` for RUES, Parquet on
S3 partitioned by period. See `CLAUDE.md` for the full list and what's
deliberately excluded.

## Setup

```bash
uv sync
```

### Local AWS credentials

Pipeline commands call `boto3.client("s3")` with no explicit profile, so they
rely on whichever profile resolves as default. If your `~/.aws/credentials`
has multiple profiles (e.g. an MFA/role-assumption setup for other AWS
accounts under `[default]`), point this project at the `amud-technologies`
profile without touching your global shell config:

```bash
echo "AWS_PROFILE=amud-technologies" > .env   # already gitignored
uv run --env-file .env claims-engine <command> ...
```

`uv run` doesn't read `.env` automatically — `--env-file .env` (or an
`AWS_PROFILE=amud-technologies` export scoped to your session) is required
each time. `pytest`/`ruff` need no AWS access at all (S3 is mocked via
`moto` in the test suite).

## Commands

```bash
ruff check .
pytest
```

## CLI

All commands are exposed under the `claims-engine` entry point
(`src/claims_engine/cli.py`):

| Command | Purpose |
|---|---|
| `profile-s3-prefix` | Phase 0 — profile every sheet of every file under an S3 prefix, degrading unreadable sheets to `<READ_ERROR>` rows instead of aborting |
| `normalize-s3-prefix` | Phase 2 — normalize raw files into `stg_jd_published_deposit` / `stg_jd_reject` Parquet on S3, enforcing `rows_ok + rows_rejected == rows_read` |
| `build-lineage` | Builds `core/{file,capture}` from the raw listing and already-written staging output |
| `build-identity` | Phase 3 — builds canonical `core/{party,court,court_name}` from staging; backfills `document_type` from RUES lookup history in `core/enrichment/` |
| `build-lifecycle` | Phase 4 — builds canonical `core/{claim,observation,claim_party}` from staging |
| `enrich-parties` | Phase 5 — queries RUES for not-yet-enriched parties of any document type (D26 — no `legal_entity` pre-filter), writes a dated batch to `core/enrichment/`. RUES's own `Categoria` field is the source of `document_type` |

Run `claims-engine <command> --help` for arguments; every command takes the
S3 bucket as its first argument. `normalize-s3-prefix`/`build-lineage` also
take an explicit S3 prefix — default is the semiannual expiring-deposits
radar; pass e.g. `raw/judicial-branch/active-deposits/2026-08-30/` for an
irregular active-deposits batch (see `docs/project-context.md`).

## Non-negotiable rules

See `CLAUDE.md` for the full list. In short: `raw/` is immutable,
normalization is a pure function of (raw file + code version), IDs are
deterministic hashes, no row is dropped silently, facts and inferences never
share a table, and enrichment is never performed for natural persons.
