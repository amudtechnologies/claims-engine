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
    document_type_check,
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
    by period like staging."""
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

        typer.echo("Building parties...", err=True)
        parties = contracts.PartySchema.validate(identity.build_parties(con))
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
    typer.echo(
        f"parties: {parties.height} total "
        f"({legal_count} legal_entity, {parties.height - legal_count} natural_person)"
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
        int, typer.Option(help="Max not-yet-enriched legal_entity parties to query this run.")
    ] = 50,
    delay_seconds: Annotated[
        float, typer.Option(help="Pause between RUES requests, in seconds.")
    ] = 3.0,
) -> None:
    """Phase 5: query RUES for up to `limit` not-yet-enriched legal_entity
    parties from core/party, and write the results as a new dated batch
    under core/enrichment/ on S3. Deliberately small and rate-limited by
    default — rerun to make more progress rather than enriching everything
    in one sitting."""
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
            # union_by_name: batches written before the `status` column existed
            # lack it entirely -- they read back with status NULL, which
            # parties_to_enrich treats as retryable (those batches predate the
            # column and were, in fact, all infra errors, never a real answer).
            # If *no* existing batch has `status` yet (true the first time this
            # runs after the column was introduced), union_by_name has nothing
            # to pull it from and the view genuinely lacks the column -- add it
            # explicitly rather than let every batch stay permanently error-only.
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
                    status VARCHAR
                )
                """
            )

        typer.echo(f"Querying RUES (limit={limit}, delay={delay_seconds}s)...", err=True)
        with httpx.Client(timeout=30.0) as http_client:
            results = enrichment.enrich_parties(con, http_client, limit, delay_seconds)

        if results.height == 0:
            typer.echo("Nothing to enrich — every legal_entity party already has a RUES attempt.")
            raise typer.Exit(code=0)

        results = contracts.EnrichmentSchema.validate(results)
        batch_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        key = load.enrichment_key(enrichment.SOURCE, batch_id)
        load.write_frame_to_s3(client, results, bucket, key)

    found = results.filter(pl.col("name").is_not_null()).height
    not_found = results.height - found
    typer.echo(f"queried: {results.height}  found: {found}  not_found_or_error: {not_found}")
    typer.echo(f"written to s3://{bucket}/{key}")


@app.command()
def check_document_types(
    bucket: Annotated[str, typer.Argument(help="S3 bucket, e.g. amud-technologies.")],
    limit: Annotated[
        int,
        typer.Option(
            help="Max unchecked exhausted-signal natural_person parties to query this run."
        ),
    ] = 50,
    delay_seconds: Annotated[
        float, typer.Option(help="Pause between RUES requests, in seconds.")
    ] = 3.0,
) -> None:
    """Query RUES for up to `limit` natural_person parties whose
    document_type has no internal evidence either way (see
    document_type_check.py), and write the results as a new dated batch
    under core/document_type_check/ on S3. A 'found' result is definitive
    evidence the party is actually a legal_entity — party.document_type in
    core/party is never rewritten by this command; instead a matching
    core/enrichment/ row is written too (same RUES response, no second
    query), so enrich-parties never needs a separate run for these."""
    client = boto3.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        typer.echo("fetching core/party...", err=True)
        client.download_file(bucket, load.core_key("party"), f"{tmpdir}/party.parquet")

        con = duckdb.connect()
        con.execute(f"CREATE VIEW party AS SELECT * FROM read_parquet('{tmpdir}/party.parquet')")

        check_keys = discover.list_keys(bucket, "core/document_type_check/")
        if check_keys:
            typer.echo(f"fetching {len(check_keys)} existing check batch(es)...", err=True)
            for i, key in enumerate(check_keys):
                client.download_file(bucket, key, f"{tmpdir}/check_{i}.parquet")
            con.execute(
                "CREATE VIEW document_type_check AS "
                f"SELECT * FROM read_parquet('{tmpdir}/check_*.parquet')"
            )
        else:
            con.execute(
                """
                CREATE TABLE document_type_check (
                    party_id VARCHAR, source VARCHAR, queried_at TIMESTAMP,
                    result VARCHAR, name VARCHAR, status VARCHAR
                )
                """
            )

        typer.echo(f"Querying RUES (limit={limit}, delay={delay_seconds}s)...", err=True)
        with httpx.Client(timeout=30.0) as http_client:
            results, enrichment_results = document_type_check.check_document_types(
                con, http_client, limit, delay_seconds
            )

        if results.height == 0:
            typer.echo(
                "Nothing to check — every exhausted-signal natural_person party "
                "already has an attempt."
            )
            raise typer.Exit(code=0)

        results = contracts.DocumentTypeCheckSchema.validate(results)
        batch_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        check_key = load.document_type_check_key(document_type_check.SOURCE, batch_id)
        load.write_frame_to_s3(client, results, bucket, check_key)

        enrichment_batch_key = None
        if enrichment_results.height > 0:
            enrichment_results = contracts.EnrichmentSchema.validate(enrichment_results)
            enrichment_batch_key = load.enrichment_key(document_type_check.SOURCE, batch_id)
            load.write_frame_to_s3(client, enrichment_results, bucket, enrichment_batch_key)

    found = results.filter(pl.col("status") == "found").height
    typer.echo(f"queried: {results.height}  confirmed_legal_entity: {found}")
    typer.echo(f"written to s3://{bucket}/{check_key}")
    if enrichment_batch_key:
        typer.echo(f"enrichment written to s3://{bucket}/{enrichment_batch_key}")
