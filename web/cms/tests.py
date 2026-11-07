from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Article, Category, Page, Redirect, Status
from .sanitize import sanitize_html


def make_page(slug="quienes-somos", **kwargs):
    kwargs.setdefault("title", slug.title())
    kwargs.setdefault("status", Status.PUBLISHED)
    return Page.objects.create(slug=slug, **kwargs)


def make_article(slug="guia", **kwargs):
    kwargs.setdefault("title", slug.title())
    kwargs.setdefault("excerpt", "Resumen")
    kwargs.setdefault("status", Status.PUBLISHED)
    return Article.objects.create(slug=slug, **kwargs)


class SanitizeTests(TestCase):
    def test_strips_scripts_handlers_and_js_urls(self):
        dirty = (
            '<p onclick="x()">Hola</p><script>alert(1)</script>'
            '<a href="javascript:alert(1)">l</a><img src="data:text/html;base64,AA" onerror="x()">'
        )
        clean = sanitize_html(dirty)
        for bad in ("script", "onclick", "onerror", "javascript:", "data:"):
            self.assertNotIn(bad, clean)
        self.assertIn("Hola", clean)

    def test_keeps_editor_formatting_and_adds_rel(self):
        clean = sanitize_html('<h2>T</h2><table><tr><td>1</td></tr></table><a href="https://x.co">x</a>')
        self.assertIn("<h2>T</h2>", clean)
        self.assertIn("<table>", clean)
        self.assertIn("noopener", clean)

    def test_keeps_toolbar_output(self):
        html = (
            '<h2 style="text-align: center;">T</h2>'
            "<p><strike>a</strike><sup>2</sup><sub>1</sub></p>"
            '<hr><p style="color: red; text-align: right;">x</p>'
        )
        clean = sanitize_html(html)
        for kept in ("<strike>", "<sup>", "<sub>", "<hr>", "text-align:center", "text-align:right"):
            self.assertIn(kept, clean)
        self.assertNotIn("red", clean)

    def test_save_sanitizes_body(self):
        page = make_page(body="<p>ok</p><script>bad()</script>")
        page.refresh_from_db()
        self.assertNotIn("script", page.body)


class PageTests(TestCase):
    def test_published_page_is_served_and_draft_is_404(self):
        make_page("quienes-somos", body="<p>Quiénes somos</p>")
        make_page("borrador", status=Status.DRAFT)
        self.assertContains(self.client.get("/quienes-somos/"), "Quiénes somos")
        self.assertEqual(self.client.get("/borrador/").status_code, 404)

    def test_scheduled_page_is_not_public_yet(self):
        make_page("futuro", published_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.client.get("/futuro/").status_code, 404)

    def test_staff_can_preview_draft_with_noindex(self):
        User = get_user_model()
        staff = User.objects.create_superuser("admin", "a@x.co", "pw")
        make_page("borrador", status=Status.DRAFT)
        self.client.force_login(staff)
        response = self.client.get("/borrador/")
        self.assertContains(response, "noindex")

    def test_slug_unique_and_reserved(self):
        make_page("uno")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_page("uno")
        with self.assertRaises(ValidationError):
            Page(title="x", slug="radares").full_clean()

    def test_does_not_shadow_fixed_routes(self):
        self.assertEqual(self.client.get("/radares/").status_code, 301)
        self.assertEqual(self.client.get("/depositos-judiciales/").status_code, 200)

    def test_slug_change_creates_301_and_avoids_chains(self):
        page = make_page("viejo")
        page.slug = "medio"
        page.save()
        page.slug = "nuevo"
        page.save()
        for old in ("/viejo/", "/medio/"):
            response = self.client.get(old)
            self.assertRedirects(
                response, "/nuevo/", status_code=301, fetch_redirect_response=False
            )
        self.assertEqual(Redirect.objects.count(), 2)

    def test_unpublish_removes_page_footer_and_sitemap(self):
        page = make_page("legal", show_in_footer=True, footer_order=1)
        self.assertContains(self.client.get("/"), 'href="/legal/"')
        self.assertContains(self.client.get("/sitemap.xml"), "/legal/")
        page.status = Status.DRAFT
        page.save()
        self.assertNotContains(self.client.get("/"), 'href="/legal/"')
        self.assertNotContains(self.client.get("/sitemap.xml"), "/legal/")
        self.assertEqual(self.client.get("/legal/").status_code, 404)

    def test_deleted_page_is_404_and_gone_from_sitemap(self):
        page = make_page("temporal")
        page.delete()
        self.assertEqual(self.client.get("/temporal/").status_code, 404)
        self.assertNotContains(self.client.get("/sitemap.xml"), "/temporal/")


