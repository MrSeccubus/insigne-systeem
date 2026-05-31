import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from markupsafe import Markup, escape

from .config import config
from .eis_render import render_eis_email

_DEFAULT_TEMPLATES = Path(__file__).parent / "email_templates"


# ── HTML → plain text ────────────────────────────────────────────────────────
#
# rspamd flags emails that declare ``multipart/alternative`` but contain only
# an HTML part (MIME_MA_MISSING_TEXT, +2). We auto-generate a plain-text
# alternative from the rendered HTML rather than maintain a parallel .txt
# template for every email — the conversion is good-enough for transactional
# email (login links, sign-off requests, etc.) and any client that prefers
# plain text will get something legible.

_BLOCK_TAGS = {
    "p", "div", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "ul", "ol", "section", "article", "header", "footer", "blockquote",
}
# Only tags whose content should be dropped — and which have proper end tags.
# Void elements (``<meta>``, ``<link>``, ``<br>``) must NOT live here because
# HTMLParser never fires a matching ``handle_endtag`` for them, which would
# leave ``_skip_depth`` stuck above zero and silently drop the rest of the
# document. They have no text content anyway.
_SKIP_TAGS = {"style", "script", "head", "title"}


class _HtmlToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "br":
            self._out.append("\n")
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_text = []
            return
        if tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a":
            text = "".join(self._anchor_text).strip()
            href = (self._href or "").strip()
            # Emit just the visible label (or the URL if the label is empty).
            # The HTML→text similarity check rspamd runs (R_PARTS_DIFFER) is
            # very strict: appending the href in parens after every anchor
            # label adds enough text to drop similarity below threshold.
            # Every transactional template that needs the URL surfaced for
            # plain-text readers includes a fallback ``<a href=X>X</a>``
            # pattern where label == href, so the URL still appears.
            self._out.append(text or href)
            self._href = None
            self._anchor_text = []
            return
        if tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        if self._href is not None:
            self._anchor_text.append(data)
        else:
            self._out.append(data)

    def text(self) -> str:
        raw = "".join(self._out)
        # Collapse runs of spaces/tabs (but preserve newlines), trim each
        # line, then collapse runs of blank lines to a single blank line.
        raw = re.sub(r"[ \t]+", " ", raw)
        lines = [ln.strip() for ln in raw.split("\n")]
        # Drop leading / trailing empty lines.
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        # Collapse multi-blank-line runs.
        out: list[str] = []
        prev_blank = False
        for ln in lines:
            if ln:
                out.append(ln)
                prev_blank = False
            elif not prev_blank:
                out.append("")
                prev_blank = True
        return unescape("\n".join(out))


def html_to_text(html: str) -> str:
    """Strip HTML to a plain-text fallback for ``multipart/alternative``."""
    p = _HtmlToText()
    p.feed(html)
    p.close()
    return p.text()


def _nl2br(value: str) -> Markup:
    return Markup(escape(value).replace("\n", Markup("<br>\n")))


def _env() -> Environment:
    loaders: list = []
    if config.email.templates_dir:
        loaders.append(FileSystemLoader(config.email.templates_dir))
    loaders.append(FileSystemLoader(str(_DEFAULT_TEMPLATES)))
    env = Environment(loader=ChoiceLoader(loaders), autoescape=True)
    env.filters["nl2br"] = _nl2br
    env.filters["render_eis"] = render_eis_email
    return env


_SMTP_TIMEOUT = 10  # seconds — prevents SMTP from blocking indefinitely


def _build_message(to: str, subject: str, html: str) -> EmailMessage:
    """Construct an RFC 5322-compliant ``multipart/alternative`` message.

    Sets ``Date`` and ``Message-ID`` headers explicitly (rspamd flags messages
    missing these). Attaches a plain-text part auto-generated from the HTML so
    the ``multipart/alternative`` wrapper actually has both renderings — a
    multipart/alternative containing only HTML trips MIME_MA_MISSING_TEXT.
    The text content uses quoted-printable encoding (EmailMessage default for
    text/*), which avoids MIME_BASE64_TEXT_BOGUS on the HTML part.
    """
    cfg = config.email
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg.from_name} <{cfg.from_address}>"
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    # Use the from_address domain for the Message-ID so it matches the
    # sending domain (good for DKIM-aligned consistency and trace logs).
    _, _, msgid_domain = cfg.from_address.rpartition("@")
    msg["Message-ID"] = make_msgid(domain=msgid_domain or None)

    # set_content() emits text/plain as the root; add_alternative() then turns
    # the message into multipart/alternative with text first, HTML second.
    # Per RFC 2046 the "best" / richest representation should come last —
    # mail clients pick the last part they support.
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")
    return msg


