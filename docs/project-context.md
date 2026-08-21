# Claims engine — project context

Background, definitions and decision log. Referenced from `CLAUDE.md`.
Last updated: 2026-08-17.

---

## 1. Objective

Build a **claims engine**: a system that detects money already belonging to an
identifiable beneficiary — a liquid claim with a determinable amount and legal basis —
by cross-referencing Colombian public data sources, and lets third parties act on
those findings.

The underlying thesis (30 ideas across three families) is that in these cases the
bottleneck is not legal but **informational**: the money exists, the legal basis is
clear, and nobody knows it is there.

**MVP scope:** judicial deposits only.

---

## 2. Legal context

Law 1743 of 2014 (arts. 4 and 5, amending arts. 192A and 192B of Law 270 of 1996),
regulated by Acuerdo PCSJA21-11731 of 2021.

| Concept | Rule |
|---|---|
| Unclaimed deposits | Prescribe **2 years** after final termination of the case |
| Labor-case deposits | Prescribe after **3 years** |
| Special-condition deposits | More than **10 years** since constitution |
| Beneficiary of prescription | The Nation – Rama Judicial, Fondo para la Modernización, Descongestión y Bienestar de la Administración de Justicia |
| Prior publication | Once, in a national newspaper and on the entity's website |
| Claim window | **20 business days** from publication, before the court that heard the case |
| Origin of the list | Judges report semiannually to the Consejo Superior de la Judicatura |

**Key implication:** the semiannual file is not a list of "deposits about to expire."
It is the **eviction notice** — the last 20 business days of the asset's life.

> Pending validation with Colombian counsel: the exact claim procedure, who may sign
> the request for release, and the edge cases around deposits belonging to public
> entities and labor deposits constituted extrajudicially.

---

## 3. The data source

Two possible detection paths: (1) scraping the case-lookup portal, and (2) the file
the Rama Judicial publishes twice a year. **The MVP uses path 2.**

### Current state

History loaded in S3 under
`amud-technologies/raw/judicial-branch/expiring-deposits/`, one folder per semester
starting at `2017-1`.

### Observed schema — Phase 0 findings across the full history (2017-1..2026-1)

