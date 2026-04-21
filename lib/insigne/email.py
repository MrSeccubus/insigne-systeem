import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from markupsafe import Markup, escape

from .config import config

_DEFAULT_TEMPLATES = Path(__file__).parent / "email_templates"


def _nl2br(value: str) -> Markup:
    return Markup(escape(value).replace("\n", Markup("<br>\n")))


def _env() -> Environment:
    loaders: list = []
    if config.email.templates_dir:
        loaders.append(FileSystemLoader(config.email.templates_dir))
    loaders.append(FileSystemLoader(str(_DEFAULT_TEMPLATES)))
    env = Environment(loader=ChoiceLoader(loaders), autoescape=True)
    env.filters["nl2br"] = _nl2br
    return env


_SMTP_TIMEOUT = 10  # seconds — prevents SMTP from blocking indefinitely


def _send_smtp(to: str, subject: str, html: str) -> None:
    cfg = config.email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.from_name} <{cfg.from_address}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    if cfg.security == "ssl":
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=_SMTP_TIMEOUT)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=_SMTP_TIMEOUT)
        if cfg.security == "starttls":
            smtp.starttls()

    if cfg.username:
        smtp.login(cfg.username, cfg.password)

    smtp.sendmail(cfg.from_address, [to], msg.as_string())
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
    register_url = f"{config.base_url}/register"
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


def send_groepsleider_invite_email(to: str, naam: str, code: str, inviter_name: str, group_name: str) -> None:
    confirm_url = f"{config.base_url}/register/confirm/{quote_plus(code)}"
    send(to, "groepsleider_invite",
         email=to, naam=naam, code=code, confirm_url=confirm_url,
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
    to: str, naam: str, code: str, inviter_name: str,
    group_name: str, speltak_name: str, role: str,
) -> None:
    confirm_url = f"{config.base_url}/register/confirm/{quote_plus(code)}"
    send(to, "speltak_invite",
         email=to, naam=naam, code=code, confirm_url=confirm_url,
         inviter_name=inviter_name, group_name=group_name,
         speltak_name=speltak_name, role=role)


def send_scout_niveau_completed_email(to: str, scout_name: str, badge_title: str, niveau_number: int) -> None:
    badge_url = f"{config.base_url}/badges"
    send(to, "scout_niveau_completed",
         email=to,
         scout_name=scout_name,
         badge_title=badge_title,
         niveau_number=niveau_number,
         badge_url=badge_url)
