import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .config import config

_DEFAULT_TEMPLATES = Path(__file__).parent / "email_templates"


def _env() -> Environment:
    loaders: list = []
    if config.email.templates_dir:
        loaders.append(FileSystemLoader(config.email.templates_dir))
    loaders.append(FileSystemLoader(str(_DEFAULT_TEMPLATES)))
    return Environment(loader=ChoiceLoader(loaders), autoescape=True)


def _send_smtp(to: str, subject: str, html: str) -> None:
    cfg = config.email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.from_name} <{cfg.from_address}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    if cfg.security == "ssl":
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
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

    _send_smtp(to, subject, html)


def send_registration_email(to: str, naam: str, code: str) -> None:
    send(to, "registration", email=to, naam=naam, code=code)


def send_password_reset_email(to: str, naam: str, code: str) -> None:
    send(to, "password_reset", email=to, naam=naam, code=code)


def send_welcome_email(to: str, naam: str) -> None:
    send(to, "welcome", email=to, naam=naam)
