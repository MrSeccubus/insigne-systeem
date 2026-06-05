"""Poster designer constants + the system base templates (#132).

Three poster types, the supported paper sizes (full A-series), and the
per-type **base templates** a user loads and then customizes. Kept in code (not
the DB) so they're always available as a starting point. Phase 1 only renders
the *chrome* (title/subtitle/header/footer/group/speltak + font sizes) plus a
placeholder body; later phases add the type-specific body params to ``params``.
"""
from __future__ import annotations

import copy

# Poster types: key → human label (Dutch).
POSTER_TYPES: dict[str, str] = {
    "badges": "Insigneposter",
    "speltak": "Speltak-overzicht",
    "signoff": "Aftekenposter",
}

# Paper sizes in mm as (width, height) **portrait**. A2/A1/A0 are NOT valid CSS
# ``@page { size: … }`` keywords (only up to A3), so we always emit explicit mm.
PAPER_SIZES_MM: dict[str, tuple[int, int]] = {
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
    "A0": (841, 1189),
}

ORIENTATIONS = ("portrait", "landscape")

# Default page margin (mm) used by the print/preview @page rule.
PAGE_MARGIN_MM = 12

# Chrome params shared by every poster type, with their defaults and the
# coercion applied when reading them from a form/query string. The keys here are
# the single source of truth used by the service, the render route, and the
# designer's Alpine model.
CHROME_PARAMS: dict[str, object] = {
    "title": "",
    "subtitle": "",
    "header": "",
    "footer": "",
    "group_name": "",
    "speltak_name": "",
    "title_font_pt": 48,
    "subtitle_font_pt": 24,
    "body_font_pt": 12,
    # Placeholder-only (Phase 1): number of demo blocks so multi-page pagination
    # can be exercised before the real poster bodies exist (Phases 2–4).
    "demo_blocks": 12,
}

_INT_PARAMS = {"title_font_pt", "subtitle_font_pt", "body_font_pt", "demo_blocks"}


def page_dimensions_mm(paper_size: str, orientation: str) -> tuple[int, int]:
    """Return (width_mm, height_mm) for a paper size + orientation."""
    w, h = PAPER_SIZES_MM.get(paper_size, PAPER_SIZES_MM["A4"])
    if orientation == "landscape":
        return (h, w)
    return (w, h)


def parse_params(mapping) -> dict:
    """Extract the known chrome params from a form/query mapping, coercing ints
    and falling back to defaults. Unknown keys are ignored (so a crafted query
    string can't inject arbitrary params)."""
    out: dict = {}
    for key, default in CHROME_PARAMS.items():
        raw = mapping.get(key)
        if raw is None or raw == "":
            out[key] = default
            continue
        if key in _INT_PARAMS:
            try:
                out[key] = max(0, int(float(raw)))
            except (TypeError, ValueError):
                out[key] = default
        else:
            out[key] = str(raw)
    return out


# The three system base templates. ``params`` starts from the chrome defaults
# with a sensible title; later phases extend the per-type params.
_BASE_TEMPLATES: dict[str, dict] = {
    "badges": {
        "poster_type": "badges",
        "paper_size": "A3",
        "orientation": "portrait",
        "params": {**CHROME_PARAMS, "title": "Insignes"},
    },
    "speltak": {
        "poster_type": "speltak",
        "paper_size": "A3",
        "orientation": "landscape",
        "params": {**CHROME_PARAMS, "title": "Speltak-overzicht"},
    },
    "signoff": {
        "poster_type": "signoff",
        "paper_size": "A4",
        "orientation": "portrait",
        "params": {**CHROME_PARAMS, "title": "Aftekenlijst"},
    },
}


def base_template(poster_type: str) -> dict:
    """Return a deep copy of the base template for a poster type (defaults to
    the badge poster for an unknown type)."""
    spec = _BASE_TEMPLATES.get(poster_type) or _BASE_TEMPLATES["badges"]
    return copy.deepcopy(spec)
