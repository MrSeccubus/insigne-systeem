"""Render eis text (markdown with ``==…==`` green highlights) to inline HTML.

Shared between the web layer (``api/templates.py``) and outbound e-mail
(``lib/insigne/email.py``) so both surfaces format eis text identically.
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
