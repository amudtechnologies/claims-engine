import dataclasses
import io
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock, skipUnless

import duckdb
from django.core.management import call_command
from django.test import TestCase, override_settings
from home.templatetags.home_extras import cop

from . import core_cache, corpus_stats, history, insights, party_search, preview, radar
from .models import ClaimWindow
from .party_search import Deposit, PartySearchResult
from .templatetags.jd_charts import axis_ticks, cop_short


class LandingTests(TestCase):
    def test_landing_renders_without_a_party_search(self):
        response = self.client.get("/depositos-judiciales/")
        self.assertContains(response, '<h1 class="serif jd-title">Depósitos judiciales</h1>')
        for section_id in ("transparencia", "preguntas"):
            self.assertContains(response, f'id="{section_id}"')
        self.assertNotContains(response, 'id="por-que-amud"')
        self.assertNotContains(response, 'id="como-funciona"')
        self.assertContains(response, 'href="/#buscar" class="btn btn-primary btn-lg"')
        # No search form here: every "Consultar" button goes to the home search.
        self.assertNotContains(response, 'action="/resultados/"')
        self.assertNotContains(response, 'href="#consultar"')
        # The product demo is always labelled as fictitious data.
        self.assertContains(response, '<span class="jd-demo-badge mono">Demostración</span>')
        self.assertContains(response, 'aria-label="Demostración de resultados con datos ficticios"')
        self.assertNotContains(response, "pequeña comisión")
        self.assertNotContains(response, "RESULTADO DE SU CONSULTA")
        # Structured data matches what the page shows: the service and its trail.
        self.assertContains(response, '"@type": "Service"')
        self.assertContains(response, "BreadcrumbList")
        self.assertContains(response, "títulos judiciales")

    def test_landing_never_aggregates_the_corpus_per_request(self):
        # No precomputed file: no section, and the heavy query never runs.
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(corpus_stats, "stats_path", return_value=Path(tmp) / "none.json"),
            mock.patch.object(corpus_stats, "_fetch_slices", side_effect=AssertionError),
        ):
            response = self.client.get("/depositos-judiciales/")
        self.assertNotContains(response, 'id="estadisticas"')

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
            mock.patch(
                "judicial_deposits.views.party_search.latest_published_period",
                return_value="2026-2",
            ),
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


def _deposit(period, amount_cop, court_office="Juzgado 1", court_account=None, name=None):
    return Deposit(
        claim_id=f"{period}-{amount_cop}",
        court_office=court_office,
        court_account=court_account,
        amount_cop=amount_cop,
        constituted_on=date(2020, 1, 1),
        procedural_role="plaintiff",
        period=period,
        source="judicial_deposits",
        source_declared_name=name,
    )


class BusinessDaysTests(TestCase):
    def test_counts_weekdays_through_the_closing_day(self):
        # Sunday 8 Nov → Tuesday 17 Nov 2026: Mon-Fri 9-13 and Tue 17; Mon 16
        # is a public holiday (Independencia de Cartagena, moved to Monday).
        self.assertEqual(party_search.business_days_left(date(2026, 11, 17), date(2026, 11, 8)), 6)

    def test_public_holiday_today_is_not_counted(self):
        self.assertEqual(party_search.business_days_left(date(2026, 11, 17), date(2026, 11, 16)), 1)

    def test_closing_today_leaves_today(self):
        self.assertEqual(party_search.business_days_left(date(2026, 11, 17), date(2026, 11, 17)), 1)

    def test_past_window_has_none_left(self):
        self.assertEqual(party_search.business_days_left(date(2026, 11, 17), date(2026, 11, 18)), 0)


class ClaimableNowTests(TestCase):
    def setUp(self):
        ClaimWindow.objects.create(
            period="2026-2", opens_on=date(2026, 10, 19), closes_on=date(2026, 11, 17)
        )
        self.result = PartySearchResult(
            document_number="890300279",
            party_name="ACME SAS",
            document_type="legal_entity",
            rues_active=True,
            deposits=[_deposit("2025-1", 1_000), _deposit("2026-2", 200), _deposit("2026-2", 300)],
        )

    def _search(self, today, latest_period="2026-2"):
        with (
            mock.patch(
                "judicial_deposits.radar.party_search.search_party", return_value=self.result
            ),
            mock.patch(
                "judicial_deposits.radar.party_search.latest_published_period",
                return_value=latest_period,
            ),
            mock.patch("django.utils.timezone.localdate", return_value=today),
        ):
            return radar.search("890300279")

    def test_open_window_on_latest_publication_is_claimable(self):
        match = self._search(date(2026, 11, 8))
        self.assertEqual((match.finding_count, match.total_amount_cop), (3, 1_500))
        self.assertEqual(
            match.extra["claimable"],
            {
                "count": 2,
                "amount_cop": 500,
                "closes_on": date(2026, 11, 17),
                "business_days_left": 6,
            },
        )

    def test_expired_window_is_not_claimable(self):
        self.assertIsNone(self._search(date(2026, 11, 18)).extra["claimable"])

    def test_absent_from_latest_publication_is_not_claimable(self):
        self.assertIsNone(
            self._search(date(2026, 11, 8), latest_period="2027-1").extra["claimable"]
        )

    def test_unconfigured_window_is_not_claimable(self):
        ClaimWindow.objects.all().delete()
        self.assertIsNone(self._search(date(2026, 11, 8)).extra["claimable"])

    def test_results_page_matches_detail_page_figures(self):
        with (
            mock.patch("judicial_deposits.core_cache.is_synced", return_value=True),
            mock.patch("judicial_deposits.views.core_cache.is_synced", return_value=True),
            mock.patch("judicial_deposits.party_search.search_party", return_value=self.result),
            mock.patch(
                "judicial_deposits.party_search.latest_published_period", return_value="2026-2"
            ),
            mock.patch(
                "judicial_deposits.party_search.published_periods",
                return_value=["2025-1", "2026-2"],
            ),
            mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 8)),
        ):
            results = self.client.get("/resultados/?nit=890300279").content.decode()
            detail = self.client.get("/depositos-judiciales/resultado/?nit=890300279")
        self.assertIn("2 · $ 500", results)
        self.assertIn("Hasta el 17/11/2026", results)
        self.assertContains(detail, "Última publicación · 2026-2")
        self.assertContains(detail, "$ 500")
        self.assertContains(detail, "17/11/2026")


