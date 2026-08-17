import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import boto3
import duckdb
import httpx
import polars as pl
import typer

from claims_engine import (
    capture,
    contracts,
    discover,
    enrichment,
    health,
    identity,
    lifecycle,
    lineage,
    load,
    normalize,
    profiling,
)

app = typer.Typer()


@app.callback()
def main() -> None:
    """Claims engine CLI. Radar operations are exposed one subcommand at a
    time — kept as a group (even with a single command today) so the
    subcommand name never silently changes as commands are added."""


@app.command()
def profile_s3_prefix(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    prefix: Annotated[str, typer.Argument(help="S3 prefix to list and profile every file under.")],
    out: Annotated[
        Path | None,
        typer.Option(help="Write the combined profile to this CSV instead of printing it."),
    ] = None,
) -> None:
    """List every object under an S3 prefix and profile each one, one file at
    a time. A file that fails entirely (e.g. can't be downloaded) is recorded
    as a <READ_ERROR> row rather than aborting the rest of the prefix."""
    keys = discover.list_keys(bucket, prefix)
    if not keys:
        typer.echo(f"No objects found under s3://{bucket}/{prefix}", err=True)
        raise typer.Exit(code=1)

    all_profiles = []
    for i, key in enumerate(keys, start=1):
        typer.echo(f"[{i}/{len(keys)}] {key}", err=True)
        try:
            all_profiles.extend(profiling.profile_s3_key(bucket, key))
        except Exception as e:
            typer.echo(f"  failed: {type(e).__name__}: {e}", err=True)
            all_profiles.append(profiling.read_error_profile(key, "<unknown>", e))

    frame = profiling.profiles_to_frame(all_profiles)
    if out is None:
        typer.echo(frame)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(out)
    typer.echo(f"Profiled {len(keys)} files -> {out}")


@app.command()
def normalize_s3_prefix(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    prefix: Annotated[
        str, typer.Argument(help="S3 prefix to list and normalize every file under.")
    ],
    staging_prefix: Annotated[
        str, typer.Option(help="S3 prefix to write staging Parquet under.")
    ] = "staging/jd_published_deposit",
    reject_prefix: Annotated[
        str, typer.Option(help="S3 prefix to write reject Parquet under.")
    ] = "staging/jd_reject",
) -> None:
    """List every object under an S3 prefix, normalize each one (Phase 2), and
    write stg_jd_published_deposit / stg_jd_reject as Parquet on S3, Hive-
    partitioned by period. Exits non-zero if rows_ok + rows_rejected != rows_read
    for any file — that invariant is the phase's whole exit criterion."""
    keys = discover.list_keys(bucket, prefix)
    if not keys:
        typer.echo(f"No objects found under s3://{bucket}/{prefix}", err=True)
        raise typer.Exit(code=1)

    client = boto3.client("s3")
    total_read = total_ok = total_rejected = 0
    mismatches: list[str] = []

    for i, key in enumerate(keys, start=1):
        typer.echo(f"[{i}/{len(keys)}] {key}", err=True)
        with capture.fetch_to_local(bucket, key) as path:
            result = normalize.transform_file(path, key)
        total_read += result.rows_read
        total_ok += result.rows_ok
        total_rejected += result.rows_rejected

        error = health.reconciliation_error(result)
        if error:
            mismatches.append(key)
            typer.echo(f"  RECONCILIATION MISMATCH: {error}", err=True)

        period = normalize.period_from_key(key)
        capture_id = normalize.capture_id_for_key(key)
        ok_key = load.staging_key(staging_prefix, period, capture_id)
        reject_key = load.staging_key(reject_prefix, period, capture_id)
        load.write_frame_to_s3(client, result.ok_frame(), bucket, ok_key)
        load.write_frame_to_s3(client, result.reject_frame(), bucket, reject_key)

    typer.echo(f"TOTAL: read={total_read} ok={total_ok} rejected={total_rejected}")
    if mismatches:
        typer.echo(f"Reconciliation failed for {len(mismatches)} file(s): {mismatches}", err=True)
        raise typer.Exit(code=1)


