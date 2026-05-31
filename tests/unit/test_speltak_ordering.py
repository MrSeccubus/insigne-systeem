"""Tests for the speltak_type_order sort key on the Speltak model (#119)."""
from insigne.models import Speltak


def _spk(name: str, speltak_type: str | None) -> Speltak:
    return Speltak(name=name, slug=name.lower(), group_id="g", speltak_type=speltak_type)


class TestSpeltakTypeOrder:
    def test_known_types_sort_in_age_order(self):
        """bevers → welpen → scouts → explorers → roverscouts → plusscouts"""
        speltakken = [
            _spk("Z", "plusscouts"),
            _spk("Y", "bevers"),
            _spk("X", "explorers"),
            _spk("W", "scouts"),
            _spk("V", "welpen"),
            _spk("U", "roverscouts"),
        ]
        ordered = sorted(speltakken, key=lambda s: s.speltak_type_order)
        assert [s.speltak_type for s in ordered] == [
            "bevers", "welpen", "scouts", "explorers", "roverscouts", "plusscouts",
        ]

    def test_unknown_type_sorts_last(self):
        speltakken = [_spk("Onbekend", "andere"), _spk("Bekend", "scouts")]
        ordered = sorted(speltakken, key=lambda s: s.speltak_type_order)
        assert ordered[0].speltak_type == "scouts"
        assert ordered[1].speltak_type == "andere"

    def test_none_type_sorts_last(self):
        """A Speltak with no speltak_type set (legacy data) sorts after known types."""
        speltakken = [_spk("NoType", None), _spk("Scouts", "scouts")]
        ordered = sorted(speltakken, key=lambda s: s.speltak_type_order)
        assert ordered[0].speltak_type == "scouts"
        assert ordered[1].speltak_type is None

    def test_compound_sort_type_then_name(self):
        """When two speltakken share a type, name is the tiebreaker."""
        speltakken = [
            _spk("Z-welpen", "welpen"),
            _spk("A-scouts", "scouts"),
            _spk("A-welpen", "welpen"),
        ]
        ordered = sorted(speltakken, key=lambda s: (s.speltak_type_order, s.name))
        assert [s.name for s in ordered] == ["A-welpen", "Z-welpen", "A-scouts"]