def _send_smtp(to: str, subject: str, html: str) -> None:
    cfg = config.email
    msg = _build_message(to, subject, html)

    if cfg.security == "ssl":
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=_SMTP_TIMEOUT)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=_SMTP_TIMEOUT)
        if cfg.security == "starttls":
            smtp.starttls()
        else:
            # Submission without TLS makes the relay's Received header show
            # a plaintext hop, which rspamd scores as RCVD_NO_TLS_LAST. Log
            # once per send so operators can spot the configuration.
            logger.warning(
                "SMTP security is 'none' — submission is plaintext. "
                "This will increase recipient spam-score (RCVD_NO_TLS_LAST). "
                "Set email.security to 'starttls' or 'ssl' in config.yml."
            )

    if cfg.username:
        smtp.login(cfg.username, cfg.password)

    smtp.send_message(msg, from_addr=cfg.from_address, to_addrs=[to])
    smtp.quit()


def send(to: str, template_name: str, **context) -> None:
    """Render and send a templated email.

    If smtp_host is empty the message is printed to stdout (dev mode).
    """
    context.setdefault("base_url", config.base_url)
    env = _env()
    subject = env.get_template(f"{template_name}.subject.txt").render(**context).strip()
    html = env.get_template(f"{template_name}.html").render(**context)

    if not config.email.smtp_host:
        print(
            f"\n[DEV EMAIL] To: {to}\n"
            f"[DEV EMAIL] Subject: {subject}\n"
            f"[DEV EMAIL] Template: {template_name} | Context: {context}\n",
            flush=True,
        )
        return

    try:
        _send_smtp(to, subject, html)
    except Exception:
        logger.exception("Failed to send email to %s (template=%s)", to, template_name)


def send_registration_email(to: str, naam: str, code: str) -> None:
    confirm_url = f"{config.base_url}/register/confirm/{quote_plus(code)}"
    send(to, "registration", email=to, naam=naam, code=code, confirm_url=confirm_url)


def send_password_reset_email(to: str, naam: str, code: str) -> None:
    confirm_url = f"{config.base_url}/forgot-password/confirm/{quote_plus(code)}"
    send(to, "password_reset", email=to, naam=naam, code=code, confirm_url=confirm_url)


def send_welcome_email(to: str, naam: str) -> None:
    send(to, "welcome", email=to, naam=naam)


def send_mentor_signoff_invite_email(to: str, scout_name: str, badge_title: str, niveau_number: int, step_text: str, notes: str | None = None) -> None:
    register_url = f"{config.base_url}/register?email={quote_plus(to)}"
    send(to, "mentor_signoff_invite",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         step_text=step_text,
         notes=notes,
         register_url=register_url)


def send_mentor_signoff_request_email(to: str, scout_name: str, badge_title: str, niveau_number: int, step_text: str, notes: str | None = None) -> None:
    signoff_url = f"{config.base_url}/signoff-requests"
    send(to, "mentor_signoff_request",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         step_text=step_text,
         notes=notes,
         signoff_url=signoff_url)


def send_mentor_jaarinsigne_signoff_request_email(
    to: str, scout_name: str, badge_slug: str, badge_title: str,
    speltak_name: str, speltak_leeftijd: str, eisen: list, notes: str | None = None,
) -> None:
    signoff_url = f"{config.base_url}/signoff-requests"
    send(to, "mentor_jaarinsigne_signoff_request",
         email=to,
         scout_name=scout_name,
         badge_slug=badge_slug,
         badge_title=badge_title,
         speltak_name=speltak_name,
         speltak_leeftijd=speltak_leeftijd,
         eisen=eisen,
         notes=notes,
         signoff_url=signoff_url)


def send_mentor_jaarinsigne_signoff_invite_email(
    to: str, scout_name: str, badge_slug: str, badge_title: str,
    speltak_name: str, speltak_leeftijd: str, eisen: list, notes: str | None = None,
) -> None:
    register_url = f"{config.base_url}/register?email={quote_plus(to)}"
    send(to, "mentor_jaarinsigne_signoff_invite",
         email=to,
         scout_name=scout_name,
         badge_slug=badge_slug,
         badge_title=badge_title,
         speltak_name=speltak_name,
         speltak_leeftijd=speltak_leeftijd,
         eisen=eisen,
         notes=notes,
         register_url=register_url)


def send_scout_jaarinsigne_signed_off_email(
    to: str, scout_name: str, badge_slug: str, badge_title: str,
    speltak_name: str, speltak_leeftijd: str, eisen: list,
    mentor_name: str, mentor_comment: str | None = None,
) -> None:
    badge_url = f"{config.base_url}/badges/{badge_slug}"
    send(to, "scout_jaarinsigne_signed_off",
         email=to,
         scout_name=scout_name,
         badge_slug=badge_slug,
         badge_title=badge_title,
         speltak_name=speltak_name,
         speltak_leeftijd=speltak_leeftijd,
         eisen=eisen,
         mentor_name=mentor_name,
         mentor_comment=mentor_comment,
         badge_url=badge_url)


