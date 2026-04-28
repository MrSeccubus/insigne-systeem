import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

from insigne.config import config

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

templates = Jinja2Templates(directory=_FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None
templates.env.globals["dev"] = os.environ.get("INSIGNE_DEV") == "1"
templates.env.globals["allow_any_user_to_create_groups"] = config.allow_any_user_to_create_groups
