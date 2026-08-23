from django import template

register = template.Library()


@register.filter
def cop(amount: int) -> str:
    """Integer COP formatted with Colombian thousands separators, e.g. $ 84.500.000."""
    return f"$ {amount:,}".replace(",", ".")


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