def send_scout_jaarinsigne_rejected_email(
    to: str, scout_name: str, badge_slug: str, badge_title: str,
    speltak_name: str, speltak_leeftijd: str, eisen: list,
    mentor_name: str, message: str,
) -> None:
    badge_url = f"{config.base_url}/badges/{badge_slug}"
    send(to, "scout_jaarinsigne_rejected",
         email=to,
         scout_name=scout_name,
         badge_slug=badge_slug,
         badge_title=badge_title,
         speltak_name=speltak_name,
         speltak_leeftijd=speltak_leeftijd,
         eisen=eisen,
         mentor_name=mentor_name,
         message=message,
         badge_url=badge_url)


def send_scout_signed_off_email(to: str, scout_name: str, badge_slug: str, badge_title: str, niveau_number: int, level_name: str, step_text: str, mentor_name: str, mentor_comment: str | None = None) -> None:
    badge_url = f"{config.base_url}/badges/{badge_slug}?niveau={niveau_number}"
    send(to, "scout_step_signed_off",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         level_name=level_name,
         step_text=step_text,
         mentor_name=mentor_name,
         mentor_comment=mentor_comment,
         badge_url=badge_url)


def send_scout_rejected_email(to: str, scout_name: str, badge_title: str, niveau_number: int, level_name: str, step_text: str, mentor_name: str, message: str) -> None:
    badge_url = f"{config.base_url}/badges"
    send(to, "scout_step_rejected",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         level_name=level_name,
         step_text=step_text,
         mentor_name=mentor_name,
         message=message,
         badge_url=badge_url)


def send_groepsleider_invite_email(to: str, naam: str, inviter_name: str, group_name: str) -> None:
    register_url = f"{config.base_url}/register?email={quote_plus(to)}"
    send(to, "groepsleider_invite",
         email=to, naam=naam, register_url=register_url,
         inviter_name=inviter_name, group_name=group_name)


def send_membership_invite_email(
    to: str, naam: str, inviter_name: str, description: str,
) -> None:
    """Generic invite email for existing users directing them to log in and accept."""
    login_url = f"{config.base_url}/login"
    send(to, "membership_invite",
         email=to, naam=naam, inviter_name=inviter_name,
         description=description, login_url=login_url)


def send_speltak_invite_email(
    to: str, naam: str, inviter_name: str,
    group_name: str, speltak_name: str, role: str,
) -> None:
    register_url = f"{config.base_url}/register?email={quote_plus(to)}"
    send(to, "speltak_invite",
         email=to, naam=naam, register_url=register_url,
         inviter_name=inviter_name, group_name=group_name,
         speltak_name=speltak_name, role=role)


def send_scout_niveau_completed_email(to: str, scout_name: str, badge_title: str, niveau_number: int, badge_slug: str | None = None) -> None:
    badge_url = f"{config.base_url}/badges"
    badge_image_url = f"{config.base_url}/images/{badge_slug}.{niveau_number}.png" if badge_slug else None
    send(to, "scout_niveau_completed",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         badge_url=badge_url,
         badge_image_url=badge_image_url)


def send_membership_request_received_email(
    to: str, naam: str, requester_name: str,
    group_name: str, speltak_name: str | None, group_slug: str,
) -> None:
    requests_url = f"{config.base_url}/groups/{group_slug}/requests"
    send(to, "membership_request_received",
         email=to, naam=naam,
         requester_name=requester_name,
         group_name=group_name,
         speltak_name=speltak_name,
         requests_url=requests_url)


def send_membership_request_approved_email(
    to: str, naam: str, group_name: str, speltak_name: str | None,
) -> None:
    send(to, "membership_request_approved",
         email=to, naam=naam,
         group_name=group_name,
         speltak_name=speltak_name)


def send_membership_request_rejected_email(
    to: str, naam: str, group_name: str, speltak_name: str | None,
) -> None:
    send(to, "membership_request_rejected",
         email=to, naam=naam,
         group_name=group_name,
         speltak_name=speltak_name)


def send_contact_form_email(to: str, sender_email: str, subject: str, body: str) -> None:
    send(to, "contact_form",
         email=to, sender_email=sender_email, subject=subject, body=body)


def send_account_deleted_email(to: str, naam: str) -> None:
    send(to, "account_deleted", email=to, naam=naam)


def send_invite_group_leader_email(
    to: str, invited_by_name: str,
) -> None:
    create_group_url = f"{config.base_url}/groups/new"
    send(to, "invite_group_leader",
         email=to,
         invited_by_name=invited_by_name,
         create_group_url=create_group_url)


def send_email_change_confirm_email(to: str, naam: str, new_email: str, token: str) -> None:
    confirm_url = f"{config.base_url}/profile/email-change/confirm/{quote_plus(token)}"
    send(to, "email_change_confirm",
         email=to, naam=naam, new_email=new_email, confirm_url=confirm_url)


def send_email_change_revert_email(to: str, naam: str, old_email: str, new_email: str, token: str) -> None:
    revert_url = f"{config.base_url}/profile/email-change/revert/{quote_plus(token)}"
    send(to, "email_change_revert",
         email=to, naam=naam, old_email=old_email, new_email=new_email, revert_url=revert_url)