class SourceDeclaredNameTests(TestCase):
    def test_most_frequent_spelling_wins_whatever_the_row_order(self):
        names = ["OCCIDENTE   BANCO DE", "BANCO DE OCCIDENTE", "BANCO  DE OCCIDENTE"]
        for ordering in (names, list(reversed(names))):
            result = PartySearchResult(
                document_number="890300279",
                party_name=None,
                document_type=None,
                rues_active=None,
                deposits=[_deposit("2018-1", i, name=name) for i, name in enumerate(ordering)],
            )
            self.assertEqual(result.source_declared_name, "BANCO DE OCCIDENTE")

    def test_name_written_twice_counts_as_the_single_spelling(self):
        # 2023-2 states names like this; the doubled form must not win the vote.
        names = ["BANCO FINANDINA SA BANCO FINANDINA SA"] * 3 + ["BANCO FINANDINA SA"]
        names += ["BANCO FINANDINA X"] * 2
        result = PartySearchResult(
            document_number="860051894",
            party_name=None,
            document_type=None,
            rues_active=None,
            deposits=[_deposit("2023-2", i, name=name) for i, name in enumerate(names)],
        )
        self.assertEqual(result.source_declared_name, "BANCO FINANDINA SA")

    def test_collapse_doubled_leaves_other_names_alone(self):
        self.assertEqual(party_search._collapse_doubled("FINANDINA FINANDINA"), "FINANDINA")
        self.assertEqual(party_search._collapse_doubled("BANCO DE BOGOTA"), "BANCO DE BOGOTA")
        self.assertEqual(party_search._collapse_doubled("SA SA BANCO"), "SA SA BANCO")


DETAIL_URL = "/depositos-judiciales/resultado/?nit=890300279"
NBSP = "\u00a0"


def _comparison(period, value, count):
    """A comparison chart summary; no-break spaces keep "valor +12,3 %" whole."""
    return f"Frente a {period}: valor{NBSP}{value}{NBSP}%, depósitos{NBSP}{count}{NBSP}%"
OPEN_WINDOW_NOTE = (
    "Que la publicación siga en plazo de reclamo no confirma que el dinero le "
    "corresponda ni que aún no haya sido entregado."
)
PERIODS = ["2017-1", "2025-1", "2025-2", "2026-2"]


def _result(deposits):
    return PartySearchResult(
        document_number="890300279",
        party_name="ACME SAS",
        document_type="legal_entity",
        rues_active=True,
        deposits=deposits,
    )


