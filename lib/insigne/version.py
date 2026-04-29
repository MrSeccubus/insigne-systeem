import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent.parent


def _run_git(*args) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=_REPO_DIR, timeout=3
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _compute_version() -> str:
    try:
        desc = _run_git("describe", "--tags", "--long", "--match", "v*")
        parts = desc.rsplit("-", 2)
        if len(parts) == 3:
            tag, commits, _ = parts
            n = int(commits)
            return tag if n == 0 else f"{tag}+{n}"
        return desc
    except Exception:
        return "dev"


def _github_api_url() -> str | None:
    try:
        remote = _run_git("remote", "get-url", "origin")
        if "github.com" not in remote:
            return None
        if remote.startswith("git@"):
            path = remote.split(":", 1)[1].removesuffix(".git")
        else:
            path = remote.split("github.com/", 1)[1].removesuffix(".git")
        return f"https://api.github.com/repos/{path}/releases/latest"
    except Exception:
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.lstrip("v").split(".")[:3])
    except Exception:
        return (0,)


# Startup value — used as fallback before the first background refresh completes
APP_VERSION: str = _compute_version()

_state: dict = {"app_version": APP_VERSION, "github": None, "checked_at": None}
_state_lock = threading.Lock()
_refreshing = False


def _refresh_in_background() -> None:
    global _refreshing
    with _state_lock:
        if _refreshing:
            return
        _refreshing = True

    def _fetch():
        global _refreshing
        try:
            import httpx

            new_version = _compute_version()

            api_url = _github_api_url()
            latest = None
            if api_url:
                try:
                    r = httpx.get(api_url, timeout=5,
                                  headers={"Accept": "application/vnd.github+json"})
                    latest = r.json().get("tag_name") if r.status_code == 200 else None
                except Exception:
                    pass

            now = datetime.now()
            with _state_lock:
                _state["app_version"] = new_version
                if latest is not None:
                    _state["github"] = latest
                _state["checked_at"] = now
        finally:
            with _state_lock:
                _refreshing = False

    threading.Thread(target=_fetch, daemon=True).start()


def get_app_version() -> str:
    """Return the current app version, refreshing from git in the background hourly."""
    with _state_lock:
        v = _state["app_version"]
        checked_at = _state["checked_at"]
    if not checked_at or datetime.now() - checked_at >= timedelta(hours=1):
        _refresh_in_background()
    return v


def get_newer_release() -> str | None:
    """Return the latest GitHub release tag if newer than the current version, else None.

    Non-blocking: triggers a background refresh when the cache is stale.
    """
    with _state_lock:
        latest = _state["github"]
        checked_at = _state["checked_at"]
    if not checked_at or datetime.now() - checked_at >= timedelta(hours=1):
        _refresh_in_background()
    if not latest:
        return None
    current_tag = get_app_version().split("+")[0]
    if _parse_version(latest) > _parse_version(current_tag):
        return latest
    return None


# Fire at import time so the cache is warm before the first request arrives
_refresh_in_background()
