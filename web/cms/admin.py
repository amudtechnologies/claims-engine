from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django_summernote.widgets import SummernoteWidget

from .models import Article, Category, Page, Redirect, Status


class PublishPermissionMixin:
    """Only users with the model's publish permission can change status or
    publication date; everyone else with change access saves drafts."""

    publish_perm = ""

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # The WYSIWYG widget is attached only here: replacing the editor means
        # changing this one line, not the models, templates or stored content.
        if db_field.name == "body":
            kwargs["widget"] = SummernoteWidget
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def _can_publish(self, request) -> bool:
        return request.user.has_perm(self.publish_perm)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not self._can_publish(request):
            readonly += ["status", "published_at"]
        return readonly

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not self._can_publish(request):
            actions.pop("publish", None)
            actions.pop("unpublish", None)
        return actions

    @admin.action(description="Publicar seleccionados")
    def publish(self, request, queryset):
        if not self._can_publish(request):
            self.message_user(request, "No tiene permiso para publicar.", messages.ERROR)
            return
        now = timezone.now()
        for obj in queryset:
            obj.status = Status.PUBLISHED
            obj.published_at = obj.published_at or now
            obj.save()

    @admin.action(description="Despublicar seleccionados (volver a borrador)")
    def unpublish(self, request, queryset):
        if not self._can_publish(request):
            self.message_user(request, "No tiene permiso para publicar.", messages.ERROR)
            return
        for obj in queryset:
            obj.status = Status.DRAFT
            obj.save()

    actions = ["publish", "unpublish"]


@admin.register(Page)
class PageAdmin(PublishPermissionMixin, admin.ModelAdmin):
    publish_perm = "cms.publish_page"
    list_display = ("title", "slug", "status", "show_in_footer", "footer_order", "updated_at")
    list_filter = ("status", "show_in_footer")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "published_at"
    fieldsets = (
        (None, {"fields": ("title", "slug", "body", "featured_image")}),
        ("Publicación", {"fields": ("status", "published_at", "show_in_footer", "footer_order")}),
        ("SEO", {"fields": ("meta_title", "meta_description")}),
    )

    def get_readonly_fields(self, request, obj=None):
        # Footer placement is a publication decision, so it follows the
        # same permission as status.
        readonly = super().get_readonly_fields(request, obj)
        if not self._can_publish(request):
            readonly = [*readonly, "show_in_footer", "footer_order"]
        return readonly

    def view_on_site(self, obj):
        return obj.get_absolute_url()


@admin.register(Article)
class ArticleAdmin(PublishPermissionMixin, admin.ModelAdmin):
    publish_perm = "cms.publish_article"
    list_display = ("title", "status", "author", "published_at", "updated_at")
    list_filter = ("status", "categories")
    search_fields = ("title", "slug", "excerpt")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("categories",)
    autocomplete_fields = ("author",)
    date_hierarchy = "published_at"
    fieldsets = (
        (None, {"fields": ("title", "slug", "excerpt", "body", "featured_image")}),
        ("Clasificación", {"fields": ("author", "categories")}),
        ("Publicación", {"fields": ("status", "published_at")}),
        ("SEO", {"fields": ("meta_title", "meta_description")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("author")

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    def view_on_site(self, obj):
        return obj.get_absolute_url() if settings.CMS_ARTICLES_ENABLED else None


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Redirect)
class RedirectAdmin(admin.ModelAdmin):
    list_display = ("old_path", "new_path", "created_at")
    search_fields = ("old_path", "new_path")
