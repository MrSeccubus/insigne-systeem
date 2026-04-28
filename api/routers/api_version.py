from fastapi import APIRouter

from insigne.version import APP_VERSION, get_newer_release

router = APIRouter(prefix="/version", tags=["version"])


@router.get("")
def get_version():
    newer = get_newer_release()
    return {
        "version": APP_VERSION,
        "newer_release": newer,
    }
