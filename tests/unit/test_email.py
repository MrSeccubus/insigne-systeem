import re
from unittest.mock import MagicMock, patch

import pytest

import insigne.email as email_mod
from insigne.email import (
    send,
    send_account_deleted_email,
    send_mentor_signoff_invite_email,
    send_mentor_signoff_request_email,
    send_password_reset_email,
    send_registration_email,
    send_scout_niveau_completed_email,
    send_scout_rejected_email,
    send_scout_signed_off_email,
    send_welcome_email,
)


# ── send() dev-mode (no smtp_host) ────────────────────────────────────────────

class TestSendDevMode:
    def test_prints_to_stdout_when_no_smtp_host(self, capsys):
        send("scout@example.com", "registration",
             email="scout@example.com", naam="Scout", code="abc123",
             confirm_url="http://localhost/confirm/abc123")
        out = capsys.readouterr().out
        assert "scout@example.com" in out
        assert "registration" in out

    def test_does_not_call_smtp_when_no_host(self):
        with patch("insigne.email._send_smtp") as mock_smtp:
            send("scout@example.com", "registration",
                 email="scout@example.com", naam="Scout", code="abc123",
                 confirm_url="http://localhost/confirm/abc123")
        mock_smtp.assert_not_called()


# ── send() with smtp_host set ─────────────────────────────────────────────────

class TestSendWithSmtpHost:
    def test_calls_send_smtp_when_host_configured(self):
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch("insigne.email._send_smtp") as mock_smtp:
            send("scout@example.com", "registration",
                 email="scout@example.com", naam="Scout", code="abc123",
                 confirm_url="http://localhost/confirm/abc123")
        mock_smtp.assert_called_once()

    def test_passes_recipient_to_send_smtp(self):
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch("insigne.email._send_smtp") as mock_smtp:
            send("scout@example.com", "registration",
                 email="scout@example.com", naam="Scout", code="abc123",
                 confirm_url="http://localhost/confirm/abc123")
        assert mock_smtp.call_args[0][0] == "scout@example.com"


# ── _send_smtp ────────────────────────────────────────────────────────────────