class DetailPageTests(TestCase):
    """The detail page's three latest-publication states, its layout and
    the page chrome, against a mocked party (no core cache needed)."""

    def setUp(self):
        ClaimWindow.objects.create(
            period="2026-2", opens_on=date(2026, 10, 19), closes_on=date(2026, 11, 17)
        )
        self.result = _result(
            [_deposit("2025-1", 1_000_000), _deposit("2026-2", 200), _deposit("2026-2", 300)]
        )

    def _patches(self, today, latest_period):
        return [
            mock.patch("judicial_deposits.views.core_cache.is_synced", return_value=True),
            mock.patch("judicial_deposits.party_search.search_party", return_value=self.result),
            mock.patch(
                "judicial_deposits.party_search.latest_published_period",
                return_value=latest_period,
            ),
            mock.patch("judicial_deposits.party_search.published_periods", return_value=PERIODS),
            mock.patch("django.utils.timezone.localdate", return_value=today),
        ]

    def _request(
        self, method="get", url=DETAIL_URL, today=date(2026, 11, 8), latest="2026-2", **kwargs
    ):
        patches = self._patches(today, latest)
        for patch in patches:
            patch.start()
        try:
            return getattr(self.client, method)(url, **kwargs)
        finally:
            for patch in patches:
                patch.stop()

    def _with_preview_deposits(self):
        def deposit(amount, number, account, day):
            return Deposit(
                claim_id=f"c{number}",
                court_office="680014303000-OFICINA EJECU CIVIL MPAL BUCARAMANGA",
                amount_cop=amount,
                constituted_on=date(2023, 11, day),
                procedural_role="plaintiff",
                period="2026-2",
                source="judicial_deposits",
                source_declared_name=None,
                court_account=account,
                deposit_no=number,
                city="Bucaramanga",
            )

        self.result = _result(
            [
                deposit(36_161_788, "460010001838272", "680012041802", 17),
                deposit(33_168_013, "460010001858260", "680012041803", 19),
                deposit(1_000, "460010001999999", "680012041804", 20),
            ]
        )

    def test_open_window_shows_masked_preview_and_contact(self):
        self._with_preview_deposits()
        response = self._request()
        html = response.content.decode()
        self.assertContains(response, "¿Desea más detalles?")
        self.assertContains(response, "Ver más detalles")
        # The readable row: largest deposit, court and amount in clear.
        self.assertContains(response, "Oficina Ejecu Civil Mpal Bucaramanga")
        self.assertContains(response, "$ 36.161.788")
        self.assertContains(response, "46001••••••••••")
        self.assertContains(response, "6800••••••••")
        # Constitution date: only the year.
        self.assertContains(response, "••/••/2023")
        self.assertNotContains(response, "17/11/2023")
        # Nothing real of any row's numbers, nor the faded rows' amounts,
        # reaches the page.
        for secret in (
            "460010001838272",
            "460010001858260",
            "680012041802",
            "680012041803",
            "33.168.013",
        ):
            self.assertNotIn(secret, html)
        self.assertContains(
            response, '2 depósitos más por <span class="jd-more-sum">$ 33.169.013</span>'
        )
        self.assertContains(
            response,
            "Contáctenos para ver el detalle completo de estos depósitos y verificar si le "
            "corresponde reclamarlos.",
        )
        # "Contactar" next to "Ver más detalles", and again under the table.
        self.assertContains(response, 'href="https://wa.me/573054381677?text=', count=2)
        self.assertContains(response, "data-jd-more-toggle")
        self.assertContains(response, "deposit_preview.js")
        self.assertContains(response, "consult%C3%A9%20el%20NIT%20890300279")

    def test_defendant_only_gets_ownership_note(self):
        note = "Que aparezca como demandado no significa que el dinero sea de la otra parte"
        self._with_preview_deposits()
        self.assertNotContains(self._request(), note)
        self.result = dataclasses.replace(
            self.result,
            deposits=[
                dataclasses.replace(d, procedural_role="defendant") for d in self.result.deposits
            ],
        )
        self.assertContains(self._request(), note)

    def test_closed_window_has_no_preview(self):
        self._with_preview_deposits()
        response = self._request(today=date(2026, 11, 18))
        self.assertNotContains(response, "Ver más detalles")
        self.assertNotContains(response, "wa.me")

    def _with_long_history(self):
        def deposit(period, amount, city="BOGOTA", role="plaintiff"):
            return Deposit(
                claim_id=f"{period}-{amount}",
                court_office="110012041014 Juz 014 Civil Municipal Bogota",
                amount_cop=amount,
                constituted_on=date(2015, 7, 31),
                procedural_role=role,
                period=period,
                source="judicial_deposits",
                source_declared_name=None,
                court_account="110012041014",
                deposit_no=f"4001000050{amount:05d}",
                city=city,
            )

        deposits = [deposit("2026-2", 99_999)]
        deposits += [deposit("2025-2", 10_000 + i) for i in range(23)]
        deposits += [deposit("2025-1", 500, city="PEREIRA", role="defendant")]
        self.result = _result(deposits)

    def test_previous_publications_list_and_sample(self):
        self._with_long_history()
        html = self._request().content.decode()
        history_html = html[html.index("Publicaciones anteriores") :]
        self.assertNotIn("publicaciones anteriores, desde", history_html)
        # Totals leave out the latest publication.
        self.assertIn('<div class="jd-summary-num mono">24</div>', history_html)
        # The most recent previous publication opens by default: its five
        # largest deposits and how many (and how much) are left.
        self.assertIn(">2025-2</a>", history_html)
        self.assertEqual(history_html.count("Demandante</td>"), 5)
        self.assertIn("18 depósitos más por $ 180.153 <span", history_html)
        self.assertIn("· Contáctenos para ver el histórico completo", history_html)
        self.assertIn('<span class="jd-pub-shown">5 de 23</span>', history_html)
        # Only two previous publications: nothing hidden, so no "Contactar".
        self.assertNotIn("https://wa.me/", history_html)
        self.assertNotIn("Mostrando", history_html)
        self.assertIn("pub=ninguna", history_html)
        # Closing it keeps everything closed.
        html = self._request(url=DETAIL_URL + "&pub=ninguna").content.decode()
        self.assertIn(">2025-2</a>", html)
        self.assertNotIn("jd-pub-deposits", html)

        html = self._request(url=DETAIL_URL + "&pub=2025-2").content.decode()
        self.assertIn("Bogotá D.C.", html)
        self.assertIn("40010••••••••••", html)
        self.assertIn("1100••••••••", html)
        self.assertIn("••/••/2015", html)
        self.assertNotIn("31/07/2015", html)
        # Never a full deposit number or judicial account.
        self.assertNotIn("110012041014", html)
        self.assertNotIn("400100005010000", html)

    def test_first_appearance_history_is_one_line(self):
        self.result = _result([_deposit("2026-2", 200), _deposit("2026-2", 300)])
        html = self._request().content.decode()
        history = html[html.index("Publicaciones anteriores") :]
        self.assertIn(
            "Primera vez: este NIT no aparece en ninguna publicación anterior.", history
        )
        # The history no longer repeats the latest publication's figures.
        self.assertNotIn("Depósitos encontrados", history)
        self.assertNotIn("Última publicación en la que aparece", history)

    def test_returning_party_keeps_full_history(self):
        html = self._request().content.decode()
        history = html[html.index("Publicaciones anteriores") :]
        self.assertNotIn("Primera vez", history)
        self.assertIn("Depósitos encontrados", history)

    def test_claimable_state(self):
        response = self._request()
        html = response.content.decode()
        self.assertLess(
            html.index("Última publicación · 2026-2"), html.index("Publicaciones anteriores")
        )
        self.assertContains(
            response,
            "Plazo de reclamo hasta el <strong>17/11/2026</strong>"
            '<span class="jd-deadline-sep"> · </span>'
            '<span class="jd-deadline-left">quedan 6 días hábiles</span>',
        )
        self.assertContains(response, 'jd-tag--open">Plazo abierto<')
        self.assertNotContains(response, "is-absent")
        self.assertContains(response, OPEN_WINDOW_NOTE)
        self.assertContains(response, "DEPÓSITOS JUDICIALES SUSCEPTIBLES DE PRESCRIPCIÓN")
        # Informational only: no collection/verification request, no sales copy.
        for commercial in (
            "Quiero recuperarlo",
            "Solicitar verificación",
            "Honorarios",
            "gestionamos el cobro",
            'method="post"',
            "<dialog",
        ):
            self.assertNotContains(response, commercial)
        self.assertEqual(self._request("post").status_code, 200)
        self.assertContains(
            response,
            "No podemos confirmar si estos depósitos se reclamaron dentro del plazo de su "
            "publicación.",
        )
        self.assertNotContains(response, "Importante:")

    def test_expired_state(self):
        response = self._request(today=date(2026, 11, 18))
        self.assertContains(response, 'jd-tag--closed">Plazo vencido<')
        self.assertContains(response, "Plazo de reclamo vencido el 17/11/2026")
        self.assertNotContains(response, "días hábiles")
        # The "no confirma" caveat is about an open window only.
        self.assertNotContains(response, OPEN_WINDOW_NOTE)

    def test_absent_from_latest_publication_state(self):
        response = self._request(today=date(2026, 11, 18), latest="2027-1")
        html = response.content.decode()
        self.assertContains(response, "Última publicación · 2027-1")
        self.assertContains(response, "No aparece en la publicación vigente (2027-1)")
        self.assertContains(response, 'class="jd-block jd-block--current is-absent"')
        # Then the last publication it does appear in, then the history.
        last = html.index("Última publicación en la que aparece · 2026-2")
        self.assertLess(html.index("No aparece en la publicación vigente"), last)
        self.assertLess(last, html.index("Publicaciones anteriores"))
        last_block = html[last : html.index("Publicaciones anteriores")]
        self.assertIn('jd-tag--closed">Plazo vencido<', last_block)
        self.assertIn('<div class="jd-summary-num mono">2</div>', last_block)
        self.assertIn('<div class="jd-summary-num mono">$ 500</div>', last_block)
        self.assertIn("Plazo de reclamo vencido el 17/11/2026", last_block)
        self.assertIn("Como demandante", last_block)

    def test_last_appearance_charts_and_wording(self):
        self.result = _result(
            [_deposit("2025-2", 2_000) for _ in range(5)]
            + [_deposit("2026-2", 1_000 + i) for i in range(10)]
        )
        response = self._request(today=date(2026, 11, 18), latest="2027-1")
        html = response.content.decode()
        last_block = html[
            html.index("Última publicación en la que aparece ·") : html.index(
                "Publicaciones anteriores"
            )
        ]
        self.assertIn("jd-charts jd-charts--compact is-muted", last_block)
        self.assertIn('id="jd-chart-last-previous-period-title"', last_block)
        self.assertIn(_comparison("2025-2", "+0,4", "+100,0"), last_block)
        # 2026-2 is highlighted there, but it isn't the current publication.
        self.assertIn("Resaltada la publicación (2026-2)", last_block)
        self.assertNotIn("(vigente)", last_block)

    def test_present_in_latest_publication_has_no_last_appearance_block(self):
        self.assertNotContains(self._request(), "Última publicación en la que aparece ·")

    def test_page_chrome(self):
        response = self._request()
        self.assertContains(response, '<meta name="robots" content="noindex,nofollow">')
        self.assertContains(response, 'href="/resultados/?nit=890300279">&larr; Volver al resumen')
        self.assertContains(response, 'class="btn btn-primary jd-again-btn">Nueva consulta')
        self.assertContains(response, 'class="masthead"')
        # The "Fuente: … · periodo" line was removed from this page on purpose.
        self.assertNotContains(response, "· periodo 2026-2")

    def test_no_charts_below_the_threshold(self):
        response = self._request()
        self.assertNotContains(response, "jd-charts")
        self.assertNotContains(response, "Evolución por publicación")

    def test_charts_from_the_threshold_without_court_names(self):
        self.result = _result(
            [_deposit("2025-1", 1_000 + i, court_office="Juzgado 7 Civil Cali") for i in range(10)]
        )
        response = self._request()
        for title in (
            "Evolución por publicación",
            "Distribución por rango de valor",
            "Por departamento",
        ):
            self.assertContains(response, title)
        self.assertNotContains(response, "especialidad")
        # The history covers the publications before the latest one: 3 of PERIODS.
        self.assertContains(response, "Aparece en 1 de 3 publicaciones")
        # Collapsed by default, like the landing's FAQ: nothing renders open.
        self.assertContains(response, '<details class="jd-chart jd-chart--vertical">')
        # 3 in the history + 3 compact ones for the last publication it appears
        # in (2025-1: it isn't in the latest one).
        self.assertEqual(response.content.decode().count('<details class="jd-chart '), 6)
        self.assertNotContains(response, "<details open")
        self.assertNotContains(response, 'class="jd-chart jd-chart--vertical" open')
        self.assertContains(response, "Ver datos")
        self.assertContains(response, 'role="img"')
        # The charts never name a court (the open publication's rows do).
        html = response.content.decode()
        charts = html[html.index('class="jd-charts"') : html.index('id="jd-publicaciones"')]
        self.assertNotIn("Juzgado 7", charts)
        self.assertContains(response, "10 · $ 10.045")

    def _current_with_findings(self, count):
        self.result = _result(
            [_deposit("2025-1", 1_000_000)]
            + [
                _deposit("2026-2", 1_000 + i, court_office="Juzgado 7 Civil Cali")
                for i in range(count)
            ]
        )

    def test_current_publication_charts_below_the_threshold(self):
        self._current_with_findings(9)
        response = self._request()
        self.assertNotContains(response, "jd-charts--compact")

    def test_current_publication_charts_under_the_note(self):
        self._current_with_findings(10)
        response = self._request()
        html = response.content.decode()
        compact = html.index("jd-charts jd-charts--compact")
        self.assertLess(html.index(OPEN_WINDOW_NOTE), compact)
        self.assertLess(compact, html.index("Publicaciones anteriores"))
        # The open-window call to action sits before the optional charts.
        self.assertLess(html.index('class="jd-more"'), compact)
        self.assertLess(
            html.index('id="jd-chart-current-previous-period-title"'),
            html.index('id="jd-chart-current-department-title"'),
        )
        self.assertContains(response, "No aparecía en 2025-2")
        self.assertContains(response, 'id="jd-chart-current-amount-range-title"')
        self.assertNotContains(response, "jd-charts--compact is-muted")
        # The charts never name a court; only the deposit preview's readable row does.
        charts = html[compact : html.index("Publicaciones anteriores")]
        self.assertNotIn("Juzgado 7", charts)
        # Department and amount range total the block: 10 · $ 10.045. The
        # comparison sets two publications side by side, so it has no total.
        self.assertEqual(html.count("Total 10 · $ 10.045"), 2)
        # Role cards for the latest publication only (the history adds 1.000.000).
        self.assertLess(html.index("10 depósitos · $ 10.045"), compact)

    def test_current_publication_charts_muted_once_expired(self):
        self._current_with_findings(10)
        response = self._request(today=date(2026, 11, 18))
        self.assertContains(response, "jd-charts jd-charts--compact is-muted")


