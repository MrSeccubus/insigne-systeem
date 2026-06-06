"""Sandboxed templating for poster text fields (#132).

Poster text fields (title/header/footer/…) may contain ``{{ user.name }}`` /
``{{ date }}`` etc. These are **user-authored** and, for speltak/group posters,
**shared** — so they are rendered through a dedicated
``jinja2.sandbox.SandboxedEnvironment`` with a fixed, tiny context and never the
app's own template environment. Anything the sandbox blocks (attribute escapes,
SSTI probes) or that errors renders to an empty string — inert. The result is
then inserted by the trusted, autoescaped poster body template (defence in
depth), so ``autoescape`` is off here to avoid double-escaping.
"""
from __future__ import annotations

import copy
from datetime import datetime

from jinja2.sandbox import SandboxedEnvironment

from insigne.poster_templates import TEXT_FIELDS

# A single shared sandbox. No globals, no app filters — only what we pass in.
_ENV = SandboxedEnvironment(autoescape=False)
_ENV.globals.clear()


def render_text(source: str, ctx: dict) -> str:
    """Render one user string in the sandbox. No template markers → returned
    as-is. Blocked/broken templates → "" (inert)."""
    if not source or ("{{" not in source and "{%" not in source):
        return source or ""
    try:
        return _ENV.from_string(source).render(**ctx)
    except Exception:
        return ""


def build_context(user, *, now: datetime | None = None) -> dict:
    """The fixed template context: the logged-in user's name + date/time.
    ``user`` is exposed as a plain dict (never the ORM object) so no attributes
    or methods leak into the sandbox. ``lid`` (speltak member) is added by the
    speltak/sign-off poster types in a later phase."""
    now = now or datetime.now()
    name = ""
    if user is not None:
        name = getattr(user, "name", None) or getattr(user, "email", None) or ""
    return {
        "user": {"name": name},
        "date": now.strftime("%d-%m-%Y"),
        "time": now.strftime("%H:%M"),
    }


def render_definition(defn: dict, ctx: dict) -> dict:
    """Return a copy of the definition with its text fields template-rendered."""
    out = copy.deepcopy(defn)
    for field in TEXT_FIELDS:
        if field in out:
            out[field] = render_text(out.get(field, ""), ctx)
    return out
