from pathlib import Path

import pytest

from insigne.badges import get_badge, list_badges

FIXTURES = Path(__file__).parent / "fixtures"
DATA_DIR = Path(__file__).parent.parent / "api" / "data"


def _all_slugs(data_dir: Path) -> list[str]:
    return [p.stem for p in (data_dir / "badges").glob("*.yml")]


# ── list_badges ──────────────────────────────────────────────────────────────

class TestListBadges:
    def test_returns_both_categories(self):
        result = list_badges(FIXTURES)
        assert "gewoon" in result
        assert "buitengewoon" in result

    def test_gewoon_contains_kantklossen(self):
        result = list_badges(FIXTURES)
        slugs = [b["slug"] for b in result["gewoon"]]
        assert "kantklossen" in slugs

    def test_buitengewoon_contains_cybersecurity(self):
        result = list_badges(FIXTURES)
        slugs = [b["slug"] for b in result["buitengewoon"]]
        assert "cybersecurity" in slugs

    def test_category_field_matches_group(self):
        result = list_badges(FIXTURES)
        for badge in result["gewoon"]:
            assert badge["category"] == "gewoon"
        for badge in result["buitengewoon"]:
            assert badge["category"] == "buitengewoon"

    def test_title_matches_yml(self):
        result = list_badges(FIXTURES)
        kantklossen = next(b for b in result["gewoon"] if b["slug"] == "kantklossen")
        cybersecurity = next(b for b in result["buitengewoon"] if b["slug"] == "cybersecurity")
        assert kantklossen["title"] == "Insigne Kantklossen"
        assert cybersecurity["title"] == "Insigne Cybersecurity"

    def test_images_are_three_urls(self):
        result = list_badges(FIXTURES)
        for category in result.values():
            for badge in category:
                assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        result = list_badges(FIXTURES)
        kantklossen = next(b for b in result["gewoon"] if b["slug"] == "kantklossen")
        assert kantklossen["images"] == [
            "/images/kantklossen.1.png",
            "/images/kantklossen.2.png",
            "/images/kantklossen.3.png",
        ]

    def test_order_matches_yml(self):
        # badges.yml lists gewoon first, then buitengewoon
        result = list_badges(FIXTURES)
        assert list(result.keys()) == ["gewoon", "buitengewoon"]

    def test_list_items_have_no_levels(self):
        result = list_badges(FIXTURES)
        for category in result.values():
            for badge in category:
                assert "levels" not in badge
                assert "introduction" not in badge


# ── get_badge ─────────────────────────────────────────────────────────────────

class TestGetBadge:
    def test_returns_none_for_unknown_slug(self):
        assert get_badge(FIXTURES, "nonexistent") is None

    def test_returns_dict_for_known_slug(self):
        assert get_badge(FIXTURES, "cybersecurity") is not None
        assert get_badge(FIXTURES, "kantklossen") is not None

    def test_slug_field(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        assert badge["slug"] == "cybersecurity"

    def test_title_matches_yml(self):
        assert get_badge(FIXTURES, "cybersecurity")["title"] == "Insigne Cybersecurity"
        assert get_badge(FIXTURES, "kantklossen")["title"] == "Insigne Kantklossen"

    def test_category_from_index(self):
        assert get_badge(FIXTURES, "cybersecurity")["category"] == "buitengewoon"
        assert get_badge(FIXTURES, "kantklossen")["category"] == "gewoon"

    def test_images_are_three_urls(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        assert badge["images"] == [
            "/images/cybersecurity.1.png",
            "/images/cybersecurity.2.png",
            "/images/cybersecurity.3.png",
        ]

    def test_introduction_present(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        assert "Cyber Security" in badge["introduction"]

    def test_afterword_present(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        assert badge["afterword"] != ""
        assert "Cyber Security" in badge["afterword"]

    def test_five_levels(self):
        for slug in ("cybersecurity", "kantklossen"):
            badge = get_badge(FIXTURES, slug)
            assert len(badge["levels"]) == 5, f"{slug} should have 5 step groups"

    def test_step_group_names_match_yml(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        names = [g["name"] for g in badge["levels"]]
        assert names == [
            "Ontdek de digitale wereld",
            "Samen en sociaal",
            "Veilig en verantwoord",
            "Creatief en duurzaam",
            "Samen sterker!",
        ]

    def test_each_group_has_three_steps(self):
        for slug in ("cybersecurity", "kantklossen"):
            badge = get_badge(FIXTURES, slug)
            for group in badge["levels"]:
                assert len(group["steps"]) == 3, (
                    f"{slug} / {group['name']} should have 3 steps"
                )

    def test_step_indices_are_zero_based(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        for group in badge["levels"]:
            indices = [s["index"] for s in group["steps"]]
            assert indices == [0, 1, 2]

    def test_step_text_is_non_empty(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"].strip() != ""

    def test_step_text_is_stripped(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"] == step["text"].strip()

    def test_first_step_of_first_group_cybersecurity(self):
        badge = get_badge(FIXTURES, "cybersecurity")
        first_step = badge["levels"][0]["steps"][0]["text"]
        assert first_step.startswith("Een digitale wereld vol kansen!")

    def test_kantklossen_step_group_names_match_yml(self):
        badge = get_badge(FIXTURES, "kantklossen")
        names = [g["name"] for g in badge["levels"]]
        assert names == [
            "Kennismaken",
            "Oefenen",
            "Verdiepen",
            "Delen",
            "Meester worden",
        ]


# ── Badge structure validation (runs against real api/data/) ─────────────────

@pytest.mark.parametrize("slug", _all_slugs(DATA_DIR))
class TestBadgeStructure:
    def test_has_five_eisen(self, slug):
        badge = get_badge(DATA_DIR, slug)
        assert len(badge["levels"]) == 5, (
            f"{slug}: verwacht 5 eisen, gevonden {len(badge['levels'])}"
        )

    def test_each_eis_has_three_niveaus(self, slug):
        badge = get_badge(DATA_DIR, slug)
        for eis in badge["levels"]:
            assert len(eis["steps"]) == 3, (
                f"{slug} / '{eis['name']}': verwacht 3 niveaus, gevonden {len(eis['steps'])}"
            )
