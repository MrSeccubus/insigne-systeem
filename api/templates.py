import html as _html
import os
import re
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from insigne import poster_templates as _poster_templates
from insigne.config import config
from insigne.eis_render import render_eis as _render_eis
from insigne.version import APP_VERSION, get_app_version, get_newer_release

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
_CUSTOM_POLICY = _FRONTEND_DIR / "templates" / "privacy_policy_custom.md"

# System poster base templates live as YAML files in the data dir (not in code).
_poster_templates.set_templates_dir(Path(__file__).parent / "data" / "poster_templates")

_GREEN_RE = re.compile(r"==(.+?)==", re.DOTALL)


_GREEN_OPEN = ""   # private-use sentinels — never appear in eis text
_GREEN_CLOSE = ""


def _render_eis_compact(text: str, groen: bool = False, length: int = 120) -> Markup:
    """Render an eis as a single inline string with markdown stripped.

    Only ``==text==`` highlights survive — they become green spans. If ``groen``
    is True and the text contains no ``==`` markers, the whole result is rendered
    in green. The result is truncated to ``length`` *visible* characters; if the
    cut falls inside an open green span, the span is closed so no orphan markup
    leaks through.
    """
    if not text:
        return Markup("")

    # Convert each matched ==…== pair into balanced sentinels.
    s = re.sub(r"==(.+?)==",
               lambda m: _GREEN_OPEN + m.group(1) + _GREEN_CLOSE,
               text, flags=re.DOTALL)

    # Strip markdown markers (sentinels survive intact).
    s = re.sub(r"(?m)^\s*[\*\-\+]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)
    s = re.sub(r"(?m)^#{1,6}\s+", "", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<![*\w])\*([^\*\n]+?)\*(?![*\w])", r"\1", s)
    s = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)

    s = re.sub(r"\s+", " ", s).strip()

    # Truncate by visible characters (sentinels don't count).
    visible = 0
    out = []
    truncated = False
    for ch in s:
        if ch in (_GREEN_OPEN, _GREEN_CLOSE):
            out.append(ch)
            continue
        if visible >= length:
            truncated = True
            break
        out.append(ch)
        visible += 1
    s = "".join(out)

    if truncated:
        if s.count(_GREEN_OPEN) > s.count(_GREEN_CLOSE):
            s += _GREEN_CLOSE
        s = s.rstrip() + "…"

    if _GREEN_OPEN not in s and groen:
        s = _GREEN_OPEN + s + _GREEN_CLOSE

    escaped = _html.escape(s)
    escaped = escaped.replace(_GREEN_OPEN, '<span class="eis-groen">')
    escaped = escaped.replace(_GREEN_CLOSE, '</span>')
    return Markup(escaped)


def _eis_needs_expand(text: str, length: int = 120) -> bool:
    """Return True if the full eis text differs visibly from the compact rendering.

    Used to decide whether to show a "toon volledige eis" toggle.
    """
    if not text:
        return False
    if "\n" in text.strip():
        return True
    plain = re.sub(r"\s+", " ", text).strip()
    return len(plain) > length


templates = Jinja2Templates(directory=_FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None
templates.env.filters["render_eis"] = _render_eis
templates.env.filters["render_eis_compact"] = _render_eis_compact
templates.env.filters["eis_needs_expand"] = _eis_needs_expand
templates.env.globals["dev"] = os.environ.get("INSIGNE_DEV") == "1"
templates.env.globals["base_url"] = config.base_url
templates.env.globals["allow_any_user_to_create_groups"] = config.allow_any_user_to_create_groups
templates.env.globals["app_version"] = get_app_version
templates.env.globals["privacy_policy_is_default"] = lambda: not _CUSTOM_POLICY.exists()
_mock_release = os.environ.get("INSIGNE_MOCK_NEWER_RELEASE")
templates.env.globals["get_newer_release"] = (lambda: _mock_release) if _mock_release else get_newer_release
