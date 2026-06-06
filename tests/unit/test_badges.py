from pathlib import Path

import pytest
import yaml

from insigne.badges import BadgeCatalogue

DATA_DIR = Path(__file__).parent.parent.parent / "api" / "data"

_CAT = BadgeCatalogue(DATA_DIR)

_SPELTAKKEN_STUB = (
    "speltakken:\n"
    "  - slug: scouts\n"
    "    naam: Scouts\n"
    "    leeftijd: 11-15 jaar\n"
    "    kort: Sc\n"
)


def _all_slugs(data_dir: Path) -> list[str]:
    return [p.stem for p in (data_dir / "badges").glob("*.yml")]


def _jaarinsigne_slugs(data_dir: Path) -> list[str]:
    out = []
    for p in (data_dir / "badges").glob("*.yml"):
        raw = yaml.safe_load(p.read_text())
        if raw.get("type") == "jaarinsigne":
            out.append(p.stem)
    return out


# ── list (BadgeCatalogue.list) ────────────────────────────────────────────────

class TestList:
    def test_returns_both_categories(self):
        result = _CAT.list()
        assert "gewoon" in result
        assert "buitengewoon" in result

    def test_gewoon_contains_sport_spel(self):
        result = _CAT.list()
        slugs = [b["slug"] for b in result["gewoon"]]
        assert "sport_spel" in slugs

    def test_buitengewoon_contains_vredeslicht(self):
        result = _CAT.list()
        slugs = [b["slug"] for b in result["buitengewoon"]]
        assert "vredeslicht" in slugs

    def test_category_field_matches_group(self):
        result = _CAT.list()
        for badge in result["gewoon"]:
            assert badge["category"] == "gewoon"
        for badge in result["buitengewoon"]:
            assert badge["category"] == "buitengewoon"

    def test_title_matches_yml(self):
        result = _CAT.list()
        sport_spel = next(b for b in result["gewoon"] if b["slug"] == "sport_spel")
        vredeslicht = next(b for b in result["buitengewoon"] if b["slug"] == "vredeslicht")
        assert sport_spel["title"] == "Sport & Spel"
        assert vredeslicht["title"] == "Vredeslicht"

    def test_images_are_three_urls(self):
        result = _CAT.list()
        for category in result.values():
            for badge in category:
                if badge.get("type") == "jaarinsigne":
                    assert len(badge["images"]) == 1
                else:
                    assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        result = _CAT.list()
        sport_spel = next(b for b in result["gewoon"] if b["slug"] == "sport_spel")
        assert sport_spel["images"] == [
            "/images/sport_spel.1.png",
            "/images/sport_spel.2.png",
            "/images/sport_spel.3.png",
        ]

    def test_order_matches_yml(self):
        result = _CAT.list()
        keys = list(result.keys())
        assert keys[0] == "gewoon"
        assert keys[1] == "buitengewoon"
        assert "explorers" in keys

    def test_list_items_have_no_levels(self):
        result = _CAT.list()
        for category in result.values():
            for badge in category:
                assert "levels" not in badge
                assert "introduction" not in badge


# ── get (BadgeCatalogue.get) ──────────────────────────────────────────────────

