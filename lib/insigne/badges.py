import re
from pathlib import Path

import yaml

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def _images(slug: str) -> list[str]:
    return [f"/images/{slug}.{i}.png" for i in (1, 2, 3)]


def _load_index(data_dir: Path) -> dict:
    return yaml.safe_load((data_dir / "badges.yml").read_text())


def list_badges(data_dir: Path) -> dict:
    """Return {'gewoon': [...], 'buitengewoon': [...]} ordered as in badges.yml."""
    index = _load_index(data_dir)
    result = {}
    for category, slugs in index["badges"].items():
        items = []
        for slug in slugs:
            raw = yaml.safe_load((data_dir / "badges" / f"{slug}.yml").read_text())
            items.append({
                "slug": slug,
                "title": raw["titel"],
                "category": category,
                "images": _images(slug),
            })
        result[category] = items
    return result


def get_badge(data_dir: Path, slug: str) -> dict | None:
    """Return full badge detail for slug, or None if not found."""
    if not _SLUG_RE.match(slug):
        return None

    badges_dir = (data_dir / "badges").resolve()
    badge_path = (badges_dir / f"{slug}.yml").resolve()
    if not badge_path.is_relative_to(badges_dir):
        return None
    if not badge_path.exists():
        return None

    raw = yaml.safe_load(badge_path.read_text())

    index = _load_index(data_dir)
    category = next(
        (cat for cat, slugs in index["badges"].items() if slug in slugs),
        None,
    )

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
        "images": _images(slug),
        "introduction": (raw.get("introductie") or "").strip(),
        "levels": step_groups,
        "afterword": (raw.get("nawoord") or "").strip(),
    }
