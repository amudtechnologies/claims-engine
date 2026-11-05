"""Server-side HTML allowlist for editor output. The WYSIWYG widget is a
convenience, not a trust boundary: whatever it (or a crafted POST) submits
is cleaned here before it is stored, so rendering `body` with `|safe` is
safe regardless of which editor produced it."""

import nh3

ALLOWED_TAGS = {
    "p", "br", "hr", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "strike",
    "ul", "ol", "li", "blockquote", "a", "img", "figure", "figcaption",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "code", "pre",
    "span", "div", "sub", "sup",
}  # fmt: skip

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "th": {"colspan", "rowspan", "scope", "style"},
    "td": {"colspan", "rowspan", "style"},
    "span": {"style"},
    "p": {"style"},
    "div": {"style"},
    "h2": {"style"},
    "h3": {"style"},
    "h4": {"style"},
    "li": {"style"},
}

# Only alignment/emphasis styles are meaningful from the editor; everything
# else (position, background:url(...), etc.) is dropped.
ALLOWED_CSS_PROPERTIES = {"text-align", "font-weight", "font-style", "text-decoration"}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel"}


def sanitize_html(html: str) -> str:
    return nh3.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        filter_style_properties=ALLOWED_CSS_PROPERTIES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
