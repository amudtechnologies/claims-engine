from django.db import migrations

PLACEHOLDER = (
    "<p><strong>BORRADOR — contenido pendiente.</strong> Esta página se creó vacía "
    "para ser redactada desde el administrador y publicada cuando esté lista. "
    "{extra}</p>"
)

PAGES = [
    ("Nosotros", "nosotros", 10, "Describa quién es Amud Technologies, qué hace y qué no hace."),
    (
        "Política de tratamiento de datos personales",
        "politica-de-tratamiento-de-datos",
        20,
        "Debe ser revisada por asesoría jurídica en Colombia (Ley 1581 de 2012) antes de publicarse.",
    ),
    (
        "Términos y condiciones",
        "terminos-y-condiciones",
        30,
        "Debe ser revisada por asesoría jurídica antes de publicarse.",
    ),
]


def seed(apps, schema_editor):
    Page = apps.get_model("cms", "Page")
    for title, slug, order, extra in PAGES:
        # Drafts only: nothing here is public until someone publishes it.
        Page.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "body": PLACEHOLDER.format(extra=extra),
                "status": "draft",
                "show_in_footer": True,
                "footer_order": order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("cms", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
