"""Poll / voting endpoints."""

import csv
import io

from fastapi import APIRouter, HTTPException, Response

from app import database, state
from app.poll import poll_manager
from app.schemas import StartPollRequest

router = APIRouter(prefix="/api", tags=["poll"])


@router.post("/poll/start")
async def start_poll_api(req: StartPollRequest):
    """Starts a new voting session and broadcasts the poll details."""
    # Server-side validation (the frontend enforces this too, but the API must not trust it).
    if len(req.candidates) < 2:
        raise HTTPException(status_code=400, detail="A poll needs at least 2 candidates")
    for c in req.candidates:
        if not (c.name or "").strip():
            raise HTTPException(status_code=400, detail="Candidate name cannot be empty")
    if req.duration_seconds is not None and req.duration_seconds < 5:
        raise HTTPException(status_code=400, detail="Poll duration must be at least 5 seconds")
    candidates = [c.model_dump() for c in req.candidates]
    try:
        await poll_manager.start_poll(req.title, candidates, req.duration_seconds, req.round_name or "")
    except ValueError as e:
        # e.g. two candidates configured with the same gift (would cause gift leaks)
        raise HTTPException(status_code=400, detail=str(e))

    # Optionally reuse the stored history of the current session: replay
    # comments and gifts that arrived BEFORE the poll started.
    history_applied = {"comments": 0, "gifts": 0, "votes": 0}
    if req.include_history and state.processor.session_id:
        history_applied = await _apply_session_history_to_poll(state.processor.session_id)

    poll_status = await poll_manager.get_status()
    await state.manager.broadcast({
        "type": "poll_update",
        "poll": poll_status
    })
    return {**poll_status, "history_applied": history_applied}


async def _apply_session_history_to_poll(session_id: str) -> dict:
    """
    Replays the stored events of a session through the active poll, so votes
    that arrived before the poll started are counted too. The exact same
    matching rules as live events apply: one comment vote per user, gift
    votes matched by gift name with 1 diamond = 1 vote.
    """
    applied = {"comments": 0, "gifts": 0, "votes": 0}
    events = await database.get_session_events(session_id)
    for event in events:
        data = (event.get("payload") or {}).get("data", {})
        if event["event_type"] == "comment":
            comment_text = data.get("comment", "")
            if await poll_manager.record_vote(event["username"], comment_text):
                applied["comments"] += 1
                applied["votes"] += 1
        elif event["event_type"] == "gift":
            gift_name = data.get("gift_name", "")
            diamond_count = int(data.get("diamond_count") or 0)
            quantity = int(data.get("quantity") or 1)
            # Same streak rules as the live processor: skip mid-streak
            # increments (gift_type=1 & repeat_end=0); the final event
            # carries the full quantity.
            if data.get("gift_type") == 1 and data.get("repeat_end") == 0:
                continue
            success, _candidate_name, votes_added = await poll_manager.record_gift_vote(
                gift_name, max(1, quantity) * max(1, diamond_count)
            )
            if success:
                applied["gifts"] += 1
                applied["votes"] += votes_added
    if applied["votes"]:
        state.logger.info(
            "Poll history replay: %s votes applied from %s comment(s) and %s gift(s)",
            applied["votes"], applied["comments"], applied["gifts"],
        )
    return applied


@router.post("/poll/stop")
async def stop_poll_api():
    """Stops the active voting session, archives its result, and broadcasts the final state."""
    archived = await poll_manager.stop_poll()
    poll_status = await poll_manager.get_status()
    await state.manager.broadcast({
        "type": "poll_update",
        "poll": poll_status
    })
    if archived:
        await state.manager.broadcast({
            "type": "poll_round_archived",
            "round": archived
        })
    return {"poll": poll_status, "archived": archived}


@router.get("/poll/status")
async def get_poll_status_api():
    """Returns the current status and vote counts of the active poll."""
    return await poll_manager.get_status()


@router.get("/poll/rounds")
async def list_poll_rounds_api(limit: int = 100):
    """Returns the archive of completed voting rounds/sessions, most recent first."""
    rounds = await database.get_poll_rounds(limit)
    return {"rounds": rounds}


@router.get("/poll/rounds/export.csv")
async def export_poll_rounds_csv_api():
    """Exports all archived rounds (one row per candidate) as a CSV download."""
    rounds = await database.get_poll_rounds(limit=10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "round_id", "round_name", "title", "started_at", "ended_at",
        "duration_seconds", "total_votes", "candidate_name", "candidate_votes", "candidate_percentage", "gift_name"
    ])
    for r in rounds:
        for c in r.get("candidates", []):
            writer.writerow([
                r.get("id"), r.get("round_name"), r.get("title"),
                r.get("started_at") or "", r.get("ended_at") or "",
                r.get("duration_seconds") if r.get("duration_seconds") is not None else "",
                r.get("total_votes"),
                c.get("name"), c.get("votes"), c.get("percentage"), c.get("gift_name") or ""
            ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=poll-rounds.csv"},
    )


@router.post("/poll/rounds/clear")
async def clear_poll_rounds_api():
    """Deletes all archived rounds."""
    await database.clear_poll_rounds()
    return {"status": "ok"}


@router.delete("/poll/rounds/{round_id}")
async def delete_poll_round_api(round_id: int):
    """Deletes a single archived round."""
    await database.delete_poll_round(round_id)
    return {"status": "ok", "deleted": round_id}