Phase 0 profiled all 17 real publications in S3 (`.xlsb`, `.xlsx`, and `.xlsm` across
different periods — the format itself isn't stable either). Full column × file matrix:
`docs/phase0_schema_matrix.csv`. Tooling: `claims-engine profile-s3-prefix`.

The 2026-1 schema below is only the *current* shape, not the historical one:

`No. Depósito` · `Despacho Judicial` · `Cuenta Judicial` · `Identificación Demandante` ·
`Identificación Demandado` · `Valor` · `Fecha Constitución` · `Seccional` ·
`Departamento` · `Ciudad`

**What actually varies across periods:**

- **Column names drift every single period.** No two files share identical headers —
  synonyms, abbreviations, and reordering throughout (e.g. `Valor` vs `Valor Depósito`
  vs `Valor del Depósito`).
- **2017-1 is a structural outlier, not a smaller version of the current schema.** It
  carries `NUMERO DE RADICADO DEL PROCESO` (the case number) and both parties' names
  (`NOMBRE DEMANTANDE`, `NOMBRE DEMANDADO`) — fields absent from every file since. The
  "names and radicado are missing from this source" framing below only holds from
  2018 onward.
- **2018-1 has real data corruption:** 494 rows where the deposit number is a corrupted
  huge float (~7.6×10²²) instead of an integer. Confirms the `Valor`-style parsing
  fragility isn't limited to currency fields.
- **2023-1 unexpectedly drops a column** (11 → 10) relative to the periods immediately
  before and after it.
- The schema only settles into something close to the current 10-column shape from
  around 2024-1 onward.

**Multi-sheet workbooks exist, and the meaningful data is not always on the first
sheet:**

- **2018-2** has two sheets: `Hoja1` (24 rows, a pre-aggregated summary — count and
  total value per city) and `Publicar` (154,451 rows, the real per-deposit detail).
  Reading only the first sheet silently returns the wrong, tiny result.
- **2017-1** has two large sheets, not one: `D J EN CONDICION ESPECIAL` (117,691 rows)
  and `D J NO RECLAMADOS` (115,247 rows) — see the classification finding below.

### Reading of the schema

**It carries more than the statute requires publishing.** `Valor` is present, so
prioritization is possible, and both parties' national IDs are present, so the entity
spine comes almost for free. This is a matching problem, not an enrichment problem.

**What is missing from the 2018-onward files, and what it costs:**

- **Names.** Present in 2017-1, absent since. Irrelevant for NIT (RUES resolves it); a
  hard barrier for cédula — and that barrier pushes toward the correct model for
  natural persons.
- **Case number (`radicado`).** Present in 2017-1, absent since. Counsel will have to
  reconstruct the case file to submit a claim for anything post-2017. This is the
  hidden per-case cost and must be measured on real cases.
- **Case termination date.** The 2/3-year clock cannot be computed from the file.
  `Fecha Constitución` does allow identifying special-condition deposits.
- **Classification** between "unclaimed" and "special condition." Resolved for 2017-1
  (see below) — still open for every period since, where there is only one sheet and
  no column carries it either.

### Structural ambiguity

The file states who the **parties** are, not who the **money** belongs to. A deposit
may belong to the plaintiff (payment of a judgment), to the defendant (auction
surplus, excess, lifted attachment) or to a third party. No column distinguishes them.

Consequence for any future pitch: the honest framing is "your NIT appears in N active
deposits; we verify which ones are yours," never "this money is yours."

---

## 4. Glossary

| Term | Definition |
|---|---|
| **Claim** (`acreencia`) | Money already belonging to an identifiable beneficiary, with an amount and a legal basis. The conceptual unit of the engine; a judicial deposit is just one type |
| **Radar** | A detection pipeline over one public source. Implements the shared contract: discover, capture, normalize, report health |
| **Procedural role** | What the source asserts: plaintiff, defendant. A **fact** |
| **Economic role** | Who is creditor and who is debtor. An **inference**, with probability and rule |
| **File** (`archivo`) | The published object. A fact about the world. Carries the `period` |
| **Capture** | One processing run over a file. A fact about the system. Reprocessing = a new capture over the same file |
| **Period** | The publication semester. An attribute of the file, never of the claim — one period may have several files |
| **Observation** | One claim seen in one capture. Fine grain, append-only. The full lifecycle derives from this |
| **Despacho** | The court office. Identified by `cuenta judicial`, not by name |
| **Cuenta judicial** | The Banco Agrario account number belonging to a court office. Numeric and stable across publications |
| **Radicado** | The case number. Present only in the 2017-1 publication for this source — every file since omits it. Modeled as `claim.case_number`, nullable |
| **RUES** | Registro Único Empresarial y Social — Colombia's business registry, queried by `document_number`. Its `Categoria` field (persona natural / persona jurídica) is the authoritative source for `party.document_type` (D26), replacing the earlier DIAN check-digit guess |

---

## 5. Decision log

### Scope

- **D01.** Current focus is storage and enrichment. Commercial exploitation is
  deferred.
- **D02.** Everything is stored, but initial work targets **legal entities**, both as
  plaintiff and as defendant.
- **D03.** Only case types and court offices where it is near-certain the plaintiff is
  the creditor are considered. *(Weakest decision in this list — see §8.1.)*
- **D04.** The 2017–2025 history is not a prospect list — that money has prescribed —
  but **ground truth** for market sizing, measuring claim rates, and calibrating rules.

### Architecture

- **D05.** Layered architecture: per-radar adapters → shared core → serving layer.
  A radar implements only the contract; identity, inference and serving are shared.
- **D06.** The scaling axis is the **number of radars**, not data volume. At thirty
  radars this is still small data.
- **D07.** All normalization is a pure function of (raw file + code version). Fully
  reprocessable, always.
- **D08.** Deterministic IDs by hash of the natural key, never sequences.
- **D09.** No row is dropped silently. Rejects go to a table with the reason.
  Invariant: rows ok + rejected = rows read.
- **D10.** Per-source observability (freshness, volume delta, rejection rate) from the
  first radar, not when it starts hurting.

### Stack

- **D11.** Python throughout. Parquet on S3 partitioned by period; DuckDB as the
  analytical engine; **Postgres as the serving layer only**.
- **D12.** Transformations in version-controlled SQL, not dataframe chains. Python for
  what SQL does badly: reading Excel and calling APIs.
- **D13.** No orchestrator for now — but idempotent, watermarked steps from day one so
  one can be added later without a rewrite.
- **D14.** Rejected as oversized: Spark/EMR/Glue, Redshift/Snowflake, Airflow,
  streaming. Iceberg reconsidered at three or four parallel radars.
- **D15.** Versioning enabled on `raw/`, with a lifecycle rule to Glacier.
- **D16.** Libraries: `polars`+`calamine`, `duckdb`, `pandera`, `boto3`/`s3fs`,
  `httpx`+`tenacity`, `unidecode`+`rapidfuzz`, `pydantic`, `typer`, `pytest`, `uv`,
  `ruff`, `dbt-duckdb`.

### Data model

- **D17.** Facts and inferences live in separate tables, always.
- **D18.** Canonical fields as columns; radar-specific fields in `attributes` (JSONB).
  Operating rule: before adding a column to `core`, ask whether it would make sense
  for the insolvency radar.
- **D19.** Court office key = `cuenta judicial`, not the name. The name is an attribute
  with validity ranges.
- **D20.** Enrichment is append-only and dated. A prior lookup is never overwritten.
- **D21.** A party with no enrichment is a valid, permanent state — not a pending item.
- **D22.** Economic role stored as an inference with probability and `rule_id`, so the
  criterion can change and be recomputed without touching facts.

### Privacy

- **D23.** *(Amended by D26, 2026-08-17 — see below.)* Records keyed by cédula are
  enriched the same as any other match, in separate storage with restricted access.
  An indexed database of national IDs with amounts, names and cities is in practice a
  wealth profile of natural persons; the source being public does not exempt it from
  Law 1581 once enriched and commercially exploited. The restricted-access storage
  requirement is the part of this decision that survives D26 unchanged — only the
  "stored unenriched" framing was wrong.
- **D24.** If natural persons are ever served, the model is self-lookup — the person
  enters their own ID and sees only their own record — never outbound. Unaffected by
  D26: it governs the serving layer, not whether ingestion enriches.
- **D26.** (2026-08-17) The working assumption behind D23 — "only NITs appear in
  RUES, so enrichment is legal-entity-only" — is wrong. A natural person registered
  as a *comerciante* obtains a NIT derived from their cédula and has a RUES record
  like any company. Consequence: `document_type` is no longer inferred from the DIAN
  check-digit algorithm before deciding whether to query RUES (old rule 8). Every
  `document_number` is queried against RUES with no pre-filter, RUES's own
  `Categoria` field becomes the authoritative source for `document_type`, and every
  match is enriched — name, status, `attributes` — with no discrimination by
  category. This does not relax the privacy posture: D23's restricted-access storage
  requirement for cédula-keyed records still applies, now to a larger set of records
  than before (every enriched natural person, not zero of them), and D24's
  self-lookup-only serving constraint is untouched. Supersedes the "check-digit
  below 85% join rate" framing in the Phase 5 row of §7 and the `document_type`
  discussion in §6 and the Phase 3 findings in §7 — both predate this decision and
  describe the mechanism it replaces.

### Automation

- **D25.** GitHub Actions runs the pipeline commands, one workflow per phase
  (`.github/workflows/`: `profile-s3-prefix`, `normalize-s3-prefix`, `build-lineage`,
  `build-identity`, `build-lifecycle`, `enrich-parties`), triggered manually except
  `enrich-parties` (daily cron, `--limit 1000`) and `build-identity`, which chains
  via `workflow_run` right after (see D27). *(Originally also chained a second
  `check-document-types` workflow via `workflow_run` right after `enrich-parties` —
  retired by D26, folded into the single `enrich-parties` workflow.)* This is the
  "one can be added later" from D13, not a reversal of D14 — cron plus a
  `workflow_run` chain has no DAG engine, no backfill UI, and no cross-run state,
  unlike Airflow/Dagster. AWS auth is static access keys (`AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` repo secrets) for now, not OIDC role assumption —
  acceptable to revisit once the pipeline is more than one person's tool.
- **D27.** (2026-08-17) `build-identity` now runs automatically via `workflow_run`
  right after `enrich-parties` succeeds (gated the same way the old
  `check-document-types` chain was — `github.event.workflow_run.conclusion ==
  'success'`, never chaining onto a failed run). Since D26, `document_type` on
  `core/party` only ever gets updated by re-running `build-identity` after
  enrichment makes progress (`identity.apply_rues_classification`) — without this
  chain, newly-learned classifications would sit in `core/enrichment/` doing
  nothing until someone remembered to trigger `build-identity` by hand.
  `build-identity` is a full rebuild from staging + accumulated enrichment history,
  not a live RUES call, so chaining it daily costs no rate-limit budget, unlike
  chaining another RUES-calling workflow would.

---

## 6. Data model

Revised for Phase 1 against the real Phase 0 findings (§3) — the first draft of this
model was written before any real file had been examined and got the grain wrong.

**What Phase 0 forced to change, and why:**

- **`(period, deposit_no)` is not a reliable unique key.** Verified empirically: in
  2026-1 and 2022-2 the deposit-number column ties 1:1 with rows (distinct count ==
  row count). But 2017-1 repeats deposit numbers heavily — 117,690 rows / 102,929
  distinct in one sheet, 115,246 / 101,394 in the other. That file carries a
  `FECHA DE LA ACTUACIÓN QUE DIO FIN AL PROCESO` column no later file has: it's
  tracking one row per **case action**, not one row per deposit. The staging grain
  has to anchor on the physical row, which is always unique — not on a business key
  that only holds from 2018 onward.
- **`sheet` is not a property of `file`.** A single file can hold two meaningful
  sheets — 2017-1's two classification sheets, 2018-2's summary + detail sheets —
  reading only "the first sheet" silently returns the wrong data (see §3). `sheet`
  belongs on the row's identity, not the file's.
- **Column position isn't stable either** (`No. Depósito` is column 0 in 2026-1 but
  `Clasificación` is column 0 in 2022-2) — column-mapping in `normalize()` must be
  name- and `schema_version`-driven, never positional.