class InsightsTests(TestCase):
    def _deposits(self):
        accounts = [f"{code}0012003001" for code in DANE_SAMPLE]
        deposits = [
            _deposit(
                "2025-1",
                1_000 * (i + 1),
                court_office="Juz 001 Civil Municipal",
                court_account=account,
            )
            for i, account in enumerate(accounts)
        ]
        deposits += [
            _deposit("2026-2", 500_000, court_office=None, court_account=None),
            _deposit("2026-2", 5_000_000, court_office="Cuenta Judicial Seccional Cali"),
            _deposit(None, 150_000_000, court_office="Juz 002 Laboral Circuito"),
        ]
        return deposits

    def _assert_partition(self, chart, deposits):
        self.assertEqual(chart.total_count, len(deposits))
        self.assertEqual(chart.total_amount_cop, sum(d.amount_cop for d in deposits))

    def test_every_chart_adds_up_to_the_history_totals(self):
        deposits = self._deposits()
        charts = insights.history_charts(deposits, PERIODS, "2026-2")
        self.assertEqual(len(charts), 3)
        for chart in charts:
            self._assert_partition(chart, deposits)

    def test_history_and_current_charts_share_one_order(self):
        deposits = self._deposits()
        history = [c.slug for c in insights.history_charts(deposits, PERIODS, "2026-2")]
        current_charts = insights.current_publication_charts(deposits, PERIODS, "2025-1")
        current = [c.slug for c in current_charts]
        # Time first, then department, then amount range — in both blocks.
        self.assertEqual(history, ["period", "department", "amount-range"])
        self.assertEqual(current, ["previous-period", "department", "amount-range"])

    def test_comparison_chart_has_no_total(self):
        chart = insights.by_previous_period(self._deposits(), PERIODS, "2026-2")
        self.assertFalse(chart.has_total)
        self.assertTrue(insights.by_department(self._deposits()).has_total)

    def test_period_chart_keeps_empty_publications(self):
        chart = insights.by_period(self._deposits(), PERIODS, "2026-2")
        self.assertEqual([bar.label for bar in chart.bars], [*PERIODS, "Sin dato"])
        self.assertEqual([bar.count for bar in chart.bars], [0, 12, 0, 2, 1])
        self.assertEqual([bar.label for bar in chart.bars if bar.highlight], ["2026-2"])
        self.assertEqual(chart.summary, "Aparece en 2 de 4 publicaciones")

    def test_threshold(self):
        self.assertIsNone(insights.history_charts(self._deposits()[:9], PERIODS, "2026-2"))
        self.assertIsNotNone(insights.history_charts(self._deposits()[:10], PERIODS, "2026-2"))
        with override_settings(JD_CHARTS_MIN_FINDINGS=20):
            self.assertIsNone(insights.history_charts(self._deposits(), PERIODS, "2026-2"))

    def test_department_top_ten_then_others_then_no_data(self):
        chart = insights.by_department(self._deposits())
        labels = [bar.label for bar in chart.bars]
        self.assertEqual(len(labels), 12)
        self.assertEqual(labels[-2:], ["Otros", "Sin dato"])
        # Ranked by amount: the largest account (last in DANE_SAMPLE) first.
        self.assertEqual(labels[0], "Vichada")
        others = chart.bars[-2]
        self.assertEqual((others.count, others.amount_cop), (2, 3_000))
        no_data = chart.bars[-1]
        self.assertEqual((no_data.count, no_data.amount_cop), (3, 155_500_000))

    def test_current_publication_charts_reuse_the_history_aggregations(self):
        deposits = self._deposits()
        current = [d for d in deposits if d.period == "2025-1"]
        charts = insights.current_publication_charts(deposits, PERIODS, "2025-1")
        self.assertEqual(
            [chart.slug for chart in charts],
            ["previous-period", "department", "amount-range"],
        )
        self.assertEqual(charts[1], insights.by_department(current))
        self.assertEqual(charts[2], insights.by_amount_range(current))
        for chart in charts[1:]:
            self._assert_partition(chart, current)
        # The threshold counts the latest publication, not the whole history.
        self.assertIsNone(insights.current_publication_charts(deposits, PERIODS, "2026-2"))

    def test_previous_period_comparison(self):
        deposits = [_deposit("2025-2", 1_000) for _ in range(4)] + [
            _deposit("2026-2", 1_500),
            _deposit("2026-2", 1_500),
            _deposit("2025-1", 99),
        ]
        chart = insights.by_previous_period(deposits, PERIODS, "2026-2")
        self.assertEqual(
            [(bar.label, bar.count, bar.amount_cop, bar.highlight) for bar in chart.bars],
            [("2025-2", 4, 4_000, False), ("2026-2", 2, 3_000, True)],
        )
        self.assertEqual(chart.summary, _comparison("2025-2", "−25,0", "−50,0"))
        absent = insights.by_previous_period(deposits[4:], PERIODS, "2026-2")
        self.assertEqual(absent.summary, "No aparecía en 2025-2")
        self.assertEqual(absent.bars[0].count, 0)
        self.assertIsNone(insights.by_previous_period(deposits, PERIODS, "2017-1"))

    def test_amount_ranges(self):
        chart = insights.by_amount_range(
            [_deposit("2025-1", amount) for amount in (999_999, 1_000_000, 10_000_000, 100_000_000)]
        )
        self.assertEqual([bar.count for bar in chart.bars], [1, 1, 1, 1])
        self.assertEqual(
            [bar.label for bar in chart.bars], ["< $1M", "$1M–$10M", "$10M–$100M", "≥ $100M"]
        )

    def test_department_classifier(self):
        self.assertEqual(insights.department("110012041004"), "Bogotá D.C.")
        self.assertEqual(insights.department("760012051005"), "Valle del Cauca")
        self.assertEqual(insights.department("460012051005"), "Sin dato")
        self.assertEqual(insights.department(None), "Sin dato")

    def test_short_cop_and_ticks(self):
        self.assertEqual(cop_short(1_234_567_890), "$1,2 mil M")
        self.assertEqual(cop_short(972_197_496), "$972 M")
        self.assertEqual(cop_short(5_000_000), "$5 M")
        self.assertEqual(cop_short(45_500), "$45,5 mil")
        self.assertEqual(axis_ticks(1642), [0, 500, 1000, 1500, 2000])


