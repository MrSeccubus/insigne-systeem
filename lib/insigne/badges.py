import re
from pathlib import Path

import yaml

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

# Plusscouts fall back to the highest defined level below them
_SPELTAK_ORDER = ["bevers", "welpen", "scouts", "explorers", "roverscouts", "plusscouts"]


def _parse_jaarinsigne_step(i: int, step_raw) -> dict:
    """Parse one jaarinsigne eis, which has a titel and tekst field."""
    if isinstance(step_raw, dict):
        titel = step_raw.get("titel", "").strip()
        tekst = step_raw.get("tekst", "").strip()
    else:
        # Legacy plain string: split heading from body
        text = (step_raw or "").strip()
        lines = text.split("\n", 1)
        titel = lines[0].lstrip("#").strip()
        tekst = lines[1].strip() if len(lines) > 1 else text
    return {"index": i, "titel": titel, "text": tekst, "green": False}


def _parse_step(i, step):
    if isinstance(step, dict):
        text = step.get("tekst", "").strip()
        bevat_groen = step.get("groen", False)
    else:
        text = step.strip()
        bevat_groen = False
    if bevat_groen and "==" not in text:
        text = f"=={text}=="
    return {"index": i, "text": text, "green": bevat_groen or "==" in text}


def _parse_full(slug: str, raw: dict, category: str | None) -> dict:
    step_groups = [
        {
            "name": group.get("naam", ""),
            "steps": [_parse_step(i, step) for i, step in enumerate(group["eisen"])],
        }
        for group in raw.get("eisen", [])
    ]
    return {
        "slug": slug,
        "title": raw["titel"],
        "category": category,
        "type": raw.get("type", "gewoon"),
        "niveau_label": raw.get("niveau_label", "Niveau"),
        "niveau_label_kort": raw.get("niveau_label_kort", "N"),
        "images": [f"/images/{slug}.{i}.png" for i in (1, 2, 3)],
        "introduction": (raw.get("introductie") or "").strip(),
        "levels": step_groups,
        "afterword": (raw.get("nawoord") or "").strip(),
        "dedicated_api": raw.get("dedicated_api", False),
    }


def _parse_jaarinsigne(slug: str, raw: dict, category: str | None, speltakken_meta: list[dict]) -> dict:
    """Parse a jaarinsigne badge.

    level_index = speltak position in _SPELTAK_ORDER (0=bevers … 4=roverscouts, 5=plusscouts)
    step_index  = eis index within that speltak's requirements
    """
    speltakken_data = raw.get("speltakken", {})

    # Build levels list: one entry per speltak slug that appears in speltakken_meta
    levels = []
    for meta in speltakken_meta:
        speltak_slug = meta["slug"]
        if speltak_slug == "plusscouts":
            # Plusscouts resolves at runtime; include if explicitly defined
            eisen_raw = speltakken_data.get(speltak_slug)
        else:
            eisen_raw = speltakken_data.get(speltak_slug)

        if eisen_raw is None:
            continue

        steps = [_parse_jaarinsigne_step(i, eis) for i, eis in enumerate(eisen_raw)]
        level_index = _SPELTAK_ORDER.index(speltak_slug) if speltak_slug in _SPELTAK_ORDER else len(levels)
        levels.append({
            "slug": speltak_slug,
            "name": meta["naam"],
            "kort": meta["kort"],
            "leeftijd": meta.get("leeftijd", ""),
            "level_index": level_index,
            "steps": steps,
        })

    return {
        "slug": slug,
        "title": raw["titel"],
        "category": category,
        "type": "jaarinsigne",
        "images": [f"/images/{slug}.png"],
        "introduction": (raw.get("introductie") or "").strip(),
        "levels": levels,
        "afterword": (raw.get("nawoord") or "").strip(),
        "dedicated_api": False,
        "n_levels": len(levels),
        "speltakken": speltakken_meta,
    }


class BadgeCatalogue:
    """All badge data loaded from disk once at construction time."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._by_slug: dict[str, dict] = {}
        self._by_category: dict[str, list] = {}
        self._load()

    def _load(self):
        speltakken_raw = yaml.safe_load((self.data_dir / "speltakken.yml").read_text())
        self.speltakken_meta: list[dict] = speltakken_raw["speltakken"]

        index = yaml.safe_load((self.data_dir / "badges.yml").read_text())
        self.category_labels: dict[str, str] = {}
        for category, cat_data in index["badges"].items():
            self.category_labels[category] = cat_data["label"]
            items = []
            for slug in cat_data["badges"]:
                raw = yaml.safe_load((self.data_dir / "badges" / f"{slug}.yml").read_text())
                badge_type = raw.get("type", "gewoon")
                items.append({
                    "slug": slug,
                    "title": raw["titel"],
                    "category": category,
                    "type": badge_type,
                    "images": [f"/images/{slug}.{i}.png" for i in (1, 2, 3)]
                             if badge_type != "jaarinsigne"
                             else [f"/images/{slug}.png"],
                    "dedicated_api": raw.get("dedicated_api", False),
                })
                if badge_type == "jaarinsigne":
                    self._by_slug[slug] = _parse_jaarinsigne(slug, raw, category, self.speltakken_meta)
                else:
                    self._by_slug[slug] = _parse_full(slug, raw, category)
            self._by_category[category] = items

    def get(self, slug: str) -> dict | None:
        """Return full badge detail for slug, or None if not found or invalid."""
        if not _SLUG_RE.match(slug):
            return None
        return self._by_slug.get(slug)

    def list(self) -> dict:
        """Return {'gewoon': [...], ...} ordered as in badges.yml."""
        return self._by_category

    def resolve_jaarinsigne_level_index(self, badge: dict, speltak_slug: str | None) -> int:
        """Return the level_index to use for this badge given a speltak_slug.

        Falls back to scouts (index 2), then first defined level.
        Plusscouts walks down to the highest available level below it.
        """
        defined_slugs = {lvl["slug"] for lvl in badge["levels"]}
        slug = speltak_slug or "scouts"

        if slug == "plusscouts" and "plusscouts" not in defined_slugs:
            # Walk down from roverscouts
            for candidate in reversed(_SPELTAK_ORDER[:-1]):  # exclude plusscouts
                if candidate in defined_slugs:
                    slug = candidate
                    break

        if slug in defined_slugs:
            return _SPELTAK_ORDER.index(slug) if slug in _SPELTAK_ORDER else 0

        # Fallback: scouts
        if "scouts" in defined_slugs:
            return _SPELTAK_ORDER.index("scouts")

        # Last resort: first defined level
        return badge["levels"][0]["level_index"] if badge["levels"] else 0
