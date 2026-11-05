from django.db import migrations

OLD = "Personas naturales, empresas y firmas que gestionan recuperaciones."
NEW = (
    "Empresas, firmas y entidades que gestionan recuperaciones; "
    "también personas naturales."
)


def update(apps, schema_editor):
    Radar = apps.get_model("home", "Radar")
    # Only if still the seeded text: never overwrite an admin's edit.
    Radar.objects.filter(slug="depositos-judiciales", audience=OLD).update(audience=NEW)


class Migration(migrations.Migration):
    dependencies = [("home", "0003_seed_radar")]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
