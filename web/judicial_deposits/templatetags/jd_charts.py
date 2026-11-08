"""Presentation for `insights.Chart`: es-CO short amounts for axes and bar
labels, and the geometry (bar lengths, axis ticks as percentages) the chart
partial lays out in plain HTML/CSS. No aggregation happens here — the
totals arrive already computed by `insights`."""

import math

from django import template
from home.templatetags.home_extras import cop, es_co_number

register = template.Library()

# (threshold, divisor, suffix), largest first — "$1,2 mil M", "$850 M", ...
_COP_SCALES = [
    (1_000_000_000_000, 1_000_000_000_000, " billones"),
    (1_000_000_000, 1_000_000_000, " mil M"),
    (1_000_000, 1_000_000, " M"),
    (1_000, 1_000, " mil"),
]


def _short(value: float) -> str:
    decimals = 0 if value >= 100 or float(value).is_integer() else 1
    formatted = es_co_number(value, decimals)
    return formatted[:-2] if formatted.endswith(",0") else formatted


@register.filter
def cop_short(amount: int) -> str:
    """Integer COP abbreviated for an axis or a bar label: 1_234_567_890 →
    "$1,2 mil M", 850_000_000 → "$850 M", 45_000 → "$45 mil"."""
    for threshold, divisor, suffix in _COP_SCALES:
        if abs(amount) >= threshold:
            return f"${_short(amount / divisor)}{suffix}"
    return f"${es_co_number(amount)}"


def _nice_step(maximum: float, target_ticks: int) -> float:
    raw = maximum / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiplier in (1, 2, 2.5, 5, 10):
        if raw <= multiplier * magnitude:
            return multiplier * magnitude
    return 10 * magnitude


def axis_ticks(maximum: int, target_ticks: int = 4) -> list[int]:
    """Round tick values from 0 to the first tick at or above `maximum`."""
    if maximum <= 0:
        return [0, 1]
    step = _nice_step(maximum, target_ticks)
    if step < 1:
        step = 1
    top = math.ceil(maximum / step) * step
    return [round(i * step) for i in range(int(round(top / step)) + 1)]


def _pct(value: int, top: int) -> str:
    # A string, not a float: the template would localize 12.5 as "12,5",
    # which is invalid inside a CSS length.
    return f"{value / top * 100:.2f}"


@register.simple_tag
def chart_layout(chart) -> dict:
    """Bars with their length as a percentage of the axis maximum, and the
    axis ticks, for one `insights.Chart`."""
    amount = chart.measure == "amount"
    values = [bar.amount_cop if amount else bar.count for bar in chart.bars]
    # A horizontal chart's axis shares its row with labels and values: fewer
    # ticks, or "$750 M" and "$1 mil M" run into each other.
    ticks = axis_ticks(max(values, default=0), 4 if chart.orientation == "vertical" else 2)
    top = ticks[-1]
    return {
        "bars": [
            {"bar": bar, "pct": _pct(value, top)}
            for bar, value in zip(chart.bars, values, strict=True)
        ],
        "ticks": [
            {
                "label": cop_short(tick) if amount else es_co_number(tick),
                "pct": _pct(tick, top),
            }
            for tick in ticks
        ],
        "measure_label": "valor" if amount else "cantidad de depósitos",
        "total_label": f"{es_co_number(chart.total_count)} · {cop(chart.total_amount_cop)}",
    }
