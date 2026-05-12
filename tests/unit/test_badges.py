from pathlib import Path

import pytest
import yaml

from insigne.badges import get_badge, list_badges

DATA_DIR = Path(__file__).parent.parent.parent / "api" / "data"


def _all_slugs(data_dir: Path) -> list[str]:
    return [p.stem for p in (data_dir / "badges").glob("*.yml")]


# ── list_badges ──────────────────────────────────────────────────────────────

class TestListBadges:
    def test_returns_both_categories(self):
        result = list_badges(DATA_DIR)
        assert "gewoon" in result
        assert "buitengewoon" in result

    def test_gewoon_contains_sport_spel(self):
        result = list_badges(DATA_DIR)
        slugs = [b["slug"] for b in result["gewoon"]]
        assert "sport_spel" in slugs

    def test_buitengewoon_contains_vredeslicht(self):
        result = list_badges(DATA_DIR)
        slugs = [b["slug"] for b in result["buitengewoon"]]
        assert "vredeslicht" in slugs

    def test_category_field_matches_group(self):
        result = list_badges(DATA_DIR)
        for badge in result["gewoon"]:
            assert badge["category"] == "gewoon"
        for badge in result["buitengewoon"]:
            assert badge["category"] == "buitengewoon"

    def test_title_matches_yml(self):
        result = list_badges(DATA_DIR)
        sport_spel = next(b for b in result["gewoon"] if b["slug"] == "sport_spel")
        vredeslicht = next(b for b in result["buitengewoon"] if b["slug"] == "vredeslicht")
        assert sport_spel["title"] == "Insigne Sport & Spel"
        assert vredeslicht["title"] == "Insigne Vredeslicht"

    def test_images_are_three_urls(self):
        result = list_badges(DATA_DIR)
        for category in result.values():
            for badge in category:
                assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        result = list_badges(DATA_DIR)
        sport_spel = next(b for b in result["gewoon"] if b["slug"] == "sport_spel")
        assert sport_spel["images"] == [
            "/images/sport_spel.1.png",
            "/images/sport_spel.2.png",
            "/images/sport_spel.3.png",
        ]

    def test_order_matches_yml(self):
        result = list_badges(DATA_DIR)
        keys = list(result.keys())
        assert keys[0] == "gewoon"
        assert keys[1] == "buitengewoon"
        assert "explorers" in keys

    def test_list_items_have_no_levels(self):
        result = list_badges(DATA_DIR)
        for category in result.values():
            for badge in category:
                assert "levels" not in badge
                assert "introduction" not in badge


# ── get_badge ─────────────────────────────────────────────────────────────────

