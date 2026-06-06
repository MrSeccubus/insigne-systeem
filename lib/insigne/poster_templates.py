"""Poster definition: the canonical YAML document for a poster (#132).

A poster is a self-contained definition (stored as YAML, exportable/importable).
This module owns the type codes, the supported paper sizes, the built-in base
definition per type, and ``normalise()`` — the single validator that allowlists
keys and coerces types so nothing arbitrary reaches the renderer.

Templating of the text fields (``title``/``header``/… may contain ``{{ … }}``)
lives in ``poster_render.py`` (a sandboxed Jinja environment).
"""
from __future__ import annotations

import copy

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
PAGE_MARGIN_MM = 12

# Text fields that may contain {{ … }} templates (rendered in poster_render).
TEXT_FIELDS = ("title", "subtitle", "header", "footer", "group_name", "speltak_name")


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


def _font_style(raw: dict | None, default_pt: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {"font_size_pt": _int(raw.get("font_size_pt"), default_pt, 6, 300)}


# ── Base templates + normalisation ────────────────────────────────────────────

def base_definition(type_code_value: int) -> dict:
    """A fresh built-in definition for a poster type — the wizard's starting
    point. Returns a normalised deep copy."""
    code = type_code(type_code_value)
    key = TYPE_CODES[code]
    defn: dict = {
        "name": "",
        "type": code,
        "paper": "A3" if key in ("badges", "speltak") else "A4",
        "orientation": "landscape" if key == "speltak" else "portrait",
        "title": TYPE_LABELS[code],
        "subtitle": "",
        "header": "",
        "footer": "",
        "group_name": "",
        "speltak_name": "",
        "demo_blocks": 12,
        "styles": {
            "title": {"font_size_pt": 48},
            "subtitle": {"font_size_pt": 24},
            "body": {"font_size_pt": 12},
        },
        "elements": {
            "badge_block": {
                "columns": 4,
                "badge_size_mm": 0,   # 0 = auto (fill the grid cell)
                "show_titles": True,
                "niveau": 1,
                "badges": [],
            },
        },
    }
    return normalise(defn)


def normalise(defn) -> dict:
    """Validate + coerce an arbitrary parsed definition into the canonical shape.
    Unknown keys are dropped; every known key is present and type-correct."""
    d = defn if isinstance(defn, dict) else {}
    code = type_code(d.get("type"))
    paper = d.get("paper") if d.get("paper") in PAPER_SIZES_MM else "A4"
    orientation = d.get("orientation") if d.get("orientation") in ORIENTATIONS else "portrait"

    styles_in = d.get("styles") if isinstance(d.get("styles"), dict) else {}
    bb_in = {}
    if isinstance(d.get("elements"), dict) and isinstance(d["elements"].get("badge_block"), dict):
        bb_in = d["elements"]["badge_block"]

    badges = bb_in.get("badges")
    badges = [str(s) for s in badges] if isinstance(badges, list) else []

    return {
        "name": _str(d.get("name"))[:120],
        "type": code,
        "paper": paper,
        "orientation": orientation,
        "title": _str(d.get("title"))[:200],
        "subtitle": _str(d.get("subtitle"))[:300],
        "header": _str(d.get("header"))[:200],
        "footer": _str(d.get("footer"))[:200],
        "group_name": _str(d.get("group_name"))[:120],
        "speltak_name": _str(d.get("speltak_name"))[:120],
        "demo_blocks": _int(d.get("demo_blocks"), 12, 0, 400),
        "styles": {
            "title": _font_style(styles_in.get("title"), 48),
            "subtitle": _font_style(styles_in.get("subtitle"), 24),
            "body": _font_style(styles_in.get("body"), 12),
        },
        "elements": {
            "badge_block": {
                "columns": _int(bb_in.get("columns"), 4, 1, 12),
                "badge_size_mm": _int(bb_in.get("badge_size_mm"), 0, 0, 120),
                "show_titles": _bool(bb_in.get("show_titles"), True),
                "niveau": _int(bb_in.get("niveau"), 1, 1, 3),
                "badges": badges,
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
