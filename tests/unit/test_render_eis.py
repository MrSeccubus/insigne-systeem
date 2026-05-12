"""Tests for the _render_eis Jinja2 filter in api/templates.py."""
import importlib
import sys
from pathlib import Path

import pytest

# Import _render_eis directly without triggering the full FastAPI app startup.
# We add the api/ directory to sys.path so `from insigne.config import config`
# resolves, then import only the rendering helper.
_API_DIR = Path(__file__).parent.parent.parent / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from templates import _render_eis


# ── helpers ──────────────────────────────────────────────────────────────────

def html(text: str) -> str:
    """Return rendered HTML string (strip outer whitespace)."""
    return str(_render_eis(text)).strip()


# ── green spans ──────────────────────────────────────────────────────────────

class TestGreenSpans:
    def test_double_equals_wraps_in_span(self):
        result = html("==groen==")
        assert '<span class="eis-groen">groen</span>' in result

    def test_partial_green_only_marks_segment(self):
        result = html("zwart ==groen== zwart")
        assert '<span class="eis-groen">groen</span>' in result
        assert "zwart" in result

    def test_multiple_green_segments(self):
        result = html("==a== b ==c==")
        assert result.count('<span class="eis-groen">') == 2

    def test_multiline_green_span(self):
        result = html("==eerste regel\ntweede regel==")
        assert '<span class="eis-groen">' in result

    def test_no_equals_no_span(self):
        result = html("gewone tekst")
        assert "eis-groen" not in result


# ── inline markdown ──────────────────────────────────────────────────────────

class TestInlineMarkdown:
    def test_bold_double_asterisk(self):
        result = html("**vet**")
        assert "<strong>vet</strong>" in result

    def test_italic_underscore(self):
        result = html("_cursief_")
        assert "<em>cursief</em>" in result

    def test_italic_asterisk(self):
        result = html("*cursief*")
        assert "<em>cursief</em>" in result

    def test_link_renders_as_anchor(self):
        result = html("[klik hier](https://example.com)")
        assert '<a' in result
        assert 'href="https://example.com"' in result
        assert "klik hier" in result

    def test_link_opens_in_new_tab(self):
        result = html("[link](https://example.com)")
        assert 'target="_blank"' in result
        assert 'rel="noopener noreferrer"' in result


# ── line breaks ──────────────────────────────────────────────────────────────

class TestLineBreaks:
    def test_single_newline_becomes_br(self):
        result = html("eerste\ntweede")
        assert "<br>" in result

    def test_double_newline_becomes_double_br(self):
        result = html("eerste\n\ntweede")
        assert "<br><br>" in result

    def test_no_bare_p_tags(self):
        result = html("tekst\n\nmeer tekst")
        assert "<p>" not in result
        assert "</p>" not in result

    def test_no_trailing_br_slash(self):
        # nl2br emits <br />\n — must be collapsed to <br>
        result = html("eerste\ntweede")
        assert "<br />" not in result


# ── bullet and ordered lists ─────────────────────────────────────────────────

class TestLists:
    def test_bullet_list_renders_ul(self):
        text = "intro\n- item a\n- item b"
        result = html(text)
        assert "<ul>" in result
        assert "<li>" in result

    def test_ordered_list_renders_ol(self):
        text = "intro\n1. eerste\n2. tweede"
        result = html(text)
        assert "<ol>" in result
        assert "<li>" in result

    def test_list_items_contain_text(self):
        text = "intro\n- aap\n- noot"
        result = html(text)
        assert "aap" in result
        assert "noot" in result

    def test_text_after_list_no_extra_blank_line(self):
        # After </ul> there should be exactly one <br>, not <br><br>
        text = "intro\n- item\n\nnajin tekst"
        result = html(text)
        # </ul> should NOT be followed by <br><br> (that would be a blank line)
        assert "</ul><br><br>" not in result

    def test_bullet_list_without_preceding_blank_line(self):
        # _ENSURE_LIST_GAP_RE must insert blank line before list items
        text = "a. Leg de volgende knopen:\n- mastworp\n- paalsteek"
        result = html(text)
        assert "<ul>" in result
        assert "mastworp" in result


# ── no <p> wrappers leaking through ─────────────────────────────────────────

class TestNoPTags:
    def test_plain_text_no_p(self):
        assert "<p>" not in html("gewone tekst")

    def test_multiline_no_p(self):
        assert "<p>" not in html("regel 1\nregel 2\nregel 3")

    def test_blank_line_paragraph_no_p(self):
        assert "<p>" not in html("para 1\n\npara 2")


# ── return type ──────────────────────────────────────────────────────────────

class TestReturnType:
    def test_returns_markup(self):
        from markupsafe import Markup
        assert isinstance(_render_eis("tekst"), Markup)

    def test_empty_string(self):
        result = html("")
        assert result == ""

    def test_whitespace_only(self):
        result = html("   \n  ")
        assert result.strip() == ""
