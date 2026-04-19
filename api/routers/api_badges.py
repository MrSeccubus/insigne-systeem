from pathlib import Path

from fastapi import APIRouter, HTTPException

from insigne.badges import get_badge, list_badges

_DATA_DIR = Path(__file__).parent.parent / "data"

router = APIRouter(prefix="/badges", tags=["badges"])


@router.get("")
async def list_all_badges():
    return list_badges(_DATA_DIR)


@router.get("/{slug}")
async def get_badge_detail(slug: str):
    badge = get_badge(_DATA_DIR, slug)
    if badge is None:
        raise HTTPException(status_code=404, detail="Badge not found.")
    return badge