# DANE codes of 12 distinct departments — the top 10 plus two that fold into
# "Otros" — in increasing amount order (see InsightsTests._deposits).
DANE_SAMPLE = ["05", "08", "11", "13", "15", "17", "18", "19", "20", "23", "25", "99"]


class CorpusStatsTests(TestCase):
    SLICES = [
        corpus_stats.Slice("2019", "11", "< $1M", 3, 900_000),
        corpus_stats.Slice("2018", "05", "$1M–$10M", 2, 5_000_000),
        corpus_stats.Slice("2018", None, "≥ $100M", 1, 200_000_000),
        corpus_stats.Slice(None, "46", "< $1M", 4, 100_000),
        corpus_stats.Slice("2019", "11", "Sin dato", 1, 0),
    ]

    def test_every_chart_partitions_the_corpus(self):
        charts = corpus_stats.charts(self.SLICES)
        self.assertEqual(
            [chart.slug for chart in charts],
            ["year-count", "year-amount", "department", "amount-range"],
        )
        for chart in charts:
            self.assertEqual((chart.total_count, chart.total_amount_cop), (11, 206_000_000))

    def test_years_ascend_and_missing_data_closes_every_list(self):
        year_count, year_amount, department, amount_range = corpus_stats.charts(self.SLICES)
        self.assertEqual([bar.label for bar in year_count.bars], ["2018", "2019", "Sin dato"])
        self.assertEqual(year_count.bars, year_amount.bars)
        self.assertEqual((year_count.measure, year_amount.measure), ("count", "amount"))
        # Unknown DANE code ("46") and no court account both fall to "Sin dato".
        self.assertEqual(
            [(bar.label, bar.count) for bar in department.bars],
            [("Antioquia", 2), ("Bogotá D.C.", 4), ("Sin dato", 5)],
        )
        self.assertEqual(
            [bar.label for bar in amount_range.bars],
            [label for label, _, _ in insights.AMOUNT_RANGES] + ["Sin dato"],
        )

    def test_amount_range_sql_matches_python_classifier(self):
        case, params = corpus_stats._amount_range_sql()
        con = duckdb.connect()
        for amount in (-5, 0, 999_999, 1_000_000, 9_999_999, 10_000_000, 100_000_000, 10**12, None):
            (label,) = con.execute(
                f"SELECT {case} FROM (SELECT ?::BIGINT AS amount_cop) c", [*params, amount]
            ).fetchone()
            expected = "Sin dato" if amount is None else insights.amount_range(amount)
            self.assertEqual(label, expected, amount)


