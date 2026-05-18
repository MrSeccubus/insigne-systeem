"""Tests for routers._query.lenient_int."""
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))

from routers._query import lenient_int  # noqa: E402


class TestLenientInt:
    @pytest.mark.parametrize("value, expected", [
        (None, None),
        ("", None),
        ("   ", None),
        ("1", 1),
        ("42", 42),
        ("0", 0),
        # The bug case: URL with a trailing paren copied from inside (parens)
        ("1)", 1),
        ("1)  ", 1),
        ("  1)", 1),
        # Other trailing junk
        ("1abc", 1),
        ("1.5", 1),
        ("1,2", 1),
        # Leading non-digit → None (do not guess intent)
        ("a1", None),
        ("-1", None),
        ("(1", None),
        # All junk → None
        ("abc", None),
        ("---", None),
    ])
    def test_parses_leniently(self, value, expected):
        assert lenient_int(value) == expected
