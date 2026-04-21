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
class Config:
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    base_url: str = "http://localhost:8000"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    server_keepalive: int = 2
    admins: list = field(default_factory=list)
    allow_group_creation: bool = True
    email: EmailConfig = field(default_factory=EmailConfig)


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
    return Config(
        database_url=data["database"]["url"],
        jwt_secret_key=data["jwt"]["secret_key"],
        jwt_algorithm=data["jwt"].get("algorithm", "HS256"),
        jwt_expire_days=data["jwt"].get("expire_days", 30),
        base_url=data.get("base_url", "http://localhost:8000").rstrip("/"),
        server_host=data.get("server", {}).get("host", "127.0.0.1"),
        server_port=int(data.get("server", {}).get("port", 8000)),
        server_keepalive=int(data.get("server", {}).get("keepalive", 2)),
        admins=[str(e).lower() for e in data.get("admins", [])],
        allow_group_creation=bool(data.get("allow_group_creation", True)),
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
    )


config = _load()
