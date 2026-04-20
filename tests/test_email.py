from unittest.mock import MagicMock, patch

import pytest

import insigne.email as email_mod
from insigne.email import (
    send,
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
             patch("smtplib.SMTP", return_value=mock_conn) as mock_smtp_cls:
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_smtp_cls.assert_called_once_with("mail.example.com", 587, timeout=email_mod._SMTP_TIMEOUT)
        mock_conn.starttls.assert_called_once()

    def test_ssl_creates_smtp_ssl_and_skips_starttls(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 465), \
             patch.object(email_mod.config.email, "security", "ssl"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl_cls:
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_ssl_cls.assert_called_once_with("mail.example.com", 465, timeout=email_mod._SMTP_TIMEOUT)
        mock_conn.starttls.assert_not_called()

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

    def test_sendmail_and_quit_called(self):
        mock_conn = MagicMock()
        with patch.object(email_mod.config.email, "smtp_host", "mail.example.com"), \
             patch.object(email_mod.config.email, "smtp_port", 587), \
             patch.object(email_mod.config.email, "security", "starttls"), \
             patch.object(email_mod.config.email, "username", ""), \
             patch("smtplib.SMTP", return_value=mock_conn):
            email_mod._send_smtp("to@example.com", "Subject", "<p>body</p>")
        mock_conn.sendmail.assert_called_once()
        mock_conn.quit.assert_called_once()


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
