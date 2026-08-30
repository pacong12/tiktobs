"""Shared application state.

Everything that used to live at module level in app/main.py and had to be
imported back into app/processor.py and app/poll.py (creating fragile
circular imports) now lives here. Import order matters: the WebSocket
ConnectionManager is defined FIRST so that modules imported below
(processor, poll) can safely do `from app.state import manager`.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from fastapi import WebSocket

from app import config, database
from app.bus import event_bus
from app.models import TikTokEvent

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = config.get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
LOG_FILE = os.path.join(DATA_DIR, "app.log")
ENV_FILE = config.ENV_FILE
SOUNDS_DIR = os.path.join(DATA_DIR, "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
SOUND_CONFIG_FILE = os.path.join(DATA_DIR, "sound_config.json")
TICKER_CONFIG_FILE = os.path.join(DATA_DIR, "ticker_config.json")
RUNNING_TEXT_CONFIG_FILE = os.path.join(DATA_DIR, "running_text_config.json")

# --------------------------------------------------------------------------
# Logging (file handler rotates so app.log cannot grow without bound)
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    ]
)
logger = logging.getLogger("app.main")

# --------------------------------------------------------------------------
# Optional API auth token. Empty string = auth disabled (default).
# --------------------------------------------------------------------------
API_TOKEN = (os.getenv("TIKTOBS_API_TOKEN") or "").strip()

# --------------------------------------------------------------------------
# Live provider (Managed Cloud WebSockets if API key exists, local fallback
# otherwise) and the event processor.
# --------------------------------------------------------------------------
sign_api_key = config.load_sign_api_key()

if sign_api_key:
    from app.providers.euler import EulerWebSocketProvider
    live_provider = EulerWebSocketProvider()
    logger.info("Managed Cloud WebSocket provider initialized.")
else:
    from app.providers.live import TikTokLiveProvider
    live_provider = TikTokLiveProvider()
    logger.info("Local TikTokLive provider initialized (No API key found).")

# --------------------------------------------------------------------------
# WebSocket fan-out manager (defined BEFORE the processor import below).
# --------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        dead_connections = []
        # Broadcast concurrently to all connected overlay clients
        async def _send(ws: WebSocket):
            try:
                await ws.send_json(message)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Failed to send websocket message to a client: {e}")
                dead_connections.append(ws)

        await asyncio.gather(*[_send(ws) for ws in list(self.active_connections)], return_exceptions=True)
        for dead in dead_connections:
            self.disconnect(dead)
manager = ConnectionManager()

# --------------------------------------------------------------------------
# Event processor. Assigned by app.main at startup (not created here) so
# that app.processor can import `manager` from this module at top level
# without any import cycle.
# --------------------------------------------------------------------------
processor: "EventProcessor | None" = None  # type: ignore[name-defined]  # noqa: F821

# --------------------------------------------------------------------------
# Event retention: tiktok_events rows older than this many days are purged.
# Set TIKTOBS_RETENTION_DAYS=0 (or negative) to keep events forever.
# --------------------------------------------------------------------------
try:
    RETENTION_DAYS = int(os.getenv("TIKTOBS_RETENTION_DAYS", "7"))
except ValueError:
    RETENTION_DAYS = 7

async def _retention_loop():
    """Purges expired events on startup and then once per day."""
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
            deleted = await database.purge_events_before(cutoff)
            if deleted:
                logger.info(f"Retention purge deleted {deleted} event(s) older than {RETENTION_DAYS} day(s).")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Retention purge failed")
        await asyncio.sleep(24 * 3600)

# --------------------------------------------------------------------------
# EventBus / provider wiring
# --------------------------------------------------------------------------
async def ws_broadcast_subscriber(event: TikTokEvent):
    await manager.broadcast({
        "type": "event",
        "event": event.model_dump(mode='json')
    })

async def handle_provider_event(event_type: str, raw_data: dict):
    """Callback receiving raw events from the TikTok LIVE provider."""
    # Route data events to the processor
    if event_type not in ("sys_log", "connect", "disconnect", "connection_failed"):
        await processor.process_raw_event(event_type, raw_data)
    else:
        # Route control/system logs directly to WebSockets
        if event_type == "sys_log":
            await manager.broadcast({
                "type": "log",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": raw_data.get("message", "")
            })
        elif event_type == "connect":
            await manager.broadcast({
                "type": "status",
                "status": "connected",
                "username": raw_data.get("username"),
                "room_id": raw_data.get("room_id"),
                "anchor_id": raw_data.get("anchor_id")
            })
        elif event_type == "disconnect":
            # Update database status if disconnected from stream
            if processor.session_id:
                await database.close_session(processor.session_id)
                processor.set_session_id(None)
            await manager.broadcast({
                "type": "status",
                "status": "disconnected"
            })
        elif event_type == "connection_failed":
            if processor.session_id:
                await database.close_session(processor.session_id)
                processor.set_session_id(None)
            await manager.broadcast({
                "type": "status",
                "status": "failed",
                "error": raw_data.get("error", "Unknown error")
            })

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def get_static_dir() -> str:
    """Resolves the static files directory (PyInstaller .exe aware)."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "static")
    return "static"
