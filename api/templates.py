import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

from insigne.config import config
from insigne.version import APP_VERSION, get_newer_release

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

templates = Jinja2Templates(directory=_FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None
templates.env.globals["dev"] = os.environ.get("INSIGNE_DEV") == "1"
templates.env.globals["allow_any_user_to_create_groups"] = config.allow_any_user_to_create_groups
templates.env.globals["app_version"] = APP_VERSION
templates.env.globals["get_newer_release"] = get_newer_release