class TestSendSmtp:
    def _smtp_cfg(self, security="starttls", username="", password=""):
        cfg = email_mod.config.email
        patches = {
            "smtp_host": "mail.example.com",
            "smtp_port": 587,
            "security": security,
            "username": username,
            "password": password,
        }
        return patches

    def test_starttls_creates_plain_smtp_and_calls_starttls(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch.object(email_mod.config.email, "from_address", "no-reply@insignesysteem.nl"), \
             patch("smtplib.SMTP", return_value=mock_conn) as mock_smtp_cls:
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_smtp_cls.assert_called_once_with(
            "mail.example.com", 587,
            local_hostname="insignesysteem.nl",
            timeout=email_mod._SMTP_TIMEOUT,
        )
        mock_conn.starttls.assert_called_once()

    def test_ssl_creates_smtp_ssl_and_skips_starttls(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 465), \
             patch.object(email_mod.config.email, "security", "ssl"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch.object(email_mod.config.email, "from_address", "no-reply@insignesysteem.nl"), \
             patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl_cls:
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_ssl_cls.assert_called_once_with(
            "mail.example.com", 465,
            local_hostname="insignesysteem.nl",
            timeout=email_mod._SMTP_TIMEOUT,
        )
        mock_conn.starttls.assert_not_called()

    def test_helo_matches_from_address_domain(self):
        """The HELO name must be the from_address domain so it aligns with
        the DKIM-signing / From-header domain — without this, smtplib uses
        socket.getfqdn() which can be ``127.0.0.1`` or an unrelated host."""
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch.object(email_mod.config.email, "from_address", "noreply@scouting.nl"), \
             patch("smtplib.SMTP", return_value=mock_conn) as mock_smtp_cls:
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        kwargs = mock_smtp_cls.call_args.kwargs
        assert kwargs.get("local_hostname") == "scouting.nl"

    def test_login_called_when_username_set(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", "user@example.com"), \
             patch.object(email_mod.config.email, "password", "secret"), \
             patch("smtplib.SMTP", return_value=mock_conn):
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_conn.login.assert_called_once_with("user@example.com", "secret")

    def test_login_not_called_when_no_username(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch("smtplib.SMTP", return_value=mock_conn):
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_conn.login.assert_not_called()

    def test_send_message_and_quit_called(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch("smtplib.SMTP", return_value=mock_conn):
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_conn.send_message.assert_called_once()
        mock_conn.quit.assert_called_once()


class TestBuildMessage:
    """The constructed ``email.message.EmailMessage`` must satisfy the
    RFC 5322 / rspamd checks that the previous hand-rolled MIME builder
    failed: Message-ID, Date, plain-text alternative, quoted-printable
    text encoding (no base64-encoded HTML)."""

    def test_has_message_id_with_from_domain(self):
        with patch.object(email_mod.config.email, "from_address", "noreply@insignesysteem.nl"), \
             patch.object(email_mod.config.email, "from_name", "Insigne Systeem"):
            msg = email_mod._build_message("to@example.com", "Subject", "<p>hi</p>")
        msgid = msg["Message-ID"]
        assert msgid, "Message-ID header is required by RFC 5322"
        assert msgid.startswith("<") and msgid.endswith(">")
        assert "@insignesysteem.nl>" in msgid

    def test_has_date_header(self):
        with patch.object(email_mod.config.email, "from_address", "noreply@x.test"):
            msg = email_mod._build_message("to@example.com", "Subject", "<p>hi</p>")
        date = msg["Date"]
        assert date, "Date header is required by RFC 5322"
        # ``formatdate(localtime=True)`` produces RFC 5322 §3.6.1 format
        # ending in a numeric timezone offset.
        assert re.search(r"[+\-]\d{4}$", date), f"non-RFC5322 Date: {date}"

    def test_multipart_alternative_has_both_text_and_html(self):
        msg = email_mod._build_message(
            "to@example.com", "Subject",
            "<html><body><p>Hello world</p></body></html>",
        )
        assert msg.is_multipart()
        assert msg.get_content_type() == "multipart/alternative"
        parts = list(msg.iter_parts())
        types = [p.get_content_type() for p in parts]
        # Text first (worse rendering), HTML last per RFC 2046 — the
        # client picks the last part it can render.
        assert types == ["text/plain", "text/html"], (
            f"Expected [text/plain, text/html], got {types}"
        )

    def test_html_part_is_not_base64(self):
        """rspamd MIME_BASE64_TEXT_BOGUS fires when the HTML part uses
        base64. EmailMessage defaults to quoted-printable for text/*."""
        msg = email_mod._build_message(
            "to@example.com", "Subject",
            "<p>Mostly ASCII body with a tilde ~ and emoji 🎉</p>",
        )
        html_part = next(
            p for p in msg.iter_parts() if p.get_content_type() == "text/html"
        )
        cte = html_part["Content-Transfer-Encoding"]
        assert cte != "base64", f"HTML part is base64: {cte}"
        assert cte in ("quoted-printable", "7bit", "8bit")

    def test_text_part_strips_html(self):
        msg = email_mod._build_message(
            "to@example.com", "Subject",
            '<html><body><h1>Hello</h1><p>Visit '
            '<a href="https://example.com/x">our site</a>.</p></body></html>',
        )
        text_part = next(
            p for p in msg.iter_parts() if p.get_content_type() == "text/plain"
        )
        body = text_part.get_content()
        assert "<h1>" not in body and "<p>" not in body
        assert "Hello" in body
        # Anchor with label renders as just the label (rspamd R_PARTS_DIFFER
        # fires if we append "(url)" to every link).
        assert "our site" in body

    def test_subject_from_and_to_headers_set(self):
        with patch.object(email_mod.config.email, "from_address", "noreply@x.test"), \
             patch.object(email_mod.config.email, "from_name", "Insigne Systeem"):
            msg = email_mod._build_message("to@example.com", "Aftekenverzoek", "<p>hi</p>")
        assert msg["Subject"] == "Aftekenverzoek"
        assert msg["From"] == "Insigne Systeem <noreply@x.test>"
        assert msg["To"] == "to@example.com"


class TestHtmlToText:
    def test_block_tags_produce_newlines(self):
        out = email_mod.html_to_text("<p>One</p><p>Two</p>")
        assert "One" in out and "Two" in out
        assert "\n" in out

    def test_br_produces_newline(self):
        out = email_mod.html_to_text("Line 1<br>Line 2")
        assert "Line 1" in out and "Line 2" in out
        assert out.index("Line 1") < out.index("Line 2")

    def test_anchor_renders_only_label(self):
        """rspamd's R_PARTS_DIFFER similarity check compares our plain text
        against the HTML's visible text. Emitting ``label (url)`` for every
        anchor adds enough extra content to drop similarity below the
        threshold. The fallback ``<a href=X>X</a>`` pattern in our templates
        keeps the URL accessible to plain-text readers."""
        out = email_mod.html_to_text('<a href="https://x/y">click here</a>')
        assert "click here" in out
        assert "https://x/y" not in out

    def test_anchor_with_url_label_emits_url_once(self):
        out = email_mod.html_to_text('<a href="https://x/y">https://x/y</a>')
        assert out.count("https://x/y") == 1

    def test_void_tags_dont_suppress_following_content(self):
        """Regression: ``<meta>``, ``<link>``, etc. are void elements with
        no end tag. If we put them in _SKIP_TAGS, _skip_depth would never
        decrement past them and the rest of the document would be silently
        dropped."""
        html = (
            "<html><head>"
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            '<link rel="stylesheet" href="x.css">'
            "</head><body><p>Hello world</p></body></html>"
        )
        out = email_mod.html_to_text(html)
        assert "Hello world" in out

    def test_skips_style_and_script(self):
        out = email_mod.html_to_text(
            "<style>.x{color:red}</style>"
            "<script>alert(1)</script>"
            "<p>Hi</p>",
        )
        assert "color:red" not in out
        assert "alert" not in out
        assert "Hi" in out

    def test_collapses_multiple_blank_lines(self):
        out = email_mod.html_to_text("<p>A</p><p></p><p></p><p>B</p>")
        # No run of more than one consecutive blank line.
        assert "\n\n\n" not in out

    def test_decodes_html_entities(self):
        out = email_mod.html_to_text("<p>Caf&eacute; &amp; bar</p>")
        assert "Café & bar" in out


# ── convenience functions use the correct template ────────────────────────────

class TestConvenienceFunctions:
    def _patched_send(self):
        return patch("insigne.email.send")

    def test_send_registration_email_uses_registration_template(self):
        with self._patched_send() as mock:
            send_registration_email("s@example.com", "Scout", "code123")
        assert mock.call_args[0][1] == "registration"

    def test_send_password_reset_email_uses_password_reset_template(self):
        with self._patched_send() as mock:
            send_password_reset_email("s@example.com", "Scout", "code123")
        assert mock.call_args[0][1] == "password_reset"

    def test_send_welcome_email_uses_welcome_template(self):
        with self._patched_send() as mock:
            send_welcome_email("s@example.com", "Scout")
        assert mock.call_args[0][1] == "welcome"

    def test_send_mentor_signoff_invite_uses_correct_template(self):
        with self._patched_send() as mock:
            send_mentor_signoff_invite_email("m@example.com", "Scout", "Vredeslicht", 1, "Stap tekst")
        assert mock.call_args[0][1] == "mentor_signoff_invite"

    def test_send_mentor_signoff_request_uses_correct_template(self):
        with self._patched_send() as mock:
            send_mentor_signoff_request_email("m@example.com", "Scout", "Vredeslicht", 1, "Stap tekst")
        assert mock.call_args[0][1] == "mentor_signoff_request"

    def test_send_scout_signed_off_uses_correct_template(self):
        with self._patched_send() as mock:
            send_scout_signed_off_email(
                "s@example.com", "Scout", "vredeslicht", "Vredeslicht",
                1, "Niveau 1", "Stap tekst", "Leider Piet"
            )
        assert mock.call_args[0][1] == "scout_step_signed_off"

    def test_send_scout_rejected_uses_correct_template(self):
        with self._patched_send() as mock:
            send_scout_rejected_email(
                "s@example.com", "Scout", "Vredeslicht", 1,
                "Niveau 1", "Stap tekst", "Leider Piet", "Nog niet klaar"
            )
        assert mock.call_args[0][1] == "scout_step_rejected"

    def test_send_scout_niveau_completed_uses_correct_template(self):
        with self._patched_send() as mock:
            send_scout_niveau_completed_email("s@example.com", "Scout", "Vredeslicht", 1)
        assert mock.call_args[0][1] == "scout_niveau_completed"

    def test_registration_confirm_url_contains_code(self):
        with self._patched_send() as mock:
            send_registration_email("s@example.com", "Scout", "my-code")
        kwargs = mock.call_args[1]
        assert "my-code" in kwargs["confirm_url"]

    def test_password_reset_confirm_url_contains_code(self):
        with self._patched_send() as mock:
            send_password_reset_email("s@example.com", "Scout", "reset-code")
        kwargs = mock.call_args[1]
        assert "reset-code" in kwargs["confirm_url"]

    def test_send_account_deleted_uses_correct_template(self):
        with self._patched_send() as mock:
            send_account_deleted_email("s@example.com", "Scout")
        assert mock.call_args[0][1] == "account_deleted"
