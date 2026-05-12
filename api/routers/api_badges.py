from pathlib import Path

from fastapi import APIRouter, HTTPException

from insigne.badges import BadgeCatalogue

_CATALOGUE = BadgeCatalogue(Path(__file__).parent.parent / "data")

router = APIRouter(prefix="/badges", tags=["badges"])


@router.get("")
async def list_all_badges():
    return _CATALOGUE.list()


@router.get("/{slug}")
async def get_badge_detail(slug: str):
    badge = _CATALOGUE.get(slug)
    if badge is None:
        raise HTTPException(status_code=404, detail="Badge not found.")
    return badge