class TestGet:
    def test_returns_none_for_unknown_slug(self):
        assert _CAT.get("nonexistent") is None

    @pytest.mark.parametrize("slug", [
        "../badges.yml",
        "../../etc/passwd",
        "foo/bar",
        "foo bar",
        "FOO",
        "",
    ])
    def test_rejects_invalid_slug(self, slug):
        assert _CAT.get(slug) is None

    def test_returns_dict_for_known_slug(self):
        assert _CAT.get("vredeslicht") is not None
        assert _CAT.get("sport_spel") is not None

    def test_slug_field(self):
        badge = _CAT.get("vredeslicht")
        assert badge["slug"] == "vredeslicht"

    def test_title_matches_yml(self):
        assert _CAT.get("vredeslicht")["title"] == "Vredeslicht"
        assert _CAT.get("sport_spel")["title"] == "Sport & Spel"

    def test_category_from_index(self):
        assert _CAT.get("vredeslicht")["category"] == "buitengewoon"
        assert _CAT.get("sport_spel")["category"] == "gewoon"

    def test_images_are_three_urls(self):
        badge = _CAT.get("vredeslicht")
        assert len(badge["images"]) == 3

    def test_image_urls_use_slug(self):
        badge = _CAT.get("vredeslicht")
        assert badge["images"] == [
            "/images/vredeslicht.1.png",
            "/images/vredeslicht.2.png",
            "/images/vredeslicht.3.png",
        ]

    def test_introduction_present(self):
        badge = _CAT.get("vredeslicht")
        assert "Vredeslicht" in badge["introduction"]

    def test_afterword_present(self):
        badge = _CAT.get("vredeslicht")
        assert badge["afterword"] != ""

    def test_five_levels(self):
        for slug in ("vredeslicht", "sport_spel"):
            badge = _CAT.get(slug)
            assert len(badge["levels"]) == 5, f"{slug} should have 5 step groups"

    def test_step_group_names_match_yml(self):
        badge = _CAT.get("vredeslicht")
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
            badge = _CAT.get(slug)
            for group in badge["levels"]:
                assert len(group["steps"]) == 3, (
                    f"{slug} / {group['name']} should have 3 steps"
                )

    def test_step_indices_are_zero_based(self):
        badge = _CAT.get("vredeslicht")
        for group in badge["levels"]:
            indices = [s["index"] for s in group["steps"]]
            assert indices == [0, 1, 2]

    def test_step_text_is_non_empty(self):
        badge = _CAT.get("vredeslicht")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"].strip() != ""

    def test_step_text_is_stripped(self):
        badge = _CAT.get("vredeslicht")
        for group in badge["levels"]:
            for step in group["steps"]:
                assert step["text"] == step["text"].strip()

    def test_first_step_of_first_group_vredeslicht(self):
        badge = _CAT.get("vredeslicht")
        first_step = badge["levels"][0]["steps"][0]["text"]
        assert first_step.startswith("Ontdek waar het Vredeslicht")

    def test_sport_spel_step_group_names_match_yml(self):
        badge = _CAT.get("sport_spel")
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
        result = _CAT.list()
        assert "explorers" in result
        slugs = [b["slug"] for b in result["explorers"]]
        assert "explorer_jaarbadge" in slugs

    def test_category_is_explorers(self):
        badge = _CAT.get("explorer_jaarbadge")
        assert badge["category"] == "explorers"

    def test_niveau_label_is_jaarbadge(self):
        badge = _CAT.get("explorer_jaarbadge")
        assert badge["niveau_label"] == "Jaarbadge"

    def test_has_eight_eis_groups(self):
        badge = _CAT.get("explorer_jaarbadge")
        assert len(badge["levels"]) == 8

    def test_each_group_has_three_steps(self):
        badge = _CAT.get("explorer_jaarbadge")
        for group in badge["levels"]:
            assert len(group["steps"]) == 3

    def test_last_eis_group_has_empty_steps_for_jaar_1_and_2(self):
        badge = _CAT.get("explorer_jaarbadge")
        last = badge["levels"][-1]
        assert last["steps"][0]["text"].strip() == ""
        assert last["steps"][1]["text"].strip() == ""
        assert last["steps"][2]["text"].strip() != ""


# ── Badge structure validation (runs against real api/data/) ─────────────────

