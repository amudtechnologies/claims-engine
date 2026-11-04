from django.db import models


class CompanyProfile(models.Model):
    """Amud Technologies' own registration and contact details — the system's
    transactional data about itself, not pipeline output.
    """

    name = models.CharField(max_length=255)
    nit = models.CharField(max_length=32, verbose_name="NIT")
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    address = models.CharField(max_length=255)
    description = models.TextField()

    class Meta:
        verbose_name = "company profile"
        verbose_name_plural = "company profile"

    def __str__(self) -> str:
        return self.name


class Radar(models.Model):
    """One card in the radar family (home + /radares/). Adding a radar is a
    row in the admin, not a template change. `in_development` rows are shown
    as such and never with figures — only a live radar has real numbers."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        IN_DEVELOPMENT = "in_development", "En desarrollo"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    problem = models.CharField("problema que resuelve", max_length=300)
    identifies = models.CharField("qué información identifica", max_length=300)
    audience = models.CharField("a quién está dirigido", max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_DEVELOPMENT)
    cta_label = models.CharField(max_length=60, blank=True)
    cta_url = models.CharField(
        max_length=300,
        blank=True,
        help_text="Ruta interna (/depositos-judiciales/) o URL completa.",
    )
    display_order = models.PositiveSmallIntegerField(default=100)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = "radar"
        verbose_name_plural = "radares"

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE
