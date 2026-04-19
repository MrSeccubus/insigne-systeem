from pathlib import Path

import yaml


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
    badge_path = data_dir / "badges" / f"{slug}.yml"
    if not badge_path.exists():
        return None

    raw = yaml.safe_load(badge_path.read_text())

    index = _load_index(data_dir)
    category = next(
        (cat for cat, slugs in index["badges"].items() if slug in slugs),
        None,
    )

    step_groups = [
        {
            "name": group["naam"],
            "steps": [
                {"index": i, "text": step.strip()}
                for i, step in enumerate(group["eisen"])
            ],
        }
        for group in raw.get("eisen", [])
    ]

    return {
        "slug": slug,
        "title": raw["titel"],
        "category": category,
        "images": _images(slug),
        "introduction": raw.get("introductie", "").strip(),
        "levels": step_groups,
        "afterword": raw.get("nawoord", "").strip(),
    }
