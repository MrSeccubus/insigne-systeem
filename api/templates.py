import os
import re
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from insigne.config import config
from insigne.version import APP_VERSION, get_app_version, get_newer_release

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
_CUSTOM_POLICY = _FRONTEND_DIR / "templates" / "privacy_policy_custom.md"

_GREEN_RE = re.compile(r"==(.+?)==", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _render_eis(text: str) -> Markup:
    """Convert ==...== markers to green <span> and [text](url) to <a>; HTML-escape everything else."""
    escaped = str(escape(text))
    linked = _LINK_RE.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped)
    rendered = _GREEN_RE.sub(r'<span class="eis-groen">\1</span>', linked)
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