class FooterTests(TestCase):
    def test_footer_respects_flag_and_order(self):
        make_page("b-pagina", title="Segunda", show_in_footer=True, footer_order=20)
        make_page("a-pagina", title="Primera", show_in_footer=True, footer_order=10)
        make_page("oculta", title="Oculta", show_in_footer=False)
        make_page("borrador", title="Borrador", show_in_footer=True, status=Status.DRAFT)
        html = self.client.get("/").content.decode()
        self.assertLess(html.index("Primera"), html.index("Segunda"))
        self.assertNotIn(">Oculta<", html)
        self.assertNotIn(">Borrador<", html)


class ArticleTests(TestCase):
    def setUp(self):
        # Migration 0003 seeds sample articles/categories; these tests need a clean slate.
        Article.objects.all().delete()
        Category.objects.all().delete()

    def test_detail_seo_metadata(self):
        article = make_article(
            "como-reclamar", meta_title="Cómo reclamar", meta_description="Desc SEO"
        )
        article.categories.add(Category.objects.create(name="Guías", slug="guias-cat"))
        response = self.client.get("/guias/como-reclamar/")
        self.assertContains(response, "<title>Cómo reclamar — Amud Technologies</title>", html=True)
        self.assertContains(response, 'name="description" content="Desc SEO"')
        self.assertContains(response, 'rel="canonical" href="http://testserver/guias/como-reclamar/"')
        self.assertContains(response, 'property="og:type" content="article"')
        self.assertContains(response, '"@type": "Article"')
        self.assertContains(response, "BreadcrumbList")

    def test_json_ld_cannot_be_broken_out_of(self):
        make_article("xss", title="</script><script>alert(1)</script>")
        self.assertNotContains(self.client.get("/guias/xss/"), "</script><script>alert(1)")

    def test_author_display_never_leaks_username(self):
        user = get_user_model().objects.create_user("secret_login", password="pw")
        article = make_article("a", author=user)
        self.assertEqual(article.author_display, "Equipo Amud Technologies")
        self.assertNotContains(self.client.get("/guias/a/"), "secret_login")

    def test_list_updates_automatically_and_hides_drafts(self):
        self.assertNotContains(self.client.get("/guias/"), "Nueva guía")
        make_article("nueva", title="Nueva guía")
        make_article("oculta", title="Guía oculta", status=Status.DRAFT)
        response = self.client.get("/guias/")
        self.assertContains(response, "Nueva guía")
        self.assertNotContains(response, "Guía oculta")
        self.assertEqual(self.client.get("/guias/oculta/").status_code, 404)

    def test_category_page_paginates(self):
        cat = Category.objects.create(name="Guías", slug="guias-cat")
        for i in range(11):
            make_article(f"art-{i}", title=f"Art {i}").categories.add(cat)
        self.assertEqual(len(self.client.get("/guias/categoria/guias-cat/").context["page_obj"]), 9)
        page2 = self.client.get("/guias/categoria/guias-cat/?page=2")
        self.assertEqual(len(page2.context["page_obj"]), 2)
        self.assertContains(
            page2, 'rel="canonical" href="http://testserver/guias/categoria/guias-cat/?page=2"'
        )

    def test_list_groups_by_category_with_chips_and_clipped_summary(self):
        legal = Category.objects.create(name="Legal", slug="legal")
        deposits = Category.objects.create(name="Depósitos", slug="depositos")
        long_excerpt = "x" * 80
        make_article("a1", title="Primera", excerpt=long_excerpt).categories.add(legal, deposits)
        make_article("a2", title="Segunda").categories.add(legal)
        make_article("a3", title="Sin categoría")
        response = self.client.get("/guias/")
        groups = response.context["groups"]
        # Each article appears once, under its first category (alphabetical).
        self.assertEqual([g["category"] for g in groups], [deposits, legal, None])
        self.assertContains(response, 'href="/guias/categoria/legal/"')  # chip links
        self.assertContains(response, "x" * 50 + "...")
        self.assertNotContains(response, "x" * 51)

    def test_placeholder_image_when_no_featured_image(self):
        make_article("sin-imagen")
        self.assertContains(self.client.get("/guias/"), "img/article-placeholder.svg")

    def test_group_preview_limited_with_link_to_category(self):
        cat = Category.objects.create(name="Legal", slug="legal")
        for i in range(8):
            make_article(f"g-{i}").categories.add(cat)
        response = self.client.get("/guias/")
        self.assertEqual(len(response.context["groups"][0]["articles"]), 6)
        self.assertContains(response, "Ver las 8 guías")

    def test_nav_and_footer_link_to_articles(self):
        html = self.client.get("/").content.decode()
        self.assertEqual(html.count('href="/guias/"'), 2)
        self.assertIn(">Aprenda</a>", html)

    def test_empty_list_is_noindex_and_not_in_sitemap(self):
        self.assertContains(self.client.get("/guias/"), "noindex")
        self.assertNotContains(self.client.get("/sitemap.xml"), "/guias/</loc>")
        make_article("uno")
        self.assertNotContains(self.client.get("/guias/"), "noindex")

    def test_category_filter_and_inactive_category(self):
        cat = Category.objects.create(name="Prescripción", slug="prescripcion")
        make_article("en-cat", title="En categoría").categories.add(cat)
        make_article("fuera", title="Fuera de categoría")
        response = self.client.get("/guias/categoria/prescripcion/")
        self.assertContains(response, "En categoría")
        self.assertNotContains(response, "Fuera de categoría")
        cat.is_active = False
        cat.save()
        self.assertEqual(self.client.get("/guias/categoria/prescripcion/").status_code, 404)

    def test_article_slug_change_redirects(self):
        article = make_article("antes")
        article.slug = "despues"
        article.save()
        self.assertRedirects(
            self.client.get("/guias/antes/"), "/guias/despues/", status_code=301,
            fetch_redirect_response=False,
        )

    def test_sitemap_lists_only_live_content(self):
        make_article("publicado")
        make_article("borrador", status=Status.DRAFT)
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/guias/publicado/", xml)
        self.assertNotIn("/guias/borrador/", xml)

    def test_published_at_set_on_first_publish(self):
        article = make_article("auto")
        self.assertIsNotNone(article.published_at)


class AdminPermissionTests(TestCase):
    def test_editor_without_publish_perm_cannot_publish(self):
        from django.contrib.auth.models import Permission

        User = get_user_model()
        editor = User.objects.create_user("ed", password="pw", is_staff=True)
        codenames = ["add_page", "change_page", "view_page"]
        editor.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(editor)
        response = self.client.get(reverse("admin:cms_page_add"))
        self.assertEqual(response.status_code, 200)
        form_fields = response.context["adminform"].form.fields
        self.assertNotIn("status", form_fields)

    def test_publisher_sees_status(self):
        admin_user = get_user_model().objects.create_superuser("root", "r@x.co", "pw")
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:cms_page_add"))
        self.assertIn("status", response.context["adminform"].form.fields)
        self.assertEqual(self.client.get(reverse("admin:cms_article_add")).status_code, 200)


class RobotsTests(TestCase):
    def test_robots_blocks_real_admin_path(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /management/", body)
        self.assertIn("Sitemap:", body)
