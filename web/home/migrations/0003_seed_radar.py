from django.db import migrations


def seed(apps, schema_editor):
    Radar = apps.get_model("home", "Radar")
    Radar.objects.get_or_create(
        slug="depositos-judiciales",
        defaults={
            "name": "Depósitos judiciales",
            "problem": (
                "Dinero constituido en procesos judiciales que prescribe a favor de la "
                "Nación si no se reclama dentro del plazo legal."
            ),
            "identifies": (
                "Depósitos publicados por la Rama Judicial como no reclamados, con su "
                "despacho, valor y número de identificación de las partes."
            ),
            "audience": "Personas naturales, empresas y firmas que gestionan recuperaciones.",
            "status": "active",
            "cta_label": "Conocer el radar",
            "cta_url": "/depositos-judiciales/",
            "display_order": 10,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("home", "0002_radar")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
