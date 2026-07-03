"""Render eis text (markdown with ``==…==`` green highlights) to inline HTML.

Shared between the web layer (``api/templates.py``) and outbound e-mail
(``lib/insigne/email.py``) so both surfaces format eis text identically.

SECURITY — this renderer does NOT sanitize HTML. python-markdown passes raw
HTML in the source straight through (the catalogue deliberately uses e.g.
``<u>…</u>``), and the result is wrapped in ``Markup`` so Jinja2 renders it
unescaped. That is safe *only* because the input is trusted, developer-authored
catalogue YAML (``api/data/badges/*.yml``) that is not writable through any web
route.

If eis/poster/badge text ever becomes editable through the app (e.g. the
poster designer, #132), piping that user input through here would be a
stored-XSS sink. Before that ships, add an allowlist HTML sanitizer to the
output — keep the tags the catalogue/markdown actually use (``u``, ``a`` with
its target/rel, ``span class="eis-groen"``, ``strong``/``em``, ``ul``/``ol``/
``li``, ``br``) and drop everything else plus ``javascript:``/``data:`` hrefs —
rather than escaping raw HTML wholesale (which would break the existing
``<u>`` formatting). Do NOT feed user-controlled text through ``render_eis``
until then.
"""
import re

import markdown as _markdown_lib
from markupsafe import Markup

_GREEN_RE = re.compile(r"==(.+?)==", re.DOTALL)

# Markdown requires a blank line before a list. Insert one when a non-list,
# non-indented line is immediately followed by any list item.
_ENSURE_LIST_GAP_RE = re.compile(r"(?m)^([^ \t*\-\n][^\n]*)\n( *(?:[*\-]|\d+\.) )")

_md = _markdown_lib.Markdown(extensions=["nl2br"])


def render_eis(text: str) -> Markup:
    """Render eis text as inline-friendly HTML.

    ``==…==`` segments become ``<span class="eis-groen">…</span>`` for the web
    UI; the e-mail layer maps ``.eis-groen`` to an inline green color via its
    own template wrapper.
    """
    if not text:
        return Markup("")
    _md.reset()
    processed = _ENSURE_LIST_GAP_RE.sub(r"\1\n\n\2", text)
    html = _md.convert(processed)
    html = re.sub(r"</p>\s*<p>", "<br><br>", html)
    html = re.sub(r"</p>(\s*)<", r"<br>\1<", html)
    html = re.sub(r"(</\w+>)\s*<p>", r"\1", html)
    html = re.sub(r"</?p>", "", html.strip())
    html = html.replace("<br />\n", "<br>")
    html = html.replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')
    rendered = _GREEN_RE.sub(r'<span class="eis-groen">\1</span>', html)
    return Markup(rendered)


def render_eis_email(text: str) -> Markup:
    """Same as :func:`render_eis` but inlines the ``eis-groen`` color so the
    output renders correctly in mail clients that strip ``<style>`` blocks.
    """
    if not text:
        return Markup("")
    html = str(render_eis(text))
    return Markup(html.replace(
        '<span class="eis-groen">',
        '<span style="color:#16a34a;font-weight:600;">',
    ))
