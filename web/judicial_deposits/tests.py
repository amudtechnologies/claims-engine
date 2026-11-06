from unittest import mock

from django.test import TestCase

from . import radar


class LandingTests(TestCase):
    def test_landing_renders_without_a_party_search(self):
        response = self.client.get("/depositos-judiciales/")
        self.assertContains(response, "Dinero olvidado en procesos judiciales")
        self.assertNotContains(response, "RESULTADO PARA ESTA BÚSQUEDA")

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
