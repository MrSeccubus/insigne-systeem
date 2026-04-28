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
        # v0.8.0-0-gabcdef1 (on tag) or v0.8.0-3-gabcdef1 (3 commits ahead)
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


# Computed once at startup — never blocks
APP_VERSION: str = _compute_version()

_cache: dict = {"version": None, "checked_at": None}
_cache_lock = threading.Lock()


def _refresh_github_in_background() -> None:
    def _fetch():
        import httpx
        api_url = _github_api_url()
        if not api_url:
            return
        try:
            r = httpx.get(api_url, timeout=5,
                          headers={"Accept": "application/vnd.github+json"})
            latest = r.json().get("tag_name") if r.status_code == 200 else None
        except Exception:
            latest = None
        now = datetime.now()
        with _cache_lock:
            if latest is not None:
                _cache["version"] = latest
            _cache["checked_at"] = now

    threading.Thread(target=_fetch, daemon=True).start()


def get_newer_release() -> str | None:
    """Return the latest GitHub release tag if newer than APP_VERSION, else None.

    Non-blocking: triggers a background refresh when the cache is stale and
    returns whatever was last cached (None on the first call).
    """
    with _cache_lock:
        latest = _cache["version"]
        checked_at = _cache["checked_at"]

    if not checked_at or datetime.now() - checked_at >= timedelta(hours=1):
        _refresh_github_in_background()

    if not latest:
        return None
    current_tag = APP_VERSION.split("+")[0]
    if _parse_version(latest) > _parse_version(current_tag):
        return latest
    return None
