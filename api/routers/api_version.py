from fastapi import APIRouter

from insigne.version import get_app_version, get_newer_release

router = APIRouter(prefix="/version", tags=["version"])


@router.get("")
def get_version():
    newer = get_newer_release()
    return {
        "version": get_app_version(),
        "newer_release": newer,
    }
