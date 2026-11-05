from datetime import timedelta

from django.db import migrations
from django.utils import timezone

CATEGORIES = [
    ("Depósitos judiciales", "depositos-judiciales", "Qué son, cuánto tiempo hay para reclamarlos y cómo hacerlo."),
    ("Liquidaciones societarias", "liquidaciones-societarias", "Acreencias y derechos económicos en la liquidación de empresas."),
]

BODY = (
    "<p><strong>Contenido de ejemplo.</strong> Este artículo existe solo para "
    "comprobar cómo se muestra el listado, los filtros por categoría y la página "
    "individual. Bórrelo o despublíquelo desde el administrador.</p>"
    "<h2>Subtítulo de ejemplo</h2>"
    "<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nulla sodales, est "
    "nec aliquet sagittis, ex neque pellentesque libero.</p>"
    "<ul><li>Primer punto de ejemplo</li><li>Segundo punto de ejemplo</li></ul>"
)

# (slug, title, excerpt, category slugs, days ago)
ARTICLES = [
    (
        "placeholder-depositos-judiciales",
        "[Placeholder] Qué es un depósito judicial y por qué puede estar a su nombre",
        "Un depósito judicial es dinero consignado dentro de un proceso que espera ser reclamado por su beneficiario.",
        ["depositos-judiciales"],
        3,
    ),
    (
        "placeholder-liquidaciones-societarias",
        "[Placeholder] Qué pasa con las acreencias cuando una sociedad se liquida",
        "Cuando una sociedad entra en liquidación, sus acreedores deben hacer valer sus derechos dentro de un procedimiento.",
        ["liquidaciones-societarias"],
        2,
    ),
    (
        "placeholder-ambas-categorias",
        "[Placeholder] Depósitos judiciales y liquidaciones: dónde pueden cruzarse",
        "Un mismo derecho económico puede aparecer en un depósito judicial y en el proceso de liquidación de una empresa.",
        ["depositos-judiciales", "liquidaciones-societarias"],
        1,
    ),
]


def create(apps, schema_editor):
    Category = apps.get_model("cms", "Category")
    Article = apps.get_model("cms", "Article")
    categories = {}
    for name, slug, description in CATEGORIES:
        categories[slug], _ = Category.objects.get_or_create(
            slug=slug, defaults={"name": name, "description": description}
        )
    now = timezone.now()
    for slug, title, excerpt, category_slugs, days_ago in ARTICLES:
        article, created = Article.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "excerpt": excerpt,
                "body": BODY,
                "status": "published",
                "published_at": now - timedelta(days=days_ago),
            },
        )
        if created:
            article.categories.set([categories[s] for s in category_slugs])


def remove(apps, schema_editor):
    # The categories are kept: they are real structure, only the samples go.
    apps.get_model("cms", "Article").objects.filter(slug__startswith="placeholder-").delete()


class Migration(migrations.Migration):
    dependencies = [("cms", "0002_seed_draft_pages")]
    operations = [migrations.RunPython(create, remove)]
