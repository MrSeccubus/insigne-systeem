import re
from pathlib import Path

import yaml

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


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
        "niveau_label": raw.get("niveau_label", "Niveau"),
        "niveau_label_kort": raw.get("niveau_label_kort", "N"),
        "images": [f"/images/{slug}.{i}.png" for i in (1, 2, 3)],
        "introduction": (raw.get("introductie") or "").strip(),
        "levels": step_groups,
        "afterword": (raw.get("nawoord") or "").strip(),
    }


class BadgeCatalogue:
    """All badge data loaded from disk once at construction time."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._by_slug: dict[str, dict] = {}
        self._by_category: dict[str, list] = {}
        self._load()

    def _load(self):
        index = yaml.safe_load((self.data_dir / "badges.yml").read_text())
        for category, slugs in index["badges"].items():
            items = []
            for slug in slugs:
                raw = yaml.safe_load((self.data_dir / "badges" / f"{slug}.yml").read_text())
                items.append({
                    "slug": slug,
                    "title": raw["titel"],
                    "category": category,
                    "images": [f"/images/{slug}.{i}.png" for i in (1, 2, 3)],
                })
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
