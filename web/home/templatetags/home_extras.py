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


NAME_MASK = "•••"
# Letters of each word a natural person's name keeps in clear.
NAME_VISIBLE = 2


@register.filter
def party_display_name(name: str | None, document_type: str | None) -> str:
    """A party's name as the page may show it. A natural person's name keeps
    each word's first two letters and nothing more: «JUAN PÉREZ GÓMEZ» →
    «JU••• PÉ••• GÓ•••» (fixed-length mask, so word lengths don't leak either). Masked here,
    server-side, so the full name never reaches the browser. Any other
    party's name, unclassified ones included, is shown as is."""
    if not name:
        return ""
    if document_type != "natural_person":
        return name
    return " ".join(word[:NAME_VISIBLE] + NAME_MASK for word in name.split())


# Leading digits a natural person's amounts keep in clear.
AMOUNT_VISIBLE = 2


def mask_cop(amount: int, visible: int = AMOUNT_VISIBLE) -> str:
    """`cop` with only the first `visible` digits in clear, separators kept:
    "$ 36.161.788" -> "$ 36.•••.•••", "$ 3.332.332" -> "$ 3.3••.•••"."""
    shown = 0
    out = []
    for character in cop(amount):
        if character.isdigit():
            out.append(character if shown < visible else "•")
            shown += 1
        else:
            out.append(character)
    return "".join(out)


@register.filter
def cop_for(amount: int, masked: bool) -> str:
    """`cop`, or `mask_cop` on a natural person's page (`masked`)."""
    return mask_cop(amount) if masked else cop(amount)


@register.filter
def cop_for_type(amount: int, document_type: str | None) -> str:
    """`cop_for` keyed by the party's document type, for templates that have
    the type but no `mask_amounts` flag (the /resultados/ rows)."""
    return cop_for(amount, document_type == "natural_person")
