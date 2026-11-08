import importlib

from django.db import migrations

# 0003's sample articles went live with the deploy and were indexable (in the
# sitemap, linked from /guias/). Back to draft — not deleted — and only while
# the body is still 0003's untouched sample, so an article an editor has since
# turned into real content is left alone.
SAMPLE_BODY = importlib.import_module("cms.migrations.0003_placeholder_articles").BODY


def unpublish(apps, schema_editor):
    apps.get_model("cms", "Article").objects.filter(
        slug__startswith="placeholder-", body=SAMPLE_BODY
    ).update(status="draft")


def republish(apps, schema_editor):
    apps.get_model("cms", "Article").objects.filter(
        slug__startswith="placeholder-", body=SAMPLE_BODY
    ).update(status="published")


class Migration(migrations.Migration):
    dependencies = [("cms", "0003_placeholder_articles")]
    operations = [migrations.RunPython(unpublish, republish)]
