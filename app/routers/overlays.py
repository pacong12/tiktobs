"""OBS overlay registry — the dashboard overlay list is persisted in the DB."""

from fastapi import APIRouter

from app import database

router = APIRouter(prefix="/api", tags=["overlays"])


@router.get("/overlays")
async def get_overlays_api():
    """Returns the enabled OBS overlays in display order."""
    overlays = await database.get_overlays(only_enabled=True)
    return {"overlays": overlays}
