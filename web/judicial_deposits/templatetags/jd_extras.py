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
