from django.core.management.base import BaseCommand

from judicial_deposits import core_cache, corpus_stats


class Command(BaseCommand):
    help = (
        "Downloads the core/ tables the document-number search needs from S3 to a local "
        "Parquet cache. Run on a schedule (e.g. after build-lifecycle/"
        "build-identity/enrich-parties), not per request."
    )

    def handle(self, *args, **options):
        self.stdout.write(f"syncing to {core_cache.cache_dir()} ...")
        core_cache.sync()
        # The landing's statistics: computed here, never per request.
        self.stdout.write(f"corpus statistics: {corpus_stats.write_slices()} groups")
        self.stdout.write(self.style.SUCCESS("done"))
