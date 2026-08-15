"""Event data endpoints: recent events, clear stream, gift leaderboard."""

from fastapi import APIRouter

from app import database, state

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events/recent")
async def get_recent_events_api():
    """Returns the last 100 events stored in the SQLite database."""
    events = await database.get_recent_events(limit=100)
    return events


@router.post("/events/clear")
async def clear_events_api():
    """Deletes all stored events and tells every client to clear its stream.

    Destructive by design: the dashboard "Clear" button calls this. It also
    resets the gift leaderboard, which aggregates these same events.
    """
    deleted = await database.clear_events()
    await state.manager.broadcast({"type": "stream_cleared"})
    state.logger.info(f"Event stream cleared via API ({deleted} event(s) deleted).")
    return {"status": "ok", "deleted": deleted}


@router.get("/leaderboard")
async def get_leaderboard_api(scope: str = "session"):
    """
    Returns the aggregated gift leaderboard.

    scope=session (default): only gifts from the active session.
    scope=all: reuses the full stored history, i.e. gifts from every
    session still in the database (subject to the retention purge).
    """
    if scope == "all":
        return await database.get_all_time_leaderboard()
    session_id = state.processor.session_id
    if not session_id:
        return []
    return await database.get_session_leaderboard(session_id)
