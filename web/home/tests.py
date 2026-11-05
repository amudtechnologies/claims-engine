from unittest import mock

from django.test import TestCase

from .models import Radar


class HomeTests(TestCase):
    def test_home_renders_search(self):
        response = self.client.get("/")
        self.assertContains(response, 'action="/resultados/"')
        self.assertContains(response, "Su patrimonio puede tener")

    def test_new_radar_appears_without_code_changes_and_without_numbers(self):
        Radar.objects.create(
            name="Radar X", slug="radar-x", problem="p", identifies="i", audience="a"
        )
        response = self.client.get("/radares/")
        self.assertContains(response, "Radar X")
        self.assertContains(response, "En desarrollo")


class ResultsRegressionTests(TestCase):
    def test_empty_query_redirects_home(self):
        self.assertRedirects(self.client.get("/resultados/"), "/", fetch_redirect_response=False)

    def test_unsynced_cache_message(self):
        with mock.patch("home.views.core_cache.is_synced", return_value=False):
            response = self.client.get("/resultados/?nit=900123456")
        self.assertContains(response, "no está disponible")
        self.assertContains(response, "noindex")

    def test_invalid_number_message(self):
        with mock.patch("home.views.core_cache.is_synced", return_value=True):
            response = self.client.get("/resultados/?nit=12")
        self.assertContains(response, "Revise el número")
