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
_md = _markdown_lib.Markdown(extensions=["nl2br"])


def _render_eis(text: str) -> Markup:
    """Render eis text as markdown; ==...== segments are coloured green."""
    _md.reset()
    html = _md.convert(text)
    # Strip paragraph wrappers; separate multiple paragraphs with a single break
    html = re.sub(r"</p>\s*<p>", "<br>", html)
    html = re.sub(r"^<p>|</p>$", "", html.strip())
    # nl2br emits "<br />\n" — collapse to a clean <br> so whitespace-mode never matters
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
