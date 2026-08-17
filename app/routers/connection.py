"""Connection management endpoints: connect, disconnect, status."""

from fastapi import APIRouter, HTTPException

from app import database, state, version
from app.schemas import ConnectRequest

router = APIRouter(prefix="/api", tags=["connection"])


@router.post("/connect")
async def connect_to_live(req: ConnectRequest):
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    # If there's an active session, close it in the database
    if state.processor.session_id:
        await database.close_session(state.processor.session_id)
        state.processor.set_session_id(None)

    # Disconnect previous if already running
    if await state.live_provider.is_connected():
        await state.live_provider.disconnect()

    # Start new session
    session_id = await database.create_session(username)
    state.processor.set_session_id(session_id)

    # Connect to stream asynchronously in the background
    await state.live_provider.connect(username)

    return {
        "status": "connecting",
        "session_id": session_id,
        "username": username
    }


@router.post("/disconnect")
async def disconnect_live():
    if not await state.live_provider.is_connected() and not await state.live_provider.is_connecting():
        return {"status": "already_disconnected"}

    await state.live_provider.disconnect()

    if state.processor.session_id:
        await database.close_session(state.processor.session_id)
        state.processor.set_session_id(None)

    return {"status": "disconnected"}


@router.get("/status")
async def get_connection_status():
    is_connected = await state.live_provider.is_connected()
    is_connecting = await state.live_provider.is_connecting()

    status_str = "disconnected"
    if is_connected:
        status_str = "connected"
    elif is_connecting:
        status_str = "connecting"

    return {
        "status": status_str,
        "version": version.__version__,
        "username": state.live_provider.username,
        "session_id": state.processor.session_id,
        "anchor_id": getattr(state.live_provider, "anchor_id", None)
    }