class FakeS3:
    """Just the calls `core_cache.sync` makes, over an in-memory bucket."""

    def __init__(self, objects):
        self.objects = objects  # key -> (etag, bytes)
        self.downloads = []

    def head_object(self, Bucket, Key):
        return {"ETag": self.objects[Key][0]}

    def get_paginator(self, _name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key, "ETag": etag}
                        for key, (etag, _) in objects.items()
                        if key.startswith(Prefix)
                    ]
                }

        return Paginator()

    def download_file(self, bucket, key, filename):
        self.downloads.append(key)
        Path(filename).write_bytes(self.objects[key][1])


class IncrementalSyncTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name)
        self.s3 = FakeS3(
            {
                core_cache.core_key(table): ('"v1"', table.encode())
                for table in core_cache.CORE_TABLES
            }
            | {core_cache.ENRICHMENT_PREFIX + "batch1.parquet": ('"e1"', b"e1")}
        )

    def _sync(self):
        with (
            override_settings(CORE_CACHE_DIR=self.cache, CLAIMS_ENGINE_BUCKET="bucket"),
            mock.patch("boto3.client", return_value=self.s3),
        ):
            return core_cache.sync()

    def test_unchanged_objects_are_not_downloaded_again(self):
        self.assertEqual(self._sync(), len(core_cache.CORE_TABLES) + 1)
        self.s3.downloads.clear()
        self.assertEqual(self._sync(), 0)
        self.assertEqual(self.s3.downloads, [])

    def test_only_changed_objects_are_downloaded(self):
        self._sync()
        self.s3.downloads.clear()
        claim_key = core_cache.core_key("claim")
        self.s3.objects[claim_key] = ('"v2"', b"claim v2")
        self.assertEqual(self._sync(), 1)
        self.assertEqual(self.s3.downloads, [claim_key])
        self.assertEqual((self.cache / "claim.parquet").read_bytes(), b"claim v2")

    def test_removed_enrichment_batch_is_dropped(self):
        self._sync()
        del self.s3.objects[core_cache.ENRICHMENT_PREFIX + "batch1.parquet"]
        self._sync()
        self.assertEqual(list((self.cache / "enrichment").iterdir()), [])


