from unittest import mock

from django.test import TestCase

from . import radars
from .models import CompanyProfile


def fake_spec(**overrides):
    values = dict(
        slug="radar-x",
        name="Radar X",
        problem="p",
        identifies="i",
        audience="a",
        landing_url_name="home:index",
        results_row_template="home/_test_row.html",
        search=lambda raw: None,
        status="in_development",
    )
    values.update(overrides)
    return radars.RadarSpec(**values)


class HomeTests(TestCase):
    def test_home_renders_search(self):
        response = self.client.get("/")
        self.assertContains(response, 'action="/resultados/"')
        self.assertContains(response, "Lo&nbsp;detectamos primero.")


class RadarRegistryTests(TestCase):
    def test_judicial_deposits_registers_itself(self):
        spec = {r.slug: r for r in radars.all_radars()}["depositos-judiciales"]
        self.assertTrue(spec.is_active)
        self.assertEqual(spec.landing_url_name, "judicial_deposits:index")

    def test_home_radars_section_lists_active_radars(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="radares"')
        # The radar draws its own card (same overview as its landing page):
        # title, legal-terms strip, CTA and figures, with its own stylesheet.
        self.assertContains(response, "Depósitos judiciales")
        self.assertContains(response, "20 días hábiles")
        self.assertContains(
            response, 'href="/depositos-judiciales/" class="radar-list-item radar-card"'
        )
        # A card, not the landing block.
        self.assertNotContains(response, "Consultar mi NIT o cédula")
        self.assertNotContains(response, "Compact version")  # template comment never leaks
        self.assertContains(response, "css/judicial_deposits.css")
        # Nav and footer scroll to the section instead of opening a page.
        self.assertContains(response, 'href="/#radares"', count=2)

    def test_radares_url_redirects_to_home_section(self):
        response = self.client.get("/radares/")
        self.assertRedirects(response, "/#radares", status_code=301, fetch_redirect_response=False)

    def test_in_development_radar_not_listed(self):
        with mock.patch.dict(radars._REGISTRY, clear=False):
            radars.register(fake_spec())
            response = self.client.get("/")
        self.assertNotContains(response, "Radar X")
        self.assertNotContains(response, "En desarrollo")

    def test_active_radars_sort_before_in_development(self):
        with mock.patch.dict(radars._REGISTRY, clear=False):
            radars.register(fake_spec(name="AAA primero alfabético"))
            ordered = [r.slug for r in radars.all_radars()]
        self.assertEqual(ordered[0], "depositos-judiciales")

    def test_invalid_slug_rejected(self):
        with self.assertRaises(ValueError):
            radars.register(fake_spec(slug="Not A Slug"))


class ResultsTests(TestCase):
    def test_empty_query_redirects_home(self):
        self.assertRedirects(self.client.get("/resultados/"), "/", fetch_redirect_response=False)

    def test_unavailable_when_no_radar_has_data(self):
        with mock.patch.dict(radars._REGISTRY, {}, clear=True):
            response = self.client.get("/resultados/?nit=900123456")
        self.assertContains(response, "no está disponible")
        self.assertContains(response, "noindex")

    def test_invalid_number_message(self):
        with mock.patch("judicial_deposits.core_cache.is_synced", return_value=True):
            response = self.client.get("/resultados/?nit=12")
        self.assertContains(response, "Revise el número")

    def test_results_render_each_radars_own_row(self):
        CompanyProfile.objects.create(
            name="Amud", nit="1", phone="1", email="info@example.co", address="x", description="d"
        )
        match = radars.RadarMatch(
            document_number="900123456",
            party_name="ACME SAS",
            source_declared_name=None,
            document_type="legal_entity",
            rues_active=True,
            finding_count=2,
            total_amount_cop=5_000_000,
            detail_url="/depositos-judiciales/resultado/?nit=900123456",
            extra={"claim_status": "reclamable"},
        )
        spec = {r.slug: r for r in radars.all_radars()}["depositos-judiciales"]
        patched = fake_spec(
            slug=spec.slug,
            name=spec.name,
            status="active",
            results_row_template=spec.results_row_template,
            search=lambda raw: match,
        )
        with mock.patch.dict(radars._REGISTRY, {spec.slug: patched}, clear=True):
            response = self.client.get("/resultados/?nit=900123456")
        self.assertContains(response, "ACME SAS")
        self.assertContains(response, "$ 5.000.000")
        self.assertContains(response, "Aún puede reclamarse")
        self.assertContains(response, "NIT 900123456")
        self.assertNotContains(response, "Más radares")
        self.assertContains(response, 'href="/" class="is-active"')
        self.assertNotContains(response, "Qué puede hacer ahora")