@pytest.mark.parametrize("slug", _all_slugs(DATA_DIR))
class TestBadgeStructure:
    def test_has_at_least_one_eis(self, slug):
        badge = _CAT.get(slug)
        assert len(badge["levels"]) >= 1, (
            f"{slug}: verwacht minimaal 1 eis, gevonden {len(badge['levels'])}"
        )
        if badge["category"] not in ("explorers", "jaarinsignes"):
            assert len(badge["levels"]) == 5, (
                f"{slug}: verwacht 5 eisen voor gewone/buitengewone insignes, gevonden {len(badge['levels'])}"
            )

    def test_each_eis_has_three_niveaus(self, slug):
        badge = _CAT.get(slug)
        if badge.get("type") == "jaarinsigne":
            # For jaarinsignes "levels" are speltakken, not eisen — verify the
            # badge covers at least the bevers / welpen / scouts span.
            assert len(badge["levels"]) >= 3, (
                f"{slug}: verwacht minimaal 3 speltakken voor jaarinsigne, "
                f"gevonden {len(badge['levels'])}"
            )
            return
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
        if raw.get("type") == "jaarinsigne":
            assert "speltakken" in raw
        else:
            assert "eisen" in raw

    def test_slug_matches_filename(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        assert raw["slug"] == slug

    def test_introduction_is_non_empty_string(self, slug):
        badge = _CAT.get(slug)
        assert isinstance(badge["introduction"], str)
        assert badge["introduction"].strip() != ""

    def test_afterword_is_string(self, slug):
        badge = _CAT.get(slug)
        assert isinstance(badge["afterword"], str)

    def test_step_text_non_empty(self, slug):
        badge = _CAT.get(slug)
        if badge.get("type") == "jaarinsigne":
            for level in badge["levels"]:
                non_empty = [s for s in level["steps"] if s["text"].strip()]
                assert non_empty, f"{slug} / '{level['name']}': alle stappen zijn leeg"
            return
        for group in badge["levels"]:
            non_empty = [s for s in group["steps"] if s["text"].strip()]
            assert non_empty, (
                f"{slug} / '{group['name']}': alle stappen zijn leeg"
            )

    def test_niveau_label_default_is_niveau(self, slug):
        badge = _CAT.get(slug)
        if badge.get("type") == "jaarinsigne":
            return
        if badge["category"] != "explorers":
            assert badge["niveau_label"] == "Niveau", (
                f"{slug}: verwacht niveau_label 'Niveau', gevonden '{badge['niveau_label']}'"
            )

    def test_step_green_is_bool(self, slug):
        badge = _CAT.get(slug)
        if badge.get("type") == "jaarinsigne":
            return
        for group in badge["levels"]:
            for step in group["steps"]:
                assert isinstance(step["green"], bool), (
                    f"{slug} / '{group['name']}' step {step['index']} green is not bool"
                )

    def test_groen_true_steps_contain_equals_markers(self, slug):
        badge_path = DATA_DIR / "badges" / f"{slug}.yml"
        raw = yaml.safe_load(badge_path.read_text())
        if raw.get("type") == "jaarinsigne":
            return
        badge = _CAT.get(slug)
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
        if raw.get("type") == "jaarinsigne":
            return
        for group in raw["eisen"]:
            for step in group["eisen"]:
                if isinstance(step, dict):
                    assert "tekst" in step, (
                        f"{slug} / '{group['naam']}': dict step missing 'tekst' key"
                    )


# ── Jaarinsigne-specific structure (runs against real api/data/) ─────────────

_KNOWN_DREMPEL_TYPES = {
    "punten", "groen", "niveau2", "niveau3", "insignes", "leiding_bepaald",
}


@pytest.mark.parametrize("slug", _jaarinsigne_slugs(DATA_DIR))
class TestJaarinsigneStructure:
    """Structural assertions that only apply to ``type: jaarinsigne`` badges.

    These mirror the regular-badge assertions in :class:`TestBadgeStructure`
    that early-return for jaarinsignes (different shape).
    """

    def test_each_level_has_speltak_metadata(self, slug):
        badge = _CAT.get(slug)
        for level in badge["levels"]:
            assert level.get("slug"), f"{slug}: level missing speltak slug"
            assert level.get("name"), (
                f"{slug} / '{level['slug']}': speltak name is empty"
            )
            # leeftijd is optional but should be a string when present
            assert isinstance(level.get("leeftijd", ""), str), (
                f"{slug} / '{level['slug']}': leeftijd must be a string"
            )
            assert isinstance(level.get("level_index"), int), (
                f"{slug} / '{level['slug']}': level_index must be int"
            )

    def test_each_step_has_required_fields(self, slug):
        badge = _CAT.get(slug)
        for level in badge["levels"]:
            for step in level["steps"]:
                assert isinstance(step.get("index"), int), (
                    f"{slug} / '{level['slug']}': step missing int 'index'"
                )
                assert isinstance(step.get("titel", ""), str), (
                    f"{slug} / '{level['slug']}' step {step['index']}: "
                    "titel must be a string"
                )
                assert isinstance(step.get("text", ""), str), (
                    f"{slug} / '{level['slug']}' step {step['index']}: "
                    "text must be a string"
                )
                drempel = step.get("drempel")
                assert drempel is None or isinstance(drempel, dict), (
                    f"{slug} / '{level['slug']}' step {step['index']}: "
                    f"drempel must be a dict or None, got {type(drempel).__name__}"
                )

    def test_each_speltak_eis_has_titel_and_tekst(self, slug):
        """Raw-YAML shape: every speltak eis must be a dict with 'titel' + 'tekst'."""
        raw = yaml.safe_load((DATA_DIR / "badges" / f"{slug}.yml").read_text())
        speltakken = raw.get("speltakken") or {}
        assert speltakken, f"{slug}: 'speltakken' is empty or missing"
        for speltak_slug, eisen in speltakken.items():
            assert isinstance(eisen, list) and eisen, (
                f"{slug} / '{speltak_slug}': eisen must be a non-empty list"
            )
            for i, eis in enumerate(eisen):
                assert isinstance(eis, dict), (
                    f"{slug} / '{speltak_slug}' eis {i}: must be a dict"
                )
                assert "titel" in eis, (
                    f"{slug} / '{speltak_slug}' eis {i}: missing 'titel'"
                )
                assert "tekst" in eis, (
                    f"{slug} / '{speltak_slug}' eis {i}: missing 'tekst'"
                )


# ── jaarinsigne_2026 (drempels are a 2026-specific concept) ───────────────────

class TestJaarinsigne2026Structure:
    """Assertions specific to the jaarinsigne_2026 meta-insigne shape."""

    def test_each_step_drempel_type_is_known(self):
        badge = _CAT.get("jaarinsigne_2026")
        assert badge is not None
        for level in badge["levels"]:
            for step in level["steps"]:
                drempel = step.get("drempel")
                assert drempel is not None, (
                    f"jaarinsigne_2026 / '{level['slug']}' step "
                    f"{step['index']}: drempel missing"
                )
                assert drempel.get("type") in _KNOWN_DREMPEL_TYPES, (
                    f"jaarinsigne_2026 / '{level['slug']}' step "
                    f"{step['index']}: unknown drempel type "
                    f"{drempel.get('type')!r}"
                )
                # All drempels except leiding_bepaald require a numeric minimum
                if drempel["type"] != "leiding_bepaald":
                    minimum = drempel.get("minimum")
                    assert isinstance(minimum, int) and minimum >= 1, (
                        f"jaarinsigne_2026 / '{level['slug']}' step "
                        f"{step['index']}: minimum must be a positive int "
                        f"(got {minimum!r})"
                    )


# ── _parse_step unit tests (no real data dir I/O) ─────────────────────────────

class TestParseStep:
    """Tests for _parse_step logic via BadgeCatalogue on a temporary data dir."""

    def _badge_with_steps(self, tmp_path, *steps):
        """Build a temp data dir with one badge containing the given step strings/dicts."""
        slug = "testbadge"
        (tmp_path / "badges").mkdir()
        (tmp_path / "speltakken.yml").write_text(_SPELTAKKEN_STUB)

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

        (tmp_path / "badges" / f"{slug}.yml").write_text("".join(lines))
        (tmp_path / "badges.yml").write_text(
            f"badges:\n  gewoon:\n    label: Gewone insignes\n    badges:\n      - {slug}\n"
        )

        cat = BadgeCatalogue(tmp_path)
        return cat.get(slug)["levels"][0]["steps"]

    def test_plain_string_step_green_false(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, "gewone tekst")
        assert steps[0]["green"] is False

    def test_plain_string_with_equals_green_true(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, "==groen deel==")
        assert steps[0]["green"] is True

    def test_dict_groen_true_wraps_text(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, {"tekst": "hele stap groen", "groen": True})
        assert steps[0]["green"] is True
        assert "==" in steps[0]["text"]

    def test_dict_groen_false_no_wrap(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, {"tekst": "niet groen", "groen": False})
        assert steps[0]["green"] is False
        assert "==" not in steps[0]["text"]

    def test_dict_groen_true_with_existing_equals_not_double_wrapped(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, {"tekst": "==deels groen==", "groen": True})
        text = steps[0]["text"]
        assert text.count("==") == 2  # exactly one pair

    def test_step_index_is_zero_based(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, "stap a", "stap b", "stap c")
        assert [s["index"] for s in steps] == [0, 1, 2]

    def test_text_is_stripped(self, tmp_path):
        steps = self._badge_with_steps(tmp_path, "  tekst met spaties  ")
        assert steps[0]["text"] == steps[0]["text"].strip()


# ── BadgeCatalogue construction errors ────────────────────────────────────────

class TestBadgeCatalogueErrors:
    def _setup_base(self, tmp_path):
        (tmp_path / "badges").mkdir()
        (tmp_path / "speltakken.yml").write_text(_SPELTAKKEN_STUB)

    def test_missing_index_raises(self, tmp_path):
        self._setup_base(tmp_path)
        with pytest.raises(FileNotFoundError):
            BadgeCatalogue(tmp_path)

    def test_missing_badge_file_raises(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges:\n  gewoon:\n    label: X\n    badges:\n      - phantom\n")
        with pytest.raises(FileNotFoundError):
            BadgeCatalogue(tmp_path)

    def test_malformed_badge_yaml_raises(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges:\n  gewoon:\n    label: X\n    badges:\n      - broken\n")
        (tmp_path / "badges" / "broken.yml").write_text(": [invalid yaml\n")
        with pytest.raises(yaml.YAMLError):
            BadgeCatalogue(tmp_path)

    def test_malformed_index_yaml_raises(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text(": [invalid yaml\n")
        with pytest.raises(yaml.YAMLError):
            BadgeCatalogue(tmp_path)

    def test_empty_index_returns_empty_dict(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        assert BadgeCatalogue(tmp_path).list() == {}

    def test_unknown_slug_returns_none(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        assert BadgeCatalogue(tmp_path).get("nope") is None

    def test_none_nawoord_becomes_empty_string(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges:\n  gewoon:\n    label: X\n    badges:\n      - no_afterword\n")
        (tmp_path / "badges" / "no_afterword.yml").write_text(
            "slug: no_afterword\ntitel: T\nintroductie: intro\neisen: []\n"
        )
        badge = BadgeCatalogue(tmp_path).get("no_afterword")
        assert badge["afterword"] == ""

    def test_explicit_null_nawoord_becomes_empty_string(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges:\n  gewoon:\n    label: X\n    badges:\n      - null_afterword\n")
        (tmp_path / "badges" / "null_afterword.yml").write_text(
            "slug: null_afterword\ntitel: T\nintroductie: intro\nnawoord:\neisen: []\n"
        )
        badge = BadgeCatalogue(tmp_path).get("null_afterword")
        assert badge["afterword"] == ""

    def test_invalid_slug_format_returns_none(self, tmp_path):
        self._setup_base(tmp_path)
        (tmp_path / "badges.yml").write_text("badges: {}\n")
        cat = BadgeCatalogue(tmp_path)
        assert cat.get("../escape") is None
        assert cat.get("FOO") is None
        assert cat.get("foo bar") is None
        assert cat.get("") is None


class TestResolveJaarinsigneLevelIndex:
    """Unit tests for BadgeCatalogue.resolve_jaarinsigne_level_index edge cases."""

    def _make_catalogue(self, tmp_path, speltak_slugs):
        """Build a temp catalogue with a jaarinsigne badge defined for the given speltak slugs."""
        (tmp_path / "badges").mkdir()
        speltakken_lines = "speltakken:\n"
        for s in ["bevers", "welpen", "scouts", "explorers", "roverscouts", "plusscouts"]:
            speltakken_lines += f"  - slug: {s}\n    naam: {s.capitalize()}\n    leeftijd: x\n    kort: {s[0].upper()}\n"
        (tmp_path / "speltakken.yml").write_text(speltakken_lines)

        speltakken_block = ""
        for s in speltak_slugs:
            speltakken_block += f"  {s}:\n    - titel: Eis 1\n      tekst: Doe iets\n"

        (tmp_path / "badges" / "jaar_test.yml").write_text(
            f"slug: jaar_test\ntitel: Jaarbadge Test\ntype: jaarinsigne\nspeltakken:\n{speltakken_block}"
        )
        (tmp_path / "badges.yml").write_text(
            "badges:\n  jaarinsignes:\n    label: Jaarinsignes\n    badges:\n      - jaar_test\n"
        )
        return BadgeCatalogue(tmp_path)

    def test_none_slug_falls_back_to_scouts(self, tmp_path):
        cat = self._make_catalogue(tmp_path, ["welpen", "scouts", "explorers"])
        badge = cat.get("jaar_test")
        assert cat.resolve_jaarinsigne_level_index(badge, None) == 2  # scouts index

    def test_none_slug_no_scouts_returns_first_level(self, tmp_path):
        # scouts not defined — should return first defined level's index
        cat = self._make_catalogue(tmp_path, ["welpen", "explorers"])
        badge = cat.get("jaar_test")
        result = cat.resolve_jaarinsigne_level_index(badge, None)
        assert result == badge["levels"][0]["level_index"]

    def test_none_slug_no_levels_returns_none(self, tmp_path):
        # badge with no speltak levels — build the dict directly to avoid YAML null issue
        cat = self._make_catalogue(tmp_path, ["scouts"])
        badge = cat.get("jaar_test")
        empty_badge = dict(badge, levels=[])
        assert cat.resolve_jaarinsigne_level_index(empty_badge, None) is None

    def test_speltak_slug_falls_back_to_lower_level(self, tmp_path):
        # explorers defined but not roverscouts — roverscouts should fall back to explorers
        cat = self._make_catalogue(tmp_path, ["scouts", "explorers"])
        badge = cat.get("jaar_test")
        result = cat.resolve_jaarinsigne_level_index(badge, "roverscouts")
        assert result == 3  # explorers index in _SPELTAK_ORDER

    def test_plusscouts_falls_back_to_roverscouts(self, tmp_path):
        cat = self._make_catalogue(tmp_path, ["scouts", "roverscouts"])
        badge = cat.get("jaar_test")
        result = cat.resolve_jaarinsigne_level_index(badge, "plusscouts")
        assert result == 4  # roverscouts index

    def test_speltak_slug_not_in_order_returns_none(self, tmp_path):
        # completely unknown speltak slug
        cat = self._make_catalogue(tmp_path, ["scouts"])
        badge = cat.get("jaar_test")
        assert cat.resolve_jaarinsigne_level_index(badge, "onbekend") is None

    def test_bevers_no_lower_fallback_returns_none(self, tmp_path):
        # bevers is the lowest level; if not defined, nothing to fall back to
        cat = self._make_catalogue(tmp_path, ["scouts"])
        badge = cat.get("jaar_test")
        assert cat.resolve_jaarinsigne_level_index(badge, "bevers") is None


class TestJaarinsigneLevelsForScout:
    """Unit tests for jaarinsigne_levels_for_scout helper (issue #122)."""

    def _make_badge(self, level_indices=(1, 2, 3)):
        return {
            "type": "jaarinsigne",
            "levels": [
                {"level_index": idx, "name": f"Level {idx}", "kort": f"L{idx}",
                 "slug": f"l{idx}", "steps": []}
                for idx in level_indices
            ],
        }

    def test_returns_levels_where_progress_exists(self):
        from insigne.badges import jaarinsigne_levels_for_scout
        badge = self._make_badge((1, 2, 3))
        slug_progress = {(1, 0): object(), (3, 1): object()}
        result = jaarinsigne_levels_for_scout(badge, slug_progress, resolved_level_index=2)
        assert [l["level_index"] for l in result] == [1, 3]

    def test_falls_back_to_resolved_when_no_progress(self):
        from insigne.badges import jaarinsigne_levels_for_scout
        badge = self._make_badge((1, 2, 3))
        result = jaarinsigne_levels_for_scout(badge, slug_progress={}, resolved_level_index=2)
        assert [l["level_index"] for l in result] == [2]

    def test_returns_empty_when_no_progress_and_no_resolved(self):
        from insigne.badges import jaarinsigne_levels_for_scout
        badge = self._make_badge((1, 2, 3))
        result = jaarinsigne_levels_for_scout(badge, slug_progress={}, resolved_level_index=None)
        assert result == []

    def test_progress_on_undefined_level_index_is_ignored(self):
        """If progress exists on a level_index that isn't in badge['levels']
        (e.g. stale data), it must not show as a card. The resolved fallback
        kicks in instead."""
        from insigne.badges import jaarinsigne_levels_for_scout
        badge = self._make_badge((1, 2, 3))
        slug_progress = {(99, 0): object()}  # not in (1, 2, 3)
        result = jaarinsigne_levels_for_scout(badge, slug_progress, resolved_level_index=2)
        assert [l["level_index"] for l in result] == [2]