class SyncCommandTests(TestCase):
    def _run(self, *args):
        with (
            mock.patch.object(core_cache, "sync", return_value=0),
            mock.patch.object(corpus_stats, "write_slices", return_value=1) as write_slices,
        ):
            call_command("sync_core_cache", *args, stdout=io.StringIO())
        return write_slices

    def test_hourly_sync_never_computes_statistics(self):
        # Next to the web workers it ran the 1 GB instance out of memory.
        self._run().assert_not_called()

    def test_startup_sync_computes_statistics(self):
        self._run("--corpus-stats").assert_called_once()


@skipUnless(core_cache.is_synced(), "local core cache not synced")
class RealCacheTests(TestCase):
    """Acceptance figures against the real local cache."""

    def test_search_flags_first_appearance(self):
        # 901256684 appears only in the latest publication; 860051894 in all.
        self.assertTrue(radar.search("901256684").extra["first_appearance"])
        self.assertFalse(radar.search("860051894").extra["first_appearance"])

    def test_published_periods_skip_publications_without_deposits(self):
        # 2017-1 is in core/file but excluded from claim identity: listing it
        # would show every party a false zero in the per-publication chart.
        periods = party_search.published_periods()
        self.assertNotIn("2017-1", periods)
        self.assertEqual(periods[0], "2018-1")

    def test_landing_statistics_add_up_to_the_corpus_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_file = Path(tmp) / "corpus_stats.json"
            with mock.patch.object(corpus_stats, "stats_path", return_value=stats_file):
                self.assertGreater(corpus_stats.write_slices(), 0)
                response = self.client.get("/depositos-judiciales/")
        html = response.content.decode()
        self.assertNotIn('class="proof"', html)
        self.assertLess(html.index("Registros encontrados"), html.index('id="estadisticas"'))
        self.assertLess(html.index('id="estadisticas"'), html.index('id="demostracion"'))
        self.assertEqual(html.count('<details class="jd-chart jd-chart--'), 4)
        # Only the first chart starts open; the rest are collapsed.
        self.assertEqual(html.count('<details class="jd-chart jd-chart--vertical" open>'), 1)
        self.assertEqual(html.count("open>"), 1)
        total = cop(party_search.total_claim_amount_cop())
        self.assertEqual(html.count(f'<td class="mono">{total}</td>'), 4)

    def test_890300279_figures(self):
        ClaimWindow.objects.create(
            period="2026-2", opens_on=date(2026, 10, 19), closes_on=date(2026, 11, 17)
        )
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 8)):
            response = self.client.get("/resultados/?nit=890300279")
        self.assertContains(response, "7.980 · $ 3.701.871.805")
        self.assertContains(response, "320 · $ 232.457.445")
        self.assertContains(
            response,
            "Hasta el 17/11/2026 "
            '<span class="results-deadline-left">(quedan 6 días hábiles)</span>',
        )

    def test_890300279_detail_page(self):
        ClaimWindow.objects.create(
            period="2026-2", opens_on=date(2026, 10, 19), closes_on=date(2026, 11, 17)
        )
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 8)):
            response = self.client.get(DETAIL_URL)
        html = response.content.decode()
        self.assertLess(
            html.index("Última publicación · 2026-2"), html.index("Publicaciones anteriores")
        )
        self.assertContains(response, '<div class="jd-summary-num mono">320</div>')
        self.assertContains(response, '<div class="jd-summary-num mono">$ 232.457.445</div>')
        # The same 6 business days as /resultados/.
        self.assertContains(
            response,
            "Plazo de reclamo hasta el <strong>17/11/2026</strong>"
            '<span class="jd-deadline-sep"> · </span>'
            '<span class="jd-deadline-left">quedan 6 días hábiles</span>',
        )
        # "Publicaciones anteriores" leaves out the latest publication's 320.
        self.assertContains(response, '<div class="jd-summary-num mono">7.660</div>')
        self.assertContains(response, '<div class="jd-summary-num mono">$ 3.469.414.360</div>')
        self.assertNotContains(response, "publicaciones anteriores, desde")
        self.assertContains(response, "BANCO DE OCCIDENTE</h2>")
        # Every chart's table totals the history.
        self.assertEqual(html.count('<td class="mono">7.660</td>'), 3)
        self.assertEqual(html.count('<td class="mono">$ 3.469.414.360</td>'), 3)

    def test_890903938_current_publication_charts(self):
        ClaimWindow.objects.create(
            period="2026-2", opens_on=date(2026, 10, 19), closes_on=date(2026, 11, 17)
        )
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 8)):
            response = self.client.get("/depositos-judiciales/resultado/?nit=890903938")
        html = response.content.decode()
        block = html[
            html.index('class="jd-block jd-block--current') : html.index("jd-block--history")
        ]
        self.assertIn('<div class="jd-summary-num mono">373</div>', block)
        self.assertIn('<div class="jd-summary-num mono">$ 456.144.596</div>', block)
        self.assertIn("jd-charts jd-charts--compact", block)
        # Each compact chart's data-table total is the block total.
        self.assertEqual(block.count("Total 373 · $ 456.144.596"), 2)
        # ... plus the comparison chart's 2026-2 row.
        self.assertEqual(block.count('<td class="mono">373</td>'), 3)
        self.assertEqual(block.count('<td class="mono">$ 456.144.596</td>'), 3)
        self.assertIn(_comparison("2026-1", "−26,9", "−81,9"), block)
        self.assertIn("Como demandante", block)
        self.assertIn("Como demandado", block)


