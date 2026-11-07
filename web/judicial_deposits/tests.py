from unittest import mock

from django.test import TestCase

from . import radar


class LandingTests(TestCase):
    def test_landing_renders_without_a_party_search(self):
        response = self.client.get("/depositos-judiciales/")
        self.assertContains(response, '<h1 class="serif jd-title">Depósitos judiciales</h1>')
        for section_id in ("como-funciona", "por-que-amud", "transparencia", "preguntas"):
            self.assertContains(response, f'id="{section_id}"')
        self.assertContains(response, 'href="/#buscar" class="btn btn-primary btn-lg"')
        # No search form here: every "Consultar" button goes to the home search.
        self.assertNotContains(response, 'action="/resultados/"')
        self.assertNotContains(response, 'href="#consultar"')
        # The product demo is always labelled as fictitious data.
        self.assertContains(response, "Demostración · Datos ficticios")
        self.assertNotContains(response, "pequeña comisión")
        self.assertNotContains(response, "RESULTADO DE SU CONSULTA")

    def test_legacy_nit_query_redirects_to_detail(self):
        response = self.client.get("/depositos-judiciales/?nit=900123456")
        self.assertRedirects(
            response,
            "/depositos-judiciales/resultado/?nit=900123456",
            fetch_redirect_response=False,
        )


class DetailTests(TestCase):
    def test_detail_without_nit_goes_to_landing(self):
        self.assertRedirects(
            self.client.get("/depositos-judiciales/resultado/"),
            "/depositos-judiciales/",
            fetch_redirect_response=False,
        )

    def test_detail_is_noindex_and_handles_unsynced_cache(self):
        with mock.patch("judicial_deposits.views.core_cache.is_synced", return_value=False):
            response = self.client.get("/depositos-judiciales/resultado/?nit=900123456")
        self.assertContains(response, "noindex")
        self.assertContains(response, "no está disponible")

    def test_detail_without_match(self):
        with (
            mock.patch("judicial_deposits.views.core_cache.is_synced", return_value=True),
            mock.patch("judicial_deposits.views.party_search.search_party", return_value=None),
        ):
            response = self.client.get("/depositos-judiciales/resultado/?nit=900123456")
        self.assertContains(response, "No encontramos depósitos judiciales")


class RadarContractTests(TestCase):
    def test_search_returns_none_without_a_match(self):
        with mock.patch("judicial_deposits.radar.party_search.search_party", return_value=None):
            self.assertIsNone(radar.search("900123456"))

    def test_spec_points_at_this_apps_own_templates_and_urls(self):
        self.assertEqual(radar.spec.results_row_template, "judicial_deposits/_results_row.html")
        self.assertEqual(radar.spec.landing_url_name, "judicial_deposits:index")

    def test_card_stats_empty_when_unsynced(self):
        with mock.patch("judicial_deposits.radar.core_cache.is_synced", return_value=False):
            self.assertEqual(radar.card_stats(), [])

    def test_card_stats_match_the_landing_figures(self):
        with (
            mock.patch("judicial_deposits.radar.core_cache.is_synced", return_value=True),
            mock.patch("judicial_deposits.radar.party_search") as ps,
        ):
            ps.latest_published_period.return_value = "2026-2"
            ps.total_court_count.return_value = 4598
            ps.total_party_count.return_value = 1_270_000
            ps.total_claim_amount_cop.return_value = 970_428_695_188
            stats = radar.card_stats()
        self.assertEqual(
            stats,
            [
                ("2017–2026", "Historial de datos públicos"),
                ("4.598", "Despachos judiciales analizados"),
                ("1,27M+", "Partes identificadas"),
                ("$ 970.428.695.188", "Valor total de los depósitos identificados a la fecha"),
            ],
        )
