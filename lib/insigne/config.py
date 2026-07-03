import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EmailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = "noreply@insigne.nl"
    from_name: str = "Insigne Systeem"
    security: str = "starttls"   # starttls | ssl | none
    templates_dir: str = ""      # optional path to custom templates directory


@dataclass
class RateLimitConfig:
    """Per-IP rate limits on the unauthenticated, e-mail-sending endpoints
    (``/register``, ``/forgot-password``, ``/contact``) to curb inbox bombing
    and contact-form spam. Values are ``limits``-library strings, e.g.
    ``"5/hour"``, ``"10/minute"``, ``"3/day"``.

    Per-IP limiting only sees the real client IP when uvicorn runs behind a
    trusted proxy with ``server.forwarded_allow_ips`` set (uvicorn rewrites
    ``request.client.host`` from ``X-Forwarded-For``); without it every request
    appears to come from the proxy and shares one bucket. Same dependency as
    the fail2ban login log.
    """
    enabled: bool = True
    register: str = "5/hour"
    forgot_password: str = "5/hour"
    contact: str = "10/hour"


@dataclass
class CaptchaConfig:
    """ALTCHA proof-of-work captcha on the unauthenticated form endpoints
    (``/register`` and ``/contact``). Self-hosted, privacy-friendly (no cookies,
    no third party): the browser widget solves a PoW challenge signed by us.

    ``complexity`` is the ALTCHA ``max_number`` — the upper bound of the number
    the client must brute-force. Higher = more bot cost but slower for real
    users (~100k solves in a fraction of a second on a normal device). Requires
    JavaScript in the browser; disable if that is a problem for your audience.
    """
    enabled: bool = True
    complexity: int = 100000


@dataclass
class Config:
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    base_url: str = "http://localhost:8000"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    server_keepalive: int = 2
    # Comma-separated list of trusted proxy IPs (uvicorn ``--forwarded-allow-ips``).
    # Empty string disables proxy-header parsing entirely; the safe default
    # because trusting unrelated upstreams lets clients spoof their source IP.
    # Set to e.g. ``"127.0.0.1"`` when running behind nginx on the same host.
    server_forwarded_allow_ips: str = ""
    admins: list = field(default_factory=list)
    allow_any_user_to_create_groups: bool = True
    email: EmailConfig = field(default_factory=EmailConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    captcha: CaptchaConfig = field(default_factory=CaptchaConfig)


def _load() -> Config:
    path = Path(os.environ.get("INSIGNE_CONFIG", "config.yml"))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise RuntimeError(
            f"Config file not found: {path}\n"
            "Create config.yml in the project root (see CLAUDE.md)."
        )
    data = yaml.safe_load(path.read_text())
    email_data = data.get("email", {})
    rl_data = data.get("rate_limit", {})
    captcha_data = data.get("captcha", {})
    return Config(
        database_url=data["database"]["url"],
        jwt_secret_key=data["jwt"]["secret_key"],
        jwt_algorithm=data["jwt"].get("algorithm", "HS256"),
        jwt_expire_days=data["jwt"].get("expire_days", 30),
        base_url=data.get("base_url", "http://localhost:8000").rstrip("/"),
        server_host=data.get("server", {}).get("host", "127.0.0.1"),
        server_port=int(data.get("server", {}).get("port", 8000)),
        server_keepalive=int(data.get("server", {}).get("keepalive", 2)),
        server_forwarded_allow_ips=str(data.get("server", {}).get("forwarded_allow_ips", "")).strip(),
        admins=[str(e).lower() for e in data.get("admins", [])],
        allow_any_user_to_create_groups=bool(data.get("allow_any_user_to_create_groups", True)),
        email=EmailConfig(
            smtp_host=email_data.get("smtp_host", ""),
            smtp_port=int(email_data.get("smtp_port", 587)),
            username=email_data.get("username", ""),
            password=email_data.get("password", ""),
            from_address=email_data.get("from_address", "noreply@insigne.nl"),
            from_name=email_data.get("from_name", "Insigne Systeem"),
            security=email_data.get("security", "starttls"),
            templates_dir=email_data.get("templates_dir", ""),
        ),
        rate_limit=RateLimitConfig(
            enabled=bool(rl_data.get("enabled", True)),
            register=str(rl_data.get("register", "5/hour")),
            forgot_password=str(rl_data.get("forgot_password", "5/hour")),
            contact=str(rl_data.get("contact", "10/hour")),
        ),
        captcha=CaptchaConfig(
            enabled=bool(captcha_data.get("enabled", True)),
            complexity=int(captcha_data.get("complexity", 100000)),
        ),
    )


config = _load()
