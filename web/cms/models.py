from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .sanitize import sanitize_html

# First path segments already owned by the URL conf or by infrastructure; a
# Page slug equal to one of these would be shadowed by (or shadow) a real route.
RESERVED_SLUGS = frozenset(
    {
        "management", "robots-txt", "sitemap-xml", "radares", "resultados",
        "depositos-judiciales", "guias", "static", "media", "summernote",
    }
)  # fmt: skip

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def validate_image_size(file) -> None:
    if file.size > MAX_IMAGE_BYTES:
        raise ValidationError("La imagen no puede superar 5 MB.")


image_validators = [
    FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
    validate_image_size,
]


class PublishedQuerySet(models.QuerySet):
    def live(self):
        """Published and past its publication date — the only rows the public
        site, footer and sitemap may ever see."""
        return self.filter(status=Status.PUBLISHED, published_at__lte=timezone.now())


class Status(models.TextChoices):
    DRAFT = "draft", "Borrador"
    PUBLISHED = "published", "Publicado"


class Redirect(models.Model):
    """A slug that used to resolve and now points elsewhere. Created
    automatically when a published Page/Article's slug changes, so inbound
    links and search-engine entries keep working (301)."""

    old_path = models.CharField(max_length=300, unique=True)
    new_path = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.old_path} → {self.new_path}"


class Category(models.Model):
    name = models.CharField("nombre", max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField("descripción", blank=True)
    is_active = models.BooleanField("activa", default=True)
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("cms:category", kwargs={"category_slug": self.slug})


class PublishableContent(models.Model):
    """Fields and behaviour shared by Page and Article. `body` is stored as
    sanitized HTML and is deliberately editor-agnostic: swapping the admin
    widget never touches the data or the templates."""

    title = models.CharField("título", max_length=200)
    slug = models.SlugField(max_length=140, unique=True)
    body = models.TextField("contenido", blank=True)
    featured_image = models.ImageField(
        "imagen destacada", upload_to="cms/%Y/%m/", blank=True, validators=image_validators
    )
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField("fecha de publicación", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loaded_slug = self.slug if self.pk else None

    def __str__(self) -> str:
        return self.title

    @property
    def is_live(self) -> bool:
        return (
            self.status == Status.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )

    @property
    def seo_title(self) -> str:
        return self.meta_title or self.title

    def path_for_slug(self, slug: str) -> str:
        raise NotImplementedError

    def get_absolute_url(self) -> str:
        return self.path_for_slug(self.slug)

    def clean(self):
        super().clean()
        self.body = sanitize_html(self.body)

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        if self.status == Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        slug_changed = self._loaded_slug is not None and self._loaded_slug != self.slug
        super().save(*args, **kwargs)
        if slug_changed and self.published_at is not None:
            self._record_redirect(self.path_for_slug(self._loaded_slug), self.get_absolute_url())
        self._loaded_slug = self.slug

    @staticmethod
    def _record_redirect(old_path: str, new_path: str) -> None:
        # Re-point earlier redirects at the newest URL (no chains) and drop any
        # redirect that would shadow the URL now in use (no loops).
        Redirect.objects.filter(new_path=old_path).update(new_path=new_path)
        Redirect.objects.filter(old_path=new_path).delete()
        Redirect.objects.update_or_create(old_path=old_path, defaults={"new_path": new_path})


class Page(PublishableContent):
    """Institutional, legal and landing pages served at /<slug>/."""

    show_in_footer = models.BooleanField("mostrar en el footer", default=False)
    footer_order = models.PositiveSmallIntegerField("orden en el footer", default=100)

    class Meta:
        ordering = ["footer_order", "title"]
        verbose_name = "página"
        verbose_name_plural = "páginas"
        permissions = [("publish_page", "Puede publicar y despublicar páginas")]

    def path_for_slug(self, slug: str) -> str:
        return reverse("cms:page", kwargs={"slug": slug})

    def clean(self):
        super().clean()
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({"slug": "Este slug está reservado por el sitio."})


class Article(PublishableContent):
    excerpt = models.TextField("resumen", max_length=400)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="articles",
        verbose_name="autor",
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="articles")

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "artículo"
        verbose_name_plural = "artículos"
        permissions = [("publish_article", "Puede publicar y despublicar artículos")]

    def path_for_slug(self, slug: str) -> str:
        return reverse("cms:article_detail", kwargs={"slug": slug})

    @property
    def author_display(self) -> str:
        """Public byline. Never falls back to the login username."""
        if self.author:
            return self.author.get_full_name() or "Equipo Amud"
        return "Equipo Amud"