class PreviewTests(TestCase):
    def _deposit(self, amount, number="460010001838272", account="680012041802"):
        return _deposit("2026-2", amount, court_account=account)

    def test_mask_digits(self):
        self.assertEqual(preview.mask_digits("460010001838272", 5), "46001••••••••••")
        self.assertEqual(preview.mask_digits(None, 5), "—")

    def test_court_display_name(self):
        self.assertEqual(
            preview.court_display_name("253074004003-JUZ 003 PENAL MUNICIPAL GIRARDOT"),
            "Juz 003 Penal Municipal Girardot",
        )
        self.assertEqual(
            preview.court_display_name("8 Juz 008 Civil Circuito de Medellin"),
            "Juz 008 Civil Circuito de Medellin",
        )
        self.assertEqual(preview.court_display_name(None), "Despacho sin nombre")

    def test_single_deposit_has_no_faded_rows(self):
        built = preview.build_preview([self._deposit(500)])
        self.assertEqual(built.faded, [])
        self.assertEqual(built.remaining_count, 0)

    def test_at_most_three_faded_rows(self):
        built = preview.build_preview([self._deposit(amount) for amount in range(1, 7)])
        self.assertEqual(built.visible.amount, "$ 6")
        self.assertEqual(len(built.faded), 3)
        self.assertEqual(built.remaining_count, 5)
        self.assertEqual(built.remaining_amount_cop, 15)
        self.assertTrue(all("•" in row.amount for row in built.faded))


class HistoryListTests(TestCase):
    def test_publication_sample_is_the_five_largest(self):
        deposits = [_deposit("2025-1", amount) for amount in range(1, 26)]
        sample = history.publication_sample(deposits, "2025-1")
        self.assertEqual([row.amount_cop for row in sample], [25, 24, 23, 22, 21])
        small = history.publication_sample(deposits[:2], "2025-1")
        self.assertEqual(len(small), 2)

    def test_city_display_name(self):
        for raw in ("Bogota", "BOGOTA", "Bogotá, D.C.", "Bogotá D.C"):
            self.assertEqual(preview.city_display_name(raw), "Bogotá D.C.")
        self.assertEqual(preview.city_display_name("PEREIRA"), "Pereira")
        self.assertEqual(preview.city_display_name("Florencia."), "Florencia")