### Staging — one table per radar

`stg_jd_published_deposit` — grain: **`(capture_id, sheet, source_row)`**, the
physical row as published. Fields as received, with normalized versions alongside
(`plaintiff_id_raw` next to `plaintiff_id`), plus `deposit_no_raw` / `deposit_no` as
a *business-key candidate* — usable for identity/dedup from 2018 onward, but not a
hard uniqueness guarantee (2017-1 violates it). Also `sheet`, `capture_id`, and
`schema_version`.

`stg_jd_reject` — raw row plus reason. Also covers a whole-sheet failure (mirrors the
profiler's `<READ_ERROR>` pattern in `profiling.py`), so one unreadable sheet doesn't
silently drop everything in it.

### Core — shared canonical model

| Table | Grain and contents |
|---|---|
| `source` | Radar registry: name, cadence, contract |
| `file` | The published object: `source_id`, `period`, `uri`, `content_hash`, `detected_at`. No `sheet` — see above |
| `capture` | A run over a file: `code_version`, `schema_version`, `executed_at`, `rows_read`, `rows_ok`, `rows_rejected`, `status`. Counts summed across every sheet in the file |
| `claim` | A claim with stable identity: `type`, `amount_cop`, `origin_date`, `legal_basis`, `claim_route`, `court_id`, `case_number` (nullable — see below), `attributes` (JSONB) |
| `observation` | A claim in a capture. Append-only. Grain `(capture_id, sheet, source_row)` |
| `claim_party` | N:M bridge with `procedural_role` (fact as declared by the source). `attributes` (JSONB) can carry a source-declared party name when the source gives one (2017-1 only — see below) |
| `party` | `document_type` (binary: `legal_entity` \| `natural_person`), `document_number`, `document_type_confidence`, `document_type_rule_id`. Sourced from RUES's `Categoria` field (D26), not inferred — see below. The system's core asset |
| `enrichment` | `party_id`, `source`, `queried_at`, `result`, `name`, `active`, `attributes` (JSONB), `categoria`. Written for every RUES match, any `document_type` (D26) |
| `court` | Key derived from `cuenta_judicial`; specialty, city, judicial district |
| `court_name` | Name history with validity ranges |

**`claim.case_number`:** promoted to a real column rather than `attributes`. Only
2017-1 has it today (1 of 17 files), but it passes the project's own test for a core
column (D18: "would the insolvency radar want this?" — yes, every legal claim has a
case number).

**Source-declared party names go in `claim_party.attributes`, never through
`enrichment`.** The distinction is no longer about *who* the party is (rule 8 pre-D26
protected natural persons specifically); it's about provenance. `claim_party.attributes`
holds a name the public file already states — recording it isn't a lookup. `enrichment`
holds the result of an active RUES query, now taken for every party regardless of
`document_type` (D26). Cédula-keyed records in either table still sit in the
restricted-access storage tier D23 requires.

**Full lineage chain:** `observation → capture → file` yields the period, URI, sheet
and exact source row behind any value in the model.

**`party.document_type_confidence` + `document_type_rule_id` living directly on
`party`, not a separate marts inference table:** matching a raw ID to a document type
is identity resolution, which the layer table explicitly permits `core` to do (unlike
economic role or deadline, which are business conclusions rule 5/6 reserve for
marts). The `rule_id` column keeps rule 5's "inferences stored with a probability and
a rule_id" intact even though the table itself stays in `core`. As of D26, the values
populating these columns come from RUES's `Categoria` field on a match
(`rule_id = rues_categoria`, `confidence = 1.0`) — never from the DIAN check-digit
algorithm described in the Phase 3 findings (§7), which this decision retires as the
classification mechanism. A clean RUES miss (`rule_id = rues_not_found`) is
deliberately *not* treated as evidence of `natural_person`: only two candidate
numbers are ever tried per party (the stored form and, for NIT-candidate lengths, the
check-digit-stripped base — see `enrichment._candidate_document_numbers`), so a real
legal entity can miss for reasons unrelated to what it actually is, and there's no
measured error rate to calibrate a confident guess either way — the same
unfalsifiable-confidence problem D26 retired the check-digit heuristic for in the
first place. `document_type`/`confidence` stay null on a miss; the party remains
unclassified, the same permanent-valid-state D21 already gives a party with no
enrichment at all.

**`enrichment.categoria` stores whatever RUES's `Categoria` field actually says,
verbatim, on every match** — not filtered through the `document_type` mapping.
Classification is a substring match on the normalized value (`JURIDICA` /
`NATURAL`), not a closed whitelist of two exact strings, so real variants
("PERSONA JURIDICA EXTRANJERA", "PERSONA NATURAL COMERCIANTE", ...) still resolve
correctly without needing to be enumerated in advance. A `categoria` this doesn't
recognize as either shape (e.g. a RUES record that isn't a persona classification
at all) still gets fully enriched — `name`/`active`/`attributes` never depend on
whether `document_type` could be derived — and the raw value is never dropped,
only the derived binary classification stays honestly null
(`rule_id = rues_categoria_unrecognized`). Same principle for the company-detail
call: `attributes.detail` holds the entire detail response RUES returns, not a
cherry-picked sub-key — an earlier version of this code kept only `detail`'s
`registros` key and silently dropped the rest.

Note on `enrichment`: fields like registration status are RUES-specific and live in
`attributes`, not as columns. Only `name` and `active` are cross-source. Per D26,
`enrichment` rows are written for every RUES match — `document_type` no longer gates
which parties get queried or enriched.

### Marts — inferences and serving

| Table | Contents |
|---|---|
| `inferred_role` | Procedural role → economic role, with probability and `rule_id` |
| `deadline` | Per-claim deadline by type and legal basis, with confidence |
| `party_summary` | Per party: claim count, aggregate amount, court offices, radars where it appears |
| `prioritized_claim` | Serving view: fact + enrichment + role + deadline + score. The only thing materialized into Postgres |

**`deadline` and the unclaimed/special-condition classification:** this is never a
fact column, even though 2017-1's sheet split makes it look like one there. Where the
source states it explicitly (2017-1), that becomes a strong input feature to the
`rule_id`/confidence computation; every other period infers it purely from
`Fecha Constitución` (the 10-year special-condition threshold, per §2). The
classification itself always lives in the inference layer — never a fact column,
regardless of how strong the source signal is for a given period. Keeps rule 5/6
(facts and inferences never share a table) intact despite the input's provenance
differing by period.

### Model validity test

Mentally model radar 2 (Supersociedades insolvency creditor claims). If `claim`,
`party`, `claim_party` and `observation` absorb it with only a new `type`, a new
`source_id` and different `attributes` content, the model holds. If it needs new
columns on the canonical table or an `insolvency_claim` table, the model is still
judicial deposits wearing a generic name.

Holds for this revision: `case_number` generalizes (insolvency claims have case
numbers too), the `(capture_id, sheet, source_row)` grain is source-shape-agnostic,
and `sheet` sits at the row level so a single-sheet insolvency file costs nothing —
`sheet` is just always the same value for every row in that source.

---

## 7. Phase plan

| Phase | Objective | Exit criterion |
|---|---|---|
| **0. Profiling** | Discover schema drift 2017–2026 before designing the normalizer | Column × file matrix and list of unstable columns |
| **1. Canonical model** | Fix grain, keys, dimensions, layers, partitioning, lineage | One-page data dictionary |
| **2. Ingestion** | 20 heterogeneous spreadsheets → one table | Reconciliation: ok + rejected = read, on every file |
| **3. Identity** | Canonical court offices and parties | Done: 4,574 canonical courts, 1,249,652 canonical parties (82,472 legal-entity, 6.6% of parties but ~34% of plaintiff-side deposit value) |
| **4. Lifecycle** | From semiannual snapshots to a time series | Done: cross-period persistence is near zero (0.0–1.5% per half-year step, measured across all 15 consecutive period pairs) — the expected answer, not a bug (see findings below). 2,818,890 claims, 2,878,335 observations (1.02/claim), 4,471,404 claim_party links |
| **5. Enrichment** | `document_number` → RUES record with name, status, contact, for any `Categoria` (D26) | Measured join rate across all parties, not just NIT-shaped numbers |

Phases 0–4 depend only on data already in hand: they are the critical path.

**Phase 6 (Role and filter) removed from the active plan, 2026-08-07.** Was: decide
who owns the money (`inferred_role`, `deadline` marts), exit criterion precision
against 30 hand-labeled cases. Building the inference logic itself doesn't need
anything beyond `core` (Phases 3–4). What blocks the exit criterion is that
*validating* it has no automated path today: there's no radar for the case-lookup
portal (§3's "path 1", never built — only path 2, the semiannual file, exists), and
most of the history has no `radicado` to find a case by (open risk #2, itself
unmeasured — "measure on 5 real cases before committing to margins" hasn't
happened). So precision-checking 30 cases means 30 manual portal lookups, each
preceded by reconstructing which case a deposit even belongs to. Deferred rather
than built partially against an unmeasured validation cost — matches the project's
own stated preference: "0–4 done well beats 0–6 done partially." Revisit once
either the case-lookup-portal radar exists or the per-case reconstruction cost
(open risk #2) has actually been measured.

Phase 0 tooling: `claims-engine profile-s3-prefix` (`src/claims_engine/profiling.py`).
Detects the header row per sheet (never assumed), profiles every sheet in every file
(not just the first), and degrades a single unreadable sheet or file to a `<READ_ERROR>`
row instead of aborting the run. Output: `docs/phase0_schema_matrix.csv`, covering all
17 real publications (2017-1..2026-1). Reusable as-is for profiling future radars.

**Phase 3 findings.** The draft exit criterion ("court count in the hundreds, not
thousands") was a pre-data guess, not a real target — Colombia genuinely has
thousands of individual court offices (juzgados), so 4,574 is a plausible true count,
not a bug. `court_account` needed left-padding to 12 digits (11 vs 12-digit variants
of the same real account) and outright exclusion for 2020-1's corrupted values
(anomalous lengths from 1 to 15 digits, unique to that one file) — rows that fail this
end up with `court_id = NULL` rather than a bogus court, same as the 2017-1/2018-1/
2018-2 rows that never had a `court_account` column at all. `document_type`
(legal-entity vs natural-person) is source-declared in exactly 1 of 17 periods
(2023-2), and even there is inconsistent (9 raw label variants). At the time of this
finding, every other period was classified via Colombia's public DIAN mod-11 NIT
check-digit algorithm — a plain length cutoff wasn't viable, since real NIT and
cédula lengths overlap heavily (10 digits is the single largest length bucket in the
whole dataset, for both). **Superseded by D26 (2026-08-17):** the check-digit
heuristic assumed only legal entities hold NITs, which is false for comerciante
natural persons; `document_type` is now sourced from RUES's own `Categoria` field
in Phase 5 rather than guessed in Phase 3, per §6. Tooling: `claims-engine
build-identity` (`src/claims_engine/identity.py`), writing
`core/{party,court,court_name}/current.parquet` — a full rebuilt-in-place snapshot,
not period-partitioned like staging.

**Phase 4 findings.** The draft exit criterion ("what % of deposits published in
2019 still appeared in 2021") assumed a rich, growing time series. The measured
answer is that cross-period persistence is small — 0.0–1.5% of a period's distinct
claims reappear in the next period, checked with two independent keys
(`court_account`+`deposit_no`, and separately `court_account`+`amount_cop`+
`origin_date`) to rule out a key artifact. This matches §2's own framing: the
semiannual file is "the eviction notice — the last 20 business days of the asset's
life," not a persistent watchlist, so a deposit is expected to appear once and then
resolve (claimed or swept), not recur. The low number is the correct finding, not a
sign the model is wrong. Within-period duplicate `(court_account, deposit_no)` rows
(heaviest in 2019-1: 147,464 rows, 134,788 distinct keys) were checked directly and
are literal re-publication of the same deposit (identical amount/date/parties), not
different deposits colliding on a number — they collapse into multiple
`observation`s of one `claim`. A much smaller residual of *genuine* key collisions
(same key, actually different content) exists — mostly single digits per period, but
3,235 in 2024-1 — resolved by taking the most recent observation's values, not by
reconciliation. `court_account` is missing entirely in 2017-1/2018-1/2018-2;
2018-1/2018-2 fall back to `deposit_no` alone (verified reliable there), but 2017-1 is
excluded from claim identity altogether — its rows are case actions, not deposits
(established in Phase 1), so no reliable claim key exists for it at all. Tooling:
`claims-engine build-lifecycle` (`src/claims_engine/lifecycle.py`), writing
`core/{claim,observation,claim_party}/current.parquet`.

---

## 8. Open risks and unresolved questions

1. **Precision of the "plaintiff = creditor" filter.** The court office gives specialty
   and hierarchy, not case type. A civil municipal court hears both enforcement and
   declaratory cases. The rule does not reach the assumed certainty and cannot be
   measured from the file alone.
   *Proposed mitigation:* behavioral signal — an ID appearing as plaintiff thousands of
   times is by construction a mass enforcement creditor — plus manual validation of 30
   cases against the case-lookup portal.
2. **Real per-case cost.** Reconstructing the case file without a `radicado`. Measure
   on 5 real cases before committing to margins.
3. **`Valor` parsing.** The most expensive bug in this domain. Handled by counting
   digits after the last separator.
4. **Unclaimed vs special-condition classification.** Resolved for 2017-1: it's not a
   hidden column, it's two separate sheets (`D J EN CONDICION ESPECIAL` vs
   `D J NO RECLAMADOS`). Every file from 2018 onward has only one sheet and no column
   carries the distinction either — for those periods the classification is genuinely
   not present in the source, not just hidden. **Closed for the data ingested so
   far (2026-08-20):** every period captured by this radar to date is unclaimed-type
   only — special-condition deposits aren't part of the current dataset. This is what
   makes a uniform per-period 20-business-day claim window (`ClaimWindow` model,
   `web/judicial_deposits/models.py`) legally sound to apply corpus-wide without
   per-row classification. Revisit if a future capture ever ingests a special-condition
   sheet (as 2017-1 had) — the window logic would need to exclude those rows or gain a
   second, constitution-date-based rule.
5. **Currency of the 2026-1 publication.** If live, a 20-business-day clock is running.
   Determines whether the history is a museum or includes still-claimable money.
6. **Maintenance as the real scaling limit.** Each radar is a permanent liability:
   sources that change format without notice, portals that go down. At twenty radars
   something will almost always be broken. Hence D10 and isolation between radars.
