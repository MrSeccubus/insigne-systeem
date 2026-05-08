import os
import re
from pathlib import Path

import markdown as _markdown_lib
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from insigne.config import config
from insigne.version import APP_VERSION, get_app_version, get_newer_release

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
_CUSTOM_POLICY = _FRONTEND_DIR / "templates" / "privacy_policy_custom.md"

_GREEN_RE = re.compile(r"==(.+?)==", re.DOTALL)
# Markdown requires a blank line before a bullet list.  Insert one when a
# non-list line is immediately followed by a "* " or "- " list item.
_ENSURE_LIST_GAP_RE = re.compile(r"(?m)^([^*\-\n][^\n]*)\n([*\-] )")
_md = _markdown_lib.Markdown(extensions=["nl2br"])


def _render_eis(text: str) -> Markup:
    """Render eis text as markdown; ==...== segments are coloured green."""
    _md.reset()
    processed = _ENSURE_LIST_GAP_RE.sub(r"\1\n\n\2", text)
    html = _md.convert(processed)
    # Normalise block boundaries so the result is inline-friendly
    html = re.sub(r"</p>\s*<p>", "<br><br>", html)   # paragraph gap
    html = re.sub(r"</p>(\s*)<", r"<br>\1<", html)   # </p> before any other block
    html = re.sub(r"(</\w+>)\s*<p>", r"\1<br>", html) # closing block before <p>
    html = re.sub(r"</?p>", "", html.strip())
    # nl2br emits "<br />\n" — collapse to a clean <br>
    html = html.replace("<br />\n", "<br>")
    # Open links in a new tab
    html = html.replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')
    # Convert ==...== to green spans
    rendered = _GREEN_RE.sub(r'<span class="eis-groen">\1</span>', html)
    return Markup(rendered)


templates = Jinja2Templates(directory=_FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None
templates.env.filters["render_eis"] = _render_eis
templates.env.globals["dev"] = os.environ.get("INSIGNE_DEV") == "1"
templates.env.globals["allow_any_user_to_create_groups"] = config.allow_any_user_to_create_groups
templates.env.globals["app_version"] = get_app_version
templates.env.globals["privacy_policy_is_default"] = lambda: not _CUSTOM_POLICY.exists()
_mock_release = os.environ.get("INSIGNE_MOCK_NEWER_RELEASE")
templates.env.globals["get_newer_release"] = (lambda: _mock_release) if _mock_release else get_newer_release
