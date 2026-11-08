from datetime import date
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
        self.assertContains(response, "Lo&nbsp;detectamos y le ayudamos a recuperarlo.")

    def test_home_carries_company_concept_and_site_schema(self):
        response = self.client.get("/")
        for section_id in ("que-hacemos", "como-trabajamos"):
            self.assertContains(response, f'id="{section_id}"')
        self.assertContains(response, '"@type": "WebSite"')
        self.assertContains(response, '"@type": "Organization"')
        self.assertNotContains(response, "One Organization node")  # template comment never leaks
        # The home description is the company's, not one radar's.
        self.assertNotContains(response, 'name="description" content="Consulte gratis')

    def test_footer_lists_active_radar_landings(self):
        response = self.client.get("/")
        self.assertContains(
            response, '<li><a href="/depositos-judiciales/">Depósitos judiciales</a></li>'
        )


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

    def _render_results(self, match):
        spec = {r.slug: r for r in radars.all_radars()}["depositos-judiciales"]
        patched = fake_spec(
            slug=spec.slug,
            name=spec.name,
            status="active",
            results_row_template=spec.results_row_template,
            search=lambda raw: match,
            is_available=lambda: True,
        )
        with mock.patch.dict(radars._REGISTRY, {spec.slug: patched}, clear=True):
            return self.client.get("/resultados/?nit=890300279")

    def _match(self, claimable=None, claim_status="reclamable"):
        return radars.RadarMatch(
            document_number="890300279",
            party_name="ACME SAS",
            source_declared_name=None,
            document_type="legal_entity",
            rues_active=True,
            finding_count=7980,
            total_amount_cop=3_701_871_805,
            detail_url="/depositos-judiciales/resultado/?nit=890300279",
            extra={"claim_status": claim_status, "claimable": claimable},
        )

    def test_results_render_each_radars_own_row(self):
        CompanyProfile.objects.create(
            name="Amud", nit="1", phone="1", email="info@example.co", address="x", description="d"
        )
        claimable = {
            "count": 320,
            "amount_cop": 232_457_445,
            "closes_on": date(2026, 11, 17),
            "business_days_left": 6,
        }
        response = self._render_results(self._match(claimable))
        self.assertContains(response, "ACME SAS")
        self.assertContains(response, "NIT 890300279")
        # Historical and claimable-now figures are separate columns.
        self.assertContains(response, "7.980 · $ 3.701.871.805")
        self.assertContains(response, "320 · $ 232.457.445")
        self.assertContains(
            response,
            'Hasta el 17/11/2026 '
            '<span class="results-deadline-left">(quedan 6 días hábiles)</span>',
        )
        self.assertContains(response, "jd-tag--open\">Reclamable<")
        self.assertNotContains(response, "Activo")
        self.assertContains(response, 'aria-label="Ver detalle de Depósitos judiciales"')
        self.assertNotContains(response, "Otros radares")
        self.assertContains(response, "Valores tomados de datos públicos de la Rama Judicial")
        self.assertContains(response, 'content="noindex,nofollow"')
        # A per-query page: no nav item is active.
        self.assertNotContains(response, 'class="is-active"')
        self.assertNotContains(response, "Qué puede hacer ahora")

    def test_results_without_open_window_show_nothing_current(self):
        response = self._render_results(self._match(claim_status="no_reclamable"))
        self.assertContains(response, "7.980 · $ 3.701.871.805")
        self.assertContains(response, "Nada vigente")
        self.assertNotContains(response, "jd-tag--open")
        self.assertNotContains(response, "días hábiles")

    def test_results_without_any_match_show_empty_state(self):
        response = self._render_results(None)
        self.assertContains(
            response,
            "No encontramos registros asociados a esta identificación en las fuentes "
            "que monitoreamos",
        )
        self.assertContains(response, "Nueva consulta")
        self.assertContains(response, "Avisarme si aparezco en un próximo listado")
        self.assertNotContains(response, "Otros radares")
