import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

templates = Jinja2Templates(directory=_FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None
templates.env.globals["dev"] = os.environ.get("INSIGNE_DEV") == "1"
