"""Shared helpers for parsing HTML-route query parameters leniently.

Browsers and chat apps sometimes include trailing punctuation when extracting a
URL from surrounding text. ``https://…/badges/knopen?niveau=1)`` written inside
parentheses gets pulled out *with* the closing paren attached, producing a
422 from FastAPI's default int parser. These helpers parse such values
forgivingly so HTML pages still render.

JSON API endpoints intentionally keep strict typing — bad input there should
surface as a 422 the way callers expect.
"""


def lenient_int(value: str | None) -> int | None:
    """Parse a query-string value as an int, stripping trailing non-digit junk.

    Returns the leading run of digits as ``int`` when the value starts with a
    digit (after stripping whitespace); ``None`` otherwise. ``None`` and empty
    string also return ``None``.
    """
    if value is None:
        return None
    s = value.strip()
    if not s or not s[0].isdigit():
        return None
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None