@app.command()
def build_lineage(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    raw_prefix: Annotated[
        str, typer.Option(help="S3 prefix to list raw files under.")
    ] = "raw/judicial-branch/expiring-deposits/",
    staging_prefix: Annotated[
        str, typer.Option(help="S3 prefix staging Parquet was written under.")
    ] = "staging/jd_published_deposit",
    reject_prefix: Annotated[
        str, typer.Option(help="S3 prefix reject Parquet was written under.")
    ] = "staging/jd_reject",
) -> None:
    """Builds core/{file,capture} -- one row per raw object, full rebuilt-
    in-place snapshot (D07). Covers historical files and future ones with the
    same code path, no separate backfill mode. Depends only on the raw
    listing plus staging/reject Parquet already written by
    normalize-s3-prefix -- run this after that, before build-identity/
    build-lifecycle (those two don't read this table, so order between them
    doesn't matter)."""
    keys_with_lm = discover.list_keys_with_last_modified(bucket, raw_prefix)
    if not keys_with_lm:
        typer.echo(f"No objects found under s3://{bucket}/{raw_prefix}", err=True)
        raise typer.Exit(code=1)
    keys = [key for key, _ in keys_with_lm]

    dep_keys = discover.list_keys(bucket, staging_prefix)
    rej_keys = discover.list_keys(bucket, reject_prefix)
    if not dep_keys or not rej_keys:
        typer.echo(
            f"No staging/reject objects found under s3://{bucket}/"
            f"{{{staging_prefix},{reject_prefix}}} -- run normalize-s3-prefix first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Not a stand-in for "we don't know the historical version" specifically --
    # build-lineage always reconstructs captures from already-written staging
    # (never a live in-process FileNormalizeResult), so it can never know the
    # real code_version that produced a given file's staging output, today or
    # in the future. lineage.BACKFILL_CODE_VERSION says that honestly instead
    # of stamping the currently-installed package version on rows it didn't
    # actually process.
    code_version = lineage.BACKFILL_CODE_VERSION
    client = boto3.client("s3")

    typer.echo(f"[1/{len(keys)}] building files (fetching raw for content_hash)...", err=True)
    files = contracts.FileSchema.validate(lineage.build_files(bucket, keys_with_lm))

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, key in enumerate(dep_keys):
            client.download_file(bucket, key, f"{tmpdir}/dep_{i}.parquet")
        for i, key in enumerate(rej_keys):
            client.download_file(bucket, key, f"{tmpdir}/rej_{i}.parquet")

        con = duckdb.connect()
        con.execute(f"CREATE VIEW dep AS SELECT * FROM read_parquet('{tmpdir}/dep_*.parquet')")
        con.execute(f"CREATE VIEW rej AS SELECT * FROM read_parquet('{tmpdir}/rej_*.parquet')")

        typer.echo("Building captures...", err=True)
        captures = contracts.CaptureSchema.validate(
            lineage.build_captures(con, keys, code_version, contracts.SCHEMA_VERSION)
        )

    for label, df in (("file", files), ("capture", captures)):
        load.write_frame_to_s3(client, df, bucket, load.core_key(label))

    status_counts = captures.group_by("status").len().sort("status")
    typer.echo(f"files: {files.height}")
    typer.echo(f"captures: {captures.height}")
    typer.echo(f"status breakdown: {status_counts.rows()}")


@app.command()
def build_identity(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    staging_prefix: Annotated[
        str, typer.Option(help="S3 prefix staging Parquet was written under.")
    ] = "staging/jd_published_deposit",
) -> None:
    """Phase 3: build canonical party/court/court_name tables from every
    staging file under staging_prefix, and write them to core/ on S3. Core
    is a single rebuilt-in-full snapshot per table (D07), not partitioned
    by period like staging.

    Per D26, document_type isn't computed from staging anymore -- it comes
    from RUES (Phase 5). Since this command rebuilds core/party from
    scratch every run, it backfills document_type/confidence/rule_id from
    whatever core/enrichment/ history already exists before writing, so a
    party enrich-parties already classified doesn't lose that classification
    just because build-identity ran again."""
    keys = discover.list_keys(bucket, staging_prefix)
    if not keys:
        typer.echo(f"No staging objects found under s3://{bucket}/{staging_prefix}", err=True)
        raise typer.Exit(code=1)

    client = boto3.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Staging and enrichment downloads live in separate subdirectories,
        # each with its own dedicated glob -- `dep`'s view definition
        # re-evaluates its read_parquet(glob) on every query, not just at
        # CREATE VIEW time, so if enrichment files ever landed in the same
        # directory as staging files, a later query against `dep` (e.g.
        # build_courts_and_names, which runs after the enrichment fetch
        # below) would silently pick them up too and blow up looking for
        # staging columns in an enrichment file.
        staging_dir = f"{tmpdir}/staging"
        Path(staging_dir).mkdir()
        for i, key in enumerate(keys, start=1):
            typer.echo(f"[{i}/{len(keys)}] fetching {key}", err=True)
            client.download_file(bucket, key, f"{staging_dir}/{key.replace('/', '_')}")

        con = duckdb.connect()
        con.execute(f"CREATE VIEW dep AS SELECT * FROM read_parquet('{staging_dir}/*.parquet')")

        typer.echo("Building parties...", err=True)
        parties = identity.build_parties(con)

        enrichment_keys = discover.list_keys(bucket, "core/enrichment/")
        if enrichment_keys:
            typer.echo(
                f"fetching {len(enrichment_keys)} existing enrichment batch(es) "
                "for document_type backfill...",
                err=True,
            )
            enrichment_dir = f"{tmpdir}/enrichment"
            Path(enrichment_dir).mkdir()
            for i, key in enumerate(enrichment_keys):
                client.download_file(bucket, key, f"{enrichment_dir}/{i}.parquet")
            # union_by_name: batches written before document_type existed on
            # `enrichment` (pre-D26) lack the column entirely and correctly
            # contribute no classification signal once unioned in as NULL.
            con.execute(
                "CREATE VIEW enrichment AS SELECT * FROM read_parquet("
                f"'{enrichment_dir}/*.parquet', union_by_name=true)"
            )
            classification = identity.latest_rues_classification(con)
            parties = identity.apply_rues_classification(parties, classification)

        parties = contracts.PartySchema.validate(parties)

        typer.echo("Building courts...", err=True)
        courts, court_names = identity.build_courts_and_names(con)
        courts = contracts.CourtSchema.validate(courts)
        court_names = contracts.CourtNameSchema.validate(court_names)

        null_court_rows = con.execute(
            "SELECT count(*) FROM dep WHERE court_account IS NULL"
        ).fetchone()[0]

        for label, df in (("party", parties), ("court", courts), ("court_name", court_names)):
            load.write_frame_to_s3(client, df, bucket, load.core_key(label))

    legal_count = parties.filter(pl.col("document_type") == "legal_entity").height
    natural_count = parties.filter(pl.col("document_type") == "natural_person").height
    unclassified = parties.height - legal_count - natural_count
    typer.echo(
        f"parties: {parties.height} total "
        f"({legal_count} legal_entity, {natural_count} natural_person, "
        f"{unclassified} not yet classified)"
    )
    typer.echo(f"courts: {courts.height}")
    typer.echo(f"staging rows with no usable court_account: {null_court_rows}")


@app.command()
def build_lifecycle(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    staging_prefix: Annotated[
        str, typer.Option(help="S3 prefix staging Parquet was written under.")
    ] = "staging/jd_published_deposit",
) -> None:
    """Phase 4: build claim/observation/claim_party from every staging file
    under staging_prefix, and write them to core/ on S3. 2017-1 is excluded
    entirely (no reliable claim key — see docs/project-context.md §7)."""
    keys = discover.list_keys(bucket, staging_prefix)
    if not keys:
        typer.echo(f"No staging objects found under s3://{bucket}/{staging_prefix}", err=True)
        raise typer.Exit(code=1)

    client = boto3.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, key in enumerate(keys, start=1):
            typer.echo(f"[{i}/{len(keys)}] fetching {key}", err=True)
            client.download_file(bucket, key, f"{tmpdir}/{key.replace('/', '_')}")

        con = duckdb.connect()
        con.execute(f"CREATE VIEW dep AS SELECT * FROM read_parquet('{tmpdir}/*.parquet')")

        typer.echo("Building claims...", err=True)
        claims = contracts.ClaimSchema.validate(lifecycle.build_claims(con))
        typer.echo("Building observations...", err=True)
        observations = contracts.ObservationSchema.validate(lifecycle.build_observations(con))
        typer.echo("Building claim_party...", err=True)
        claim_parties = contracts.ClaimPartySchema.validate(lifecycle.build_claim_parties(con))
        typer.echo("Measuring cross-period persistence...", err=True)
        persistence = lifecycle.measure_persistence(con)

        for label, df in (
            ("claim", claims),
            ("observation", observations),
            ("claim_party", claim_parties),
        ):
            load.write_frame_to_s3(client, df, bucket, load.core_key(label))

    avg_observations = observations.height / claims.height if claims.height else 0
    typer.echo(f"claims: {claims.height}")
    typer.echo(f"observations: {observations.height} ({avg_observations:.2f} per claim)")
    typer.echo(f"claim_party links: {claim_parties.height}")
    typer.echo("cross-period persistence (the phase's exit criterion):")
    for row in persistence.iter_rows(named=True):
        typer.echo(
            f"  {row['prev_period']} -> {row['period']}: "
            f"{row['overlap']}/{row['prev_count']} ({row['overlap_pct']}%)"
        )


@app.command()
def enrich_parties(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    limit: Annotated[
        int, typer.Option(help="Max not-yet-enriched parties to query this run.")
    ] = 1000,
    delay_seconds: Annotated[
        float, typer.Option(help="Pause between RUES requests, in seconds.")
    ] = 3.0,
) -> None:
    """Phase 5: query RUES for up to `limit` not-yet-enriched parties from
    core/party -- every document_type, no discrimination (D26) -- and write
    the results as a new dated batch under core/enrichment/ on S3.
    Deliberately small and rate-limited by default — rerun to make more
    progress rather than enriching everything in one sitting. This is also
    now the only source of party.document_type; run build-identity again
    afterward to fold newly-learned classifications back onto core/party."""
    client = boto3.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        typer.echo("fetching core/party...", err=True)
        client.download_file(bucket, load.core_key("party"), f"{tmpdir}/party.parquet")

        con = duckdb.connect()
        con.execute(f"CREATE VIEW party AS SELECT * FROM read_parquet('{tmpdir}/party.parquet')")

        enrichment_keys = discover.list_keys(bucket, "core/enrichment/")
        if enrichment_keys:
            typer.echo(
                f"fetching {len(enrichment_keys)} existing enrichment batch(es)...", err=True
            )
            for i, key in enumerate(enrichment_keys):
                client.download_file(bucket, key, f"{tmpdir}/enrichment_{i}.parquet")
            glob = f"{tmpdir}/enrichment_*.parquet"
            # union_by_name: batches written before the `status` (or, since
            # D26, `document_type`) columns existed lack them entirely -- they
            # read back NULL, which parties_to_enrich/build_identity treat
            # correctly (retryable / no classification signal respectively).
            # If *no* existing batch has `status` yet, union_by_name has
            # nothing to pull it from and the view genuinely lacks the column
            # -- add it explicitly rather than let every batch stay
            # permanently error-only.
            con.execute(
                "CREATE VIEW enrichment_raw AS "
                f"SELECT * FROM read_parquet('{glob}', union_by_name=true)"
            )
            existing_columns = {row[0] for row in con.execute("DESCRIBE enrichment_raw").fetchall()}
            select = "*" if "status" in existing_columns else "*, NULL::VARCHAR AS status"
            con.execute(f"CREATE VIEW enrichment AS SELECT {select} FROM enrichment_raw")
        else:
            con.execute(
                """
                CREATE TABLE enrichment (
                    party_id VARCHAR, source VARCHAR, queried_at TIMESTAMP,
                    result VARCHAR, name VARCHAR, active BOOLEAN, attributes VARCHAR,
                    status VARCHAR, categoria VARCHAR, document_type VARCHAR,
                    document_type_confidence DOUBLE, document_type_rule_id VARCHAR
                )
                """
            )

        typer.echo(f"Querying RUES (limit={limit}, delay={delay_seconds}s)...", err=True)

        def _progress(done: int, total: int) -> None:
            typer.echo(f"  {done}/{total} queried", err=True)

        with httpx.Client(timeout=30.0) as http_client:
            results = enrichment.enrich_parties(
                con, http_client, limit, delay_seconds, on_progress=_progress
            )

        if results.height == 0:
            typer.echo("Nothing to enrich — every party already has a RUES attempt.")
            raise typer.Exit(code=0)

        results = contracts.EnrichmentSchema.validate(results)
        batch_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        key = load.enrichment_key(enrichment.SOURCE, batch_id)
        load.write_frame_to_s3(client, results, bucket, key)

    found = results.filter(pl.col("name").is_not_null()).height
    not_found_or_error = results.height - found
    legal_count = results.filter(pl.col("document_type") == "legal_entity").height
    natural_count = results.filter(pl.col("document_type") == "natural_person").height
    typer.echo(
        f"queried: {results.height}  found: {found}  not_found_or_error: {not_found_or_error}  "
        f"(classified: {legal_count} legal_entity, {natural_count} natural_person)"
    )
    typer.echo(f"written to s3://{bucket}/{key}")


