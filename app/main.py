"""Application entry point: app creation, lifespan wiring and mounts.

All shared runtime state lives in app.state; the HTTP routes live in
app.routers. This module only assembles the pieces.
"""

import asyncio
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import auth, database, state
from app.auth import TokenAuthMiddleware
from app.bus import event_bus
from app.poll import poll_manager
from app.processor import EventProcessor
from app.version import __version__
from app.routers import connection, events, media, overlays, poll, settings, testsim

logger = state.logger

# Create the shared event processor here (state must not import processor
# itself, or processor.py could not import state without a cycle).
state.processor = EventProcessor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("Initializing database and application components...")
    await database.init_db()

    retention_task: asyncio.Task | None = None
    if state.RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(state._retention_loop())
        logger.info(f"Event retention enabled: purging events older than {state.RETENTION_DAYS} day(s).")
    else:
        logger.info("Event retention disabled (TIKTOBS_RETENTION_DAYS <= 0).")

    static_sounds = os.path.join(state.get_static_dir(), "sounds")
    if os.path.exists(static_sounds):
        for f in os.listdir(static_sounds):
            src = os.path.join(static_sounds, f)
            dst = os.path.join(state.SOUNDS_DIR, f)
            if not os.path.exists(dst) and os.path.isfile(src):
                try:
                    shutil.copy2(src, dst)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Could not copy sound {f}: {e}")

    # Set the event callback for the live provider
    state.live_provider.set_event_callback(state.handle_provider_event)

    # Subscribe WebSocket broadcasting to EventBus
    event_bus.subscribe(state.ws_broadcast_subscriber)

    # Restore a poll that was active when the app last shut down (survives restarts).
    await poll_manager.restore()

    yield

    # Shutdown tasks
    logger.info("Shutting down live connections and cleaning up...")
    if retention_task is not None:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
    event_bus.unsubscribe(state.ws_broadcast_subscriber)
    if await state.live_provider.is_connected():
        await state.live_provider.disconnect()
    if state.processor.session_id:
        await database.close_session(state.processor.session_id)
    await database.close_db()


app = FastAPI(
    title="TikTok LIVE Data Collector",
    description="MVP Phase 1: Connection & Realtime Event Collector",
    version=__version__,
    lifespan=lifespan
)

# Middleware: last added = outermost. CORS outermost so even 401 responses
# carry CORS headers; token auth just inside it.
app.add_middleware(TokenAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(connection.router)
app.include_router(events.router)
app.include_router(poll.router)
app.include_router(media.router)
app.include_router(settings.router)
app.include_router(overlays.router)
# The test-endpoint gate is enforced per-request inside the router so the
# disable flag can be toggled at runtime (tests monkeypatch it).
app.include_router(testsim.router)

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not auth.websocket_token_ok(websocket):
        await websocket.close(code=4401)
        return
    await state.manager.connect(websocket)
    try:
        # Keep connection open, ignore incoming client messages for now
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket connection error")
        state.manager.disconnect(websocket)

# Mount static files (Frontend Dashboard)
app.mount("/sounds", StaticFiles(directory=state.SOUNDS_DIR), name="sounds")
app.mount("/", StaticFiles(directory=state.get_static_dir(), html=True), name="static")

# Backwards-compatible aliases (older code/tests imported these from app.main).
manager = state.manager
processor = state.processor
live_provider = state.live_provider
