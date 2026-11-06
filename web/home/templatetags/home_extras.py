from django import template

register = template.Library()


@register.filter
def cop(amount: int) -> str:
    """Integer COP formatted with Colombian thousands separators, e.g. $ 84.500.000."""
    return f"$ {amount:,}".replace(",", ".")


@register.filter
def es_co_number(value, decimals: int = 0) -> str:
    """Formats a number the same way counter.js's `toLocaleString("es-CO", ...)`
    does — "." as the thousands separator, "," as the decimal separator — so the
    server-rendered stat (what a crawler or no-JS visitor sees) matches the
    animated value counter.js counts up to, instead of the placeholder "0" the
    animation used to start from (see the SEO report this fixes)."""
    formatted = f"{float(value):,.{int(decimals)}f}"
    return formatted.translate(str.maketrans(",.", ".,"))


_DOCUMENT_TYPE_LABELS = {
    "legal_entity": "Persona jurídica",
    "natural_person": "Persona natural",
}


@register.filter
def document_type_label(document_type: str | None) -> str:
    if document_type is None:
        return "Sin clasificar"
    return _DOCUMENT_TYPE_LABELS.get(document_type, document_type)


_DOCUMENT_NUMBER_LABELS = {
    "legal_entity": "NIT",
    "natural_person": "Cédula",
}


@register.filter
def document_number_label(document_type: str | None) -> str:
    """The field label for a party's document number — "NIT" or "Cédula"
    depending on `document_type`. A RUES miss (`document_type is None`) is a
    permanent-valid unknown state (D26), not evidence of either category, so
    it falls back to the generic "Identificación" rather than guessing."""
    if document_type is None:
        return "Identificación"
    return _DOCUMENT_NUMBER_LABELS.get(document_type, "Identificación")
