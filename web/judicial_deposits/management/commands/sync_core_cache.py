from django.core.management.base import BaseCommand

from judicial_deposits import core_cache, corpus_stats


class Command(BaseCommand):
    help = (
        "Downloads the core/ tables the document-number search needs from S3 to a local "
        "Parquet cache. Run on a schedule (e.g. after build-lifecycle/"
        "build-identity/enrich-parties), not per request."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--corpus-stats",
            action="store_true",
            help=(
                "Also recompute the landing's statistics (corpus_stats.json). "
                "Only the startup sync passes it: the aggregation peaks at ~440 MB, "
                "and running it from the hourly background sync next to the web "
                "workers ran the 1 GB production instance out of memory."
            ),
        )

    def handle(self, *args, **options):
        self.stdout.write(f"syncing to {core_cache.cache_dir()} ...")
        self.stdout.write(f"downloaded {core_cache.sync()} changed objects")
        if options["corpus_stats"]:
            # The landing's statistics: computed here, never per request.
            self.stdout.write(f"corpus statistics: {corpus_stats.write_slices()} groups")
        self.stdout.write(self.style.SUCCESS("done"))