class TestGetBadge:
    def test_returns_none_for_unknown_slug(self):
        assert get_badge(DATA_DIR, "nonexistent") is None

    def test_returns_dict_for_known_slug(self):
        assert get_badge(DATA_DIR, "vredeslicht") is not None
        assert get_badge(DATA_DIR, "sport_spel") is not None

    def test_slug_field(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        assert badge["slug"] == "vredeslicht"

    def test_title_matches_yml(self):
        assert get_badge(DATA_DIR, "vredeslicht")["title"] == "Insigne Vredeslicht"
        assert get_badge(DATA_DIR, "sport_spel")["title"] == "Insigne Sport & Spel"

    def test_category_from_index(self):
        assert get_badge(DATA_DIR, "vredeslicht")["category"] == "buitengewoon"
        assert get_badge(DATA_DIR, "sport_spel")["category"] == "gewoon"

    def test_images_are_three_urls(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        assert badge["images"] == [
            "/images/vredeslicht.1.png",
            "/images/vredeslicht.2.png",
            "/images/vredeslicht.3.png",
        ]

    def test_introduction_present(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        assert "Vredeslicht" in badge["introduction"]

    def test_afterword_present(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        assert badge["afterword"] != ""

    def test_five_levels(self):
        for slug in ("vredeslicht", "sport_spel"):
            badge = get_badge(DATA_DIR, slug)
            assert len(badge["levels"]) == 5, f"{slug} should have 5 step groups"

    def test_step_group_names_match_yml(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        names = [g["name"] for g in badge["levels"]]
        assert names == [
            "Geschiedenis",
            "Reis en verspreiding",
            "Betekenis en vredesgedachte",
            "Creatief en duurzaam",
            "Evenement en eigen bijdrage",
        ]

    def test_each_group_has_three_steps(self):
        for slug in ("vredeslicht", "sport_spel"):
            badge = get_badge(DATA_DIR, slug)
            for group in badge["levels"]:
                assert len(group["steps"]) == 3, (
                    f"{slug} / {group['name']} should have 3 steps"
                )

    def test_step_indices_are_zero_based(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        for group in badge["levels"]:
            indices = [s["index"] for s in group["steps"]]
            assert indices == [0, 1, 2]

    def test_step_text_is_non_empty(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"].strip() != ""

    def test_step_text_is_stripped(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"] == step["text"].strip()

    def test_first_step_of_first_group_vredeslicht(self):
        badge = get_badge(DATA_DIR, "vredeslicht")
        first_step = badge["levels"][0]["steps"][0]["text"]
        assert first_step.startswith("Ontdek waar het Vredeslicht")

    def test_sport_spel_step_group_names_match_yml(self):
        badge = get_badge(DATA_DIR, "sport_spel")
        names = [g["name"] for g in badge["levels"]]
        assert names == [
            "Sporten",
            "Spelen",
            "Bedenken",
            "Spelleiding",
            "Extern",
        ]


# ── Explorer Jaarbadge specifics ─────────────────────────────────────────────

class TestExplorerJaarbadge:
    def test_present_in_explorers_category(self):
        result = list_badges(DATA_DIR)
        assert "explorers" in result
        slugs = [b["slug"] for b in result["explorers"]]
        assert "explorer_jaarbadge" in slugs

    def test_category_is_explorers(self):
        badge = get_badge(DATA_DIR, "explorer_jaarbadge")
        assert badge["category"] == "explorers"

    def test_niveau_label_is_jaarbadge(self):
        badge = get_badge(DATA_DIR, "explorer_jaarbadge")
        assert badge["niveau_label"] == "Jaarbadge"

    def test_has_eight_eis_groups(self):
        badge = get_badge(DATA_DIR, "explorer_jaarbadge")
        assert len(badge["levels"]) == 8

    def test_each_group_has_three_steps(self):
        badge = get_badge(DATA_DIR, "explorer_jaarbadge")
        for group in badge["levels"]:
            assert len(group["steps"]) == 3

    def test_last_eis_group_has_empty_steps_for_jaar_1_and_2(self):
        badge = get_badge(DATA_DIR, "explorer_jaarbadge")
        last = badge["levels"][-1]
        assert last["steps"][0]["text"].strip() == ""
        assert last["steps"][1]["text"].strip() == ""
        assert last["steps"][2]["text"].strip() != ""


# ── Badge structure validation (runs against real api/data/) ─────────────────

@pytest.mark.parametrize("slug", _all_slugs(DATA_DIR))
class TestBadgeStructure:
    def test_has_at_least_one_eis(self, slug):
        badge = get_badge(DATA_DIR, slug)
        assert len(badge["levels"]) >= 1, (
            f"{slug}: verwacht minimaal 1 eis, gevonden {len(badge['levels'])}"
        )
        if badge["category"] not in ("explorers",):
            assert len(badge["levels"]) == 5, (
                f"{slug}: verwacht 5 eisen voor gewone/buitengewone insignes, gevonden {len(badge['levels'])}"
            )

    def test_each_eis_has_three_niveaus(self, slug):
        badge = get_badge(DATA_DIR, slug)
        for eis in badge["levels"]:
            assert len(eis["steps"]) == 3, (
                f"{slug} / '{eis['name']}': verwacht 3 niveaus, gevonden {len(eis['steps'])}"
            )

    def test_yaml_parses_without_error(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        assert raw is not None

    def test_required_top_level_keys(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        assert "slug" in raw
        assert "titel" in raw
        assert "introductie" in raw
        assert "eisen" in raw

    def test_slug_matches_filename(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        assert raw["slug"] == slug

    def test_introduction_is_non_empty_string(self, slug):
        badge = get_badge(DATA_DIR, slug)
        assert isinstance(badge["introduction"], str)
        assert badge["introduction"].strip() != ""

    def test_afterword_is_string(self, slug):
        # afterword is optional but must never crash (None → "")
        badge = get_badge(DATA_DIR, slug)
        assert isinstance(badge["afterword"], str)

    def test_step_text_non_empty(self, slug):
        badge = get_badge(DATA_DIR, slug)
        for group in badge["levels"]:
            non_empty = [s for s in group["steps"] if s["text"].strip()]
            assert non_empty, (
                f"{slug} / '{group['name']}': alle stappen zijn leeg"
            )

    def test_niveau_label_default_is_niveau(self, slug):
        badge = get_badge(DATA_DIR, slug)
        if badge["category"] != "explorers":
            assert badge["niveau_label"] == "Niveau", (
                f"{slug}: verwacht niveau_label 'Niveau', gevonden '{badge['niveau_label']}'"
            )

    def test_step_green_is_bool(self, slug):
        badge = get_badge(DATA_DIR, slug)
        for group in badge["levels"]:
            for step in group["steps"]:
                assert isinstance(step["green"], bool), (
                    f"{slug} / '{group['name']}' step {step['index']} green is not bool"
                )

    def test_groen_true_steps_contain_equals_markers(self, slug):
        # When groen=True in YAML, _parse_step must wrap text in ==...==
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        badge = get_badge(DATA_DIR, slug)
        for group_raw, group in zip(raw["eisen"], badge["levels"]):
            for step_raw, step in zip(group_raw["eisen"], group["steps"]):
                if isinstance(step_raw, dict) and step_raw.get("groen"):
                    assert "==" in step["text"], (
                        f"{slug} / '{group['name']}' step {step['index']}: "
                        "groen=True but no == markers in parsed text"
                    )
                    assert step["green"] is True

    def test_eis_dicts_have_tekst_key(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        for group in raw["eisen"]:
            for step in group["eisen"]:
                if isinstance(step, dict):
                    assert "tekst" in step, (
                        f"{slug} / '{group['naam']}': dict step missing 'tekst' key"
                    )


# ── _parse_step unit tests (no file I/O) ─────────────────────────────────────

class TestParseStep:
    """Tests for _parse_step logic via get_badge on synthetic-like YAML."""

    def _badge_with_steps(self, *steps):
        """Build a minimal badge YAML string with one group of given step strings/dicts."""
        import tempfile, os
        lines = [
            "slug: testbadge\n",
            "titel: Test\n",
            "introductie: intro\n",
            "eisen:\n",
            "  - naam: Groep\n",
            "    eisen:\n",
        ]
        for step in steps:
            if isinstance(step, str):
                lines.append(f"      - |\n        {step}\n")
            else:
                tekst = step["tekst"]
                groen = step.get("groen", False)
                lines.append(f"      - tekst: |\n          {tekst}\n")
                if groen:
                    lines.append("        groen: true\n")
        content = "".join(lines)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False,
            dir=DATA_DIR / "badges", prefix="_test_"
        )
        tmp.write(content)
        tmp.close()

        # patch badges.yml to include testbadge temporarily
        index_path = DATA_DIR / "badges.yml"
        original_index = index_path.read_text()
        index = yaml.safe_load(original_index)
        slug = Path(tmp.name).stem
        index["badges"].setdefault("gewoon", []).append(slug)
        index_path.write_text(yaml.dump(index))

        try:
            badge = get_badge(DATA_DIR, slug)
        finally:
            os.unlink(tmp.name)
            index_path.write_text(original_index)

        return badge["levels"][0]["steps"]

    def test_plain_string_step_green_false(self):
        steps = self._badge_with_steps("gewone tekst")
        assert steps[0]["green"] is False

    def test_plain_string_with_equals_green_true(self):
        steps = self._badge_with_steps("==groen deel==")
        assert steps[0]["green"] is True

    def test_dict_groen_true_wraps_text(self):
        steps = self._badge_with_steps({"tekst": "hele stap groen", "groen": True})
        assert steps[0]["green"] is True
        assert "==" in steps[0]["text"]

    def test_dict_groen_false_no_wrap(self):
        steps = self._badge_with_steps({"tekst": "niet groen", "groen": False})
        assert steps[0]["green"] is False
        assert "==" not in steps[0]["text"]

    def test_dict_groen_true_with_existing_equals_not_double_wrapped(self):
        steps = self._badge_with_steps({"tekst": "==deels groen==", "groen": True})
        # Should not add outer == because text already contains ==
        text = steps[0]["text"]
        assert text.count("==") == 2  # exactly one pair

    def test_step_index_is_zero_based(self):
        steps = self._badge_with_steps("stap a", "stap b", "stap c")
        assert [s["index"] for s in steps] == [0, 1, 2]

    def test_text_is_stripped(self):
        steps = self._badge_with_steps("  tekst met spaties  ")
        assert steps[0]["text"] == steps[0]["text"].strip()


# ── list_badges / get_badge error handling ───────────────────────────────────

class TestListBadgesErrors:
    def test_missing_index_raises(self, tmp_path):
        (tmp_path / "badges").mkdir()
        with pytest.raises(FileNotFoundError):
            list_badges(tmp_path)

    def test_missing_badge_file_raises(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text(
            "badges:\n  gewoon:\n    - phantom\n"
        )
        with pytest.raises(FileNotFoundError):
            list_badges(tmp_path)

    def test_malformed_badge_yaml_raises(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text(
            "badges:\n  gewoon:\n    - broken\n"
        )
        (tmp_path / "badges" / "broken.yml").write_text(": [invalid yaml\n")
        with pytest.raises(yaml.YAMLError):
            list_badges(tmp_path)

    def test_malformed_index_yaml_raises(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text(": [invalid yaml\n")
        with pytest.raises(yaml.YAMLError):
            list_badges(tmp_path)

    def test_empty_index_returns_empty_dict(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        assert list_badges(tmp_path) == {}


class TestGetBadgeErrors:
    def test_nonexistent_slug_returns_none(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        assert get_badge(tmp_path, "nope") is None

    def test_malformed_badge_yaml_raises(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        (tmp_path / "badges" / "broken.yml").write_text(": [invalid yaml\n")
        with pytest.raises(yaml.YAMLError):
            get_badge(tmp_path, "broken")

    def test_category_is_none_when_slug_not_in_index(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        (tmp_path / "badges" / "orphan.yml").write_text(
            "slug: orphan\ntitel: Test\nintroductie: intro\neisen: []\n"
        )
        badge = get_badge(tmp_path, "orphan")
        assert badge is not None
        assert badge["category"] is None

    def test_none_nawoord_becomes_empty_string(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        (tmp_path / "badges" / "no_afterword.yml").write_text(
            "slug: no_afterword\ntitel: T\nintroductie: intro\neisen: []\n"
        )
        badge = get_badge(tmp_path, "no_afterword")
        assert badge["afterword"] == ""

    def test_explicit_null_nawoord_becomes_empty_string(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        (tmp_path / "badges" / "null_afterword.yml").write_text(
            "slug: null_afterword\ntitel: T\nintroductie: intro\nnawoord:\neisen: []\n"
        )
        badge = get_badge(tmp_path, "null_afterword")
        assert badge["afterword"] == ""
