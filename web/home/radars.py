"""The contract between the site shell (`home`) and the radars.

Each radar is its own Django app and owns everything about itself — landing
page, detail pages, search implementation, templates, styles, admin, tests.
It plugs into the shell by registering a `RadarSpec` from its
`AppConfig.ready()`. The shell only aggregates: the `/radares/` index and the
consolidated `/resultados/` page, which asks every available radar to search
the document number and renders each radar's own results row.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.template.defaultfilters import slugify


@dataclass(frozen=True)
class RadarMatch:
    """What one radar found for one document number."""

    document_number: str
    party_name: str | None
    source_declared_name: str | None
    document_type: str | None
    rues_active: bool | None
    finding_count: int
    total_amount_cop: int
    detail_url: str
    # True when the radar considers the finding still actionable (e.g. its
    # claim window is open); drives the shared "what to do next" copy.
    actionable: bool = False
    # Radar-specific data for that radar's own results-row template.
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RadarSpec:
    slug: str
    name: str
    problem: str
    identifies: str
    audience: str
    landing_url_name: str
    # Partial rendered once per match on /resultados/, with `spec` and `match`.
    results_row_template: str
    search: Callable[[str], RadarMatch | None]
    is_available: Callable[[], bool] = lambda: True
    # Optional real figures for the /radares/ card: [(value, label), ...].
    card_stats: Callable[[], list[tuple[str, str]]] | None = None
    # Optional partial rendered inside the radar's /radares/ card, and the
    # stylesheet (static path) the shell loads on that page to style it.
    card_template: str | None = None
    stylesheet: str | None = None
    status: str = "active"  # "active" | "in_development"
    cta_label: str = "Conocer el radar"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def status_label(self) -> str:
        return "Activo" if self.is_active else "En desarrollo"


_REGISTRY: dict[str, RadarSpec] = {}


def register(spec: RadarSpec) -> None:
    if spec.slug != slugify(spec.slug):
        raise ValueError(f"Radar slug {spec.slug!r} is not a valid slug")
    _REGISTRY[spec.slug] = spec


def all_radars() -> list[RadarSpec]:
    """Active radars first, then those in development; each group by name."""
    return sorted(_REGISTRY.values(), key=lambda r: (not r.is_active, r.name))
