"""Poster definition: the canonical YAML document for a poster (#132).

A poster is a self-contained definition (stored as YAML, exportable/importable).
This module owns the type codes, the supported paper sizes, the built-in base
definition per type, and ``normalise()`` — the single validator that allowlists
keys and coerces types so nothing arbitrary reaches the renderer.

Templating of the text fields (``title``/``header``/… may contain ``{{ … }}``)
lives in ``poster_render.py`` (a sandboxed Jinja environment).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# Poster types — numeric code (as stored in the YAML `type:` field) → key/label.
TYPE_CODES: dict[int, str] = {0: "badges", 1: "speltak", 2: "signoff"}
TYPE_LABELS: dict[int, str] = {
    0: "Insigneposter",
    1: "Speltak-overzicht",
    2: "Aftekenposter",
}
KEY_TO_CODE: dict[str, int] = {key: code for code, key in TYPE_CODES.items()}


def code_from_key(key: str, default: int = 0) -> int:
    """Map a string type key ('badges'/'speltak'/'signoff') → numeric code."""
    return KEY_TO_CODE.get(key, default)

# Paper sizes in mm as (width, height) PORTRAIT. A2/A1/A0 are not valid CSS
# `@page { size }` keywords, so we always emit explicit mm.
PAPER_SIZES_MM: dict[str, tuple[int, int]] = {
    "A4": (210, 297), "A3": (297, 420), "A2": (420, 594),
    "A1": (594, 841), "A0": (841, 1189),
}
ORIENTATIONS = ("portrait", "landscape")
PAGE_MARGIN_MM = 8

# Text fields that may contain {{ … }} templates (rendered in poster_render).
TEXT_FIELDS = ("title", "subtitle", "header", "footer", "group_name", "speltak_name")

# An empty badge_block.badges list means "all" — these catalogue categories.
DEFAULT_BADGE_CATEGORIES = ("gewoon", "buitengewoon")


def page_dimensions_mm(paper: str, orientation: str) -> tuple[int, int]:
    w, h = PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A4"])
    return (h, w) if orientation == "landscape" else (w, h)


def type_code(value, default: int = 0) -> int:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return default
    return code if code in TYPE_CODES else default


# ── Coercion helpers ──────────────────────────────────────────────────────────

def _str(v, default: str = "") -> str:
    return default if v is None else str(v)


def _int(v, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def _bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "on", "yes")


# CSS-injection-safe font family: letters/digits/space/comma/hyphen only (no
# quotes/semicolons/braces). Permits stacks like "Times New Roman, serif".
_FONT_FAMILY_RE = re.compile(r"^[a-zA-Z0-9 ,\-]{0,60}$")


def _font_family(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if _FONT_FAMILY_RE.match(s) else ""


def _font_style(raw: dict | None, default_pt: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "font_size_pt": _int(raw.get("font_size_pt"), default_pt, 6, 300),
        "font_family": _font_family(raw.get("font_family")),
        "color": _color(raw.get("color"), ""),   # "" = inherit / element default
    }


def _niveaus(v) -> list[int]:
    """Coerce a niveaus value to a sorted, unique list of valid levels (1–3).
    Accepts a list or a single scalar; falls back to [1]."""
    items = v if isinstance(v, list) else [v]
    out = sorted({n for n in (
        _int(x, 0, 0, 3) for x in items) if n in (1, 2, 3)})
    return out or [1]


# CSS-injection-safe colour: a #hex or a plain named colour only (no chars that
# could break out of a style attribute). Anything else falls back to default.
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$|^[a-z]{1,20}$")

_BG_STYLES = ("none", "solid", "horizontal_gradient", "vertical_gradient")


def _color(v, default: str) -> str:
    s = "" if v is None else str(v).strip()
    return s if _COLOR_RE.match(s) else default


# ── Base templates (loaded from YAML files in the data dir) ───────────────────

# The directory holding the system base templates (<key>.yml). Set by the app
# at startup via set_templates_dir() — the library doesn't assume where the
# app's data dir lives (same pattern as BadgeCatalogue being given its path).
_TEMPLATES_DIR: Path | None = None


def set_templates_dir(path) -> None:
    global _TEMPLATES_DIR
    _TEMPLATES_DIR = Path(path) if path else None


def base_definition(type_code_value: int) -> dict:
    """The wizard's starting definition for a poster type, loaded from
    ``<templates_dir>/<key>.yml`` and normalised. Falls back to a minimal valid
    definition for the type if the dir/file is missing or invalid."""
    code = type_code(type_code_value)
    key = TYPE_CODES[code]
    if _TEMPLATES_DIR is not None:
        path = _TEMPLATES_DIR / f"{key}.yml"
        try:
            return from_yaml(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return normalise({"type": code})


def normalise(defn) -> dict:
    """Validate + coerce an arbitrary parsed definition into the canonical shape.
    Unknown keys are dropped; every known key is present and type-correct."""
    d = defn if isinstance(defn, dict) else {}
    code = type_code(d.get("type"))
    paper = d.get("paper") if d.get("paper") in PAPER_SIZES_MM else "A4"
    orientation = d.get("orientation") if d.get("orientation") in ORIENTATIONS else "portrait"

    # Element-centric: content text stays top-level; per-block props live under
    # elements.<name>. ``badges: []`` means "all" (resolved at render time).
    els = d.get("elements") if isinstance(d.get("elements"), dict) else {}
    bb_in = els.get("badge_block") if isinstance(els.get("badge_block"), dict) else {}
    badges = bb_in.get("badges")
    badges = [str(s) for s in badges] if isinstance(badges, list) else []
    bg_in = els.get("background") if isinstance(els.get("background"), dict) else {}
    bg_style = bg_in.get("style") if bg_in.get("style") in _BG_STYLES else "none"

    return {
        "name": _str(d.get("name"))[:120],
        "type": code,
        "paper": paper,
        "orientation": orientation,
        # False (default): scale everything to fit one page. True: paginate.
        "multi_page": _bool(d.get("multi_page"), False),
        # Multi-page only: repeat the full title (masthead) on every page. The
        # header and footer always repeat when paginating; this adds the title.
        "repeat_title": _bool(d.get("repeat_title"), False),
        "title": _str(d.get("title"))[:200],
        "subtitle": _str(d.get("subtitle"))[:300],
        "header": _str(d.get("header"))[:200],
        "footer": _str(d.get("footer"))[:200],
        "group_name": _str(d.get("group_name"))[:120],
        "speltak_name": _str(d.get("speltak_name"))[:120],
        "elements": {
            "title": _font_style(els.get("title"), 48),
            "subtitle": _font_style(els.get("subtitle"), 24),
            "header": _font_style(els.get("header"), 11),
            "footer": _font_style(els.get("footer"), 10),
            "badge_block": {
                "font_size_pt": _int(bb_in.get("font_size_pt"), 12, 6, 72),
                "columns": _int(bb_in.get("columns"), 4, 1, 12),
                "badge_size_mm": _int(bb_in.get("badge_size_mm"), 0, 0, 120),
                "show_titles": _bool(bb_in.get("show_titles"), True),
                "show_section_headers": _bool(bb_in.get("show_section_headers"), True),
                "show_niveau_headers": _bool(bb_in.get("show_niveau_headers"), True),
                "show_activiteitengebied": _bool(bb_in.get("show_activiteitengebied"), True),
                "activiteitengebied_font_size_pt": _int(bb_in.get("activiteitengebied_font_size_pt"), 14, 6, 72),
                # accept the common 'neveaus' misspelling + the old singular 'niveau'
                "niveaus": _niveaus(bb_in.get("niveaus", bb_in.get("neveaus", bb_in.get("niveau")))),
                "badges": badges,
            },
            "background": {
                "style": bg_style,
                "start_color": _color(bg_in.get("start_color"), "#ffffff"),
                "end_color": _color(bg_in.get("end_color"), "#ffffff"),
            },
        },
    }


# ── Serialisation ──────────────────────────────────────────────────────────────

def to_yaml(defn: dict) -> str:
    return yaml.safe_dump(normalise(defn), allow_unicode=True, sort_keys=False)


def from_yaml(text: str) -> dict:
    """Parse a YAML poster definition (safe_load only) → normalised dict.
    Raises ValueError on non-mapping / invalid YAML."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"ongeldige YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("posterdefinitie moet een YAML-mapping zijn")
    return normalise(data)
