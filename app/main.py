import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, database
from app.bus import event_bus
from app.models import TikTokEvent
from app.poll import poll_manager
from app.processor import EventProcessor
from app.providers.euler import EulerWebSocketProvider
from app.providers.live import TikTokLiveProvider

def get_base_dir() -> str:
    """Returns the directory containing the executable or the script."""
    return config.get_base_dir()

BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
LOG_FILE = os.path.join(DATA_DIR, "app.log")
ENV_FILE = config.ENV_FILE
SOUNDS_DIR = os.path.join(DATA_DIR, "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
SOUND_CONFIG_FILE = os.path.join(DATA_DIR, "sound_config.json")
TICKER_CONFIG_FILE = os.path.join(DATA_DIR, "ticker_config.json")

# Configure Logging
# The file handler rotates so app.log cannot grow without bound.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    ]
)
logger = logging.getLogger("app.main")

# Initialize global components (Managed Cloud WebSockets if API key exists, local fallback otherwise)
sign_api_key = config.load_sign_api_key()

if sign_api_key:
    live_provider = EulerWebSocketProvider()
    logger.info("Managed Cloud WebSocket provider initialized.")
else:
    live_provider = TikTokLiveProvider()
    logger.info("Local TikTokLive provider initialized (No API key found).")

processor = EventProcessor()

# Event retention: tiktok_events rows older than this many days are purged.
# Set TIKTOBS_RETENTION_DAYS=0 (or negative) to keep events forever.
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
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:  # noqa: BLE001
                # Client disconnected or connection is broken, it will be cleaned up
                logger.debug(f"Failed to send websocket message to a client: {e}")

manager = ConnectionManager()

# EventBus subscriber to push normalized events to all WebSockets
async def ws_broadcast_subscriber(event: TikTokEvent):
    await manager.broadcast({
        "type": "event",
        "event": event.model_dump(mode='json')
    })

# Register callback to receive stream events from TikTok LIVE provider
async def handle_provider_event(event_type: str, raw_data: dict):
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

# Lifespan context manager for startup and shutdown hooks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("Initializing database and application components...")
    await database.init_db()

    retention_task: asyncio.Task | None = None
    if RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(_retention_loop())
        logger.info(f"Event retention enabled: purging events older than {RETENTION_DAYS} day(s).")
    else:
        logger.info("Event retention disabled (TIKTOBS_RETENTION_DAYS <= 0).")
    
    import shutil
    static_sounds = os.path.join(get_static_dir(), "sounds")
    if os.path.exists(static_sounds):
        for f in os.listdir(static_sounds):
            src = os.path.join(static_sounds, f)
            dst = os.path.join(SOUNDS_DIR, f)
            if not os.path.exists(dst) and os.path.isfile(src):
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.warning(f"Could not copy sound {f}: {e}")
                    
    # Set the event callback for the live provider
    live_provider.set_event_callback(handle_provider_event)
    
    # Subscribe WebSocket broadcasting to EventBus
    event_bus.subscribe(ws_broadcast_subscriber)

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
    event_bus.unsubscribe(ws_broadcast_subscriber)
    if await live_provider.is_connected():
        await live_provider.disconnect()
    if processor.session_id:
        await database.close_session(processor.session_id)
    await database.close_db()

app = FastAPI(
    title="TikTok LIVE Data Collector",
    description="MVP Phase 1: Connection & Realtime Event Collector",
    version="1.0.0",
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST Schemas
class ConnectRequest(BaseModel):
    username: str

class CandidateInput(BaseModel):
    name: str
    image_url: str | None = None
    gift_name: str | None = None

class StartPollRequest(BaseModel):
    title: str
    candidates: list[CandidateInput]
    duration_seconds: int | None = None
    round_name: str | None = None

class SettingsUpdateRequest(BaseModel):
    tiktok_sign_api_key: str | None = None

class SoundConfigRequest(BaseModel):
    gift_sound: str | None = None
    vote_sound: str | None = None
    gift_volume: float | None = None
    vote_volume: float | None = None

class TickerConfigRequest(BaseModel):
    enabled: bool | None = None
    speed: int | None = None          # pixels per second (10-300)
    direction: str | None = None      # "left" or "right"
    separator: str | None = None      # text shown between messages
    messages: list[str] | None = None # one entry per scrolling line

# API Routes
@app.post("/api/connect")
async def connect_to_live(req: ConnectRequest):
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    # If there's an active session, close it in the database
    if processor.session_id:
        await database.close_session(processor.session_id)
        processor.set_session_id(None)

    # Disconnect previous if already running
    if await live_provider.is_connected():
        await live_provider.disconnect()

    # Start new session
    session_id = await database.create_session(username)
    processor.set_session_id(session_id)

    # Connect to stream asynchronously in the background
    await live_provider.connect(username)

    return {
        "status": "connecting",
        "session_id": session_id,
        "username": username
    }

@app.post("/api/disconnect")
async def disconnect_live():
    if not await live_provider.is_connected() and not await live_provider.is_connecting():
        return {"status": "already_disconnected"}

    await live_provider.disconnect()
    
    if processor.session_id:
        await database.close_session(processor.session_id)
        processor.set_session_id(None)

    return {"status": "disconnected"}

@app.get("/api/status")
async def get_connection_status():
    is_connected = await live_provider.is_connected()
    is_connecting = await live_provider.is_connecting()
    
    status_str = "disconnected"
    if is_connected:
        status_str = "connected"
    elif is_connecting:
        status_str = "connecting"
        
    return {
        "status": status_str,
        "username": live_provider.username,
        "session_id": processor.session_id,
        "anchor_id": getattr(live_provider, "anchor_id", None)
    }

@app.get("/api/events/recent")
async def get_recent_events_api():
    """Returns the last 100 events stored in the SQLite database."""
    events = await database.get_recent_events(limit=100)
    return events

@app.post("/api/events/clear")
async def clear_events_api():
    """Deletes all stored events and tells every client to clear its stream.

    Destructive by design: the dashboard "Clear" button calls this. It also
    resets the gift leaderboard, which aggregates these same events.
    """
    deleted = await database.clear_events()
    await manager.broadcast({"type": "stream_cleared"})
    logger.info(f"Event stream cleared via API ({deleted} event(s) deleted).")
    return {"status": "ok", "deleted": deleted}

@app.get("/api/leaderboard")
async def get_leaderboard_api():
    """Returns the aggregated gift leaderboard for the active session."""
    session_id = processor.session_id
    if not session_id:
        return []
    leaderboard = await database.get_session_leaderboard(session_id)
    return leaderboard

@app.get("/api/rankings")
async def get_rankings_api(anchor_id: str):
    """Queries the EulerStream Rankings API for the given creator (last 30 days)."""
    # Use the globally configured API key
    if not sign_api_key:
        raise HTTPException(status_code=400, detail="API Key not configured.")

    from datetime import datetime, timedelta, timezone
    now_utc = datetime.now(timezone.utc)
    to_date = now_utc.date().isoformat()
    from_date = (now_utc - timedelta(days=30)).date().isoformat()

    url = f"https://tiktok.eulerstream.com/webcast/rankings/catalog/anchors/{anchor_id}/rank_names"
    headers = {
        "x-api-key": sign_api_key
    }
    params = {
        "from": from_date,
        "to": to_date
    }

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=10.0)
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=f"EulerStream API Error: {r.text}")
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Request failed to EulerStream: {e}")

@app.post("/api/poll/start")
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
    await poll_manager.start_poll(req.title, candidates, req.duration_seconds, req.round_name or "")
    poll_status = await poll_manager.get_status()
    await manager.broadcast({
        "type": "poll_update",
        "poll": poll_status
    })
    return poll_status

@app.post("/api/poll/stop")
async def stop_poll_api():
    """Stops the active voting session, archives its result, and broadcasts the final state."""
    archived = await poll_manager.stop_poll()
    poll_status = await poll_manager.get_status()
    await manager.broadcast({
        "type": "poll_update",
        "poll": poll_status
    })
    if archived:
        await manager.broadcast({
            "type": "poll_round_archived",
            "round": archived
        })
    return {"poll": poll_status, "archived": archived}

@app.get("/api/poll/status")
async def get_poll_status_api():
    """Returns the current status and vote counts of the active poll."""
    return await poll_manager.get_status()

@app.get("/api/poll/rounds")
async def list_poll_rounds_api(limit: int = 100):
    """Returns the archive of completed voting rounds/sessions, most recent first."""
    rounds = await database.get_poll_rounds(limit)
    return {"rounds": rounds}

@app.delete("/api/poll/rounds/{round_id}")
async def delete_poll_round_api(round_id: int):
    """Deletes a single archived round."""
    await database.delete_poll_round(round_id)
    return {"status": "ok", "deleted": round_id}

@app.post("/api/poll/rounds/clear")
async def clear_poll_rounds_api():
    """Deletes all archived rounds."""
    await database.clear_poll_rounds()
    return {"status": "ok"}

@app.get("/api/poll/rounds/export.csv")
async def export_poll_rounds_csv_api():
    """Exports all archived rounds (one row per candidate) as a CSV download."""
    import csv
    import io
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

# Custom Gift Catalog Endpoints (user-added gifts for the Gift Boost dropdown)
class CustomGiftRequest(BaseModel):
    name: str
    diamonds: int | None = None

@app.get("/api/gifts")
async def list_custom_gifts_api():
    """Returns user-added gifts (merged with the built-in catalog on the client)."""
    gifts = await database.get_custom_gifts()
    return {"gifts": gifts}

@app.post("/api/gifts")
async def add_custom_gift_api(req: CustomGiftRequest):
    """Adds (or updates) a user-defined gift."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Gift name cannot be empty")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="Gift name too long (max 60 chars)")
    diamonds = max(0, int(req.diamonds or 0))
    await database.add_custom_gift(name, diamonds)
    return {"status": "success", "gift": {"name": name, "diamonds": diamonds}}

@app.delete("/api/gifts/{name}")
async def delete_custom_gift_api(name: str):
    """Removes a user-defined gift."""
    deleted = await database.delete_custom_gift(name.strip())
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom gift not found")
    return {"status": "success", "deleted": name}

# Sound Management Endpoints
DEFAULT_SOUND_CONFIG = {
    "gift_sound": "",        # filename in data/sounds, "" = default synth chime
    "vote_sound": "",        # filename for vote-boost alerts
    "gift_volume": 1.0,      # 0.0 - 1.0
    "vote_volume": 1.0,
}


def _load_sound_config():
    """Reads sound_config.json, falling back to defaults for any missing key."""
    import json
    cfg = dict(DEFAULT_SOUND_CONFIG)
    if os.path.exists(SOUND_CONFIG_FILE):
        try:
            with open(SOUND_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_SOUND_CONFIG if k in data})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not read sound config, using defaults: {e}")
    return cfg


def _save_sound_config(cfg):
    import json
    with open(SOUND_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


@app.get("/api/sounds")
async def list_sounds_api():
    """Lists available sound files plus the current sound configuration."""
    files = []
    if os.path.exists(SOUNDS_DIR):
        files = [f for f in os.listdir(SOUNDS_DIR) if f.lower().endswith((".mp3", ".wav", ".ogg", ".m4a"))]
        files.sort()
    return {"sounds": files, "config": _load_sound_config()}


@app.get("/api/sound-config")
async def get_sound_config_api():
    """Returns just the active sound configuration."""
    return _load_sound_config()


@app.post("/api/sound-config")
async def update_sound_config_api(req: SoundConfigRequest):
    """Updates which sound file + volume each alert type uses. Persisted to disk."""
    cfg = _load_sound_config()

    def _valid(name):
        if not name:
            return True  # empty = default chime
        return os.path.exists(os.path.join(SOUNDS_DIR, name))

    if req.gift_sound is not None:
        if not _valid(req.gift_sound):
            raise HTTPException(status_code=400, detail=f"Sound file not found: {req.gift_sound}")
        cfg["gift_sound"] = req.gift_sound
    if req.vote_sound is not None:
        if not _valid(req.vote_sound):
            raise HTTPException(status_code=400, detail=f"Sound file not found: {req.vote_sound}")
        cfg["vote_sound"] = req.vote_sound
    if req.gift_volume is not None:
        cfg["gift_volume"] = max(0.0, min(1.0, req.gift_volume))
    if req.vote_volume is not None:
        cfg["vote_volume"] = max(0.0, min(1.0, req.vote_volume))

    _save_sound_config(cfg)
    # Notify open overlays so they reload the new sound live.
    await manager.broadcast({"type": "sound_config_update", "config": cfg})
    logger.info(f"Sound config updated: {cfg}")
    return {"status": "success", "config": cfg}


@app.delete("/api/sounds/{filename}")
async def delete_sound_api(filename: str):
    """Deletes an uploaded sound file. Clears it from config if it was selected."""
    # Prevent path traversal.
    safe_name = os.path.basename(filename)
    target = os.path.join(SOUNDS_DIR, safe_name)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Sound file not found")
    try:
        os.remove(target)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not delete file: {e}")

    cfg = _load_sound_config()
    changed = False
    if cfg.get("gift_sound") == safe_name:
        cfg["gift_sound"] = ""
        changed = True
    if cfg.get("vote_sound") == safe_name:
        cfg["vote_sound"] = ""
        changed = True
    if changed:
        _save_sound_config(cfg)
        await manager.broadcast({"type": "sound_config_update", "config": cfg})

    logger.info(f"Sound file deleted: {safe_name}")
    return {"status": "success", "deleted": safe_name, "config": cfg}


@app.post("/api/upload-sound")
async def upload_sound_api(file: UploadFile = File(...)):
    """Uploads a custom audio file to data/sounds."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp3", ".wav", ".ogg", ".m4a"):
        raise HTTPException(status_code=400, detail="Only audio files (.mp3, .wav, .ogg, .m4a) are allowed")
    
    safe_name = os.path.basename(file.filename)
    save_path = os.path.join(SOUNDS_DIR, safe_name)
    content = await file.read()
    # Guard against huge uploads filling up the disk.
    MAX_SOUND_BYTES = 25 * 1024 * 1024  # 25 MB
    if len(content) > MAX_SOUND_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB)")
    with open(save_path, "wb") as f:
        f.write(content)
        
    logger.info(f"Custom sound file uploaded successfully: {safe_name}")
    return {"status": "success", "filename": safe_name, "url": f"/sounds/{safe_name}"}

# Running Text / Ticker Overlay Endpoints
DEFAULT_TICKER_CONFIG = {
    "enabled": True,
    "speed": 60,             # scroll speed in pixels per second
    "direction": "left",     # "left" or "right"
    "separator": "  \u2022  ",   # text shown between messages
    "messages": [],          # one entry per scrolling line (ads, notices, ...)
}

def _load_ticker_config():
    """Reads ticker_config.json, falling back to defaults for any missing key."""
    import json
    cfg = dict(DEFAULT_TICKER_CONFIG)
    if os.path.exists(TICKER_CONFIG_FILE):
        try:
            with open(TICKER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_TICKER_CONFIG if k in data})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not read ticker config, using defaults: {e}")
    return cfg

def _save_ticker_config(cfg):
    import json
    with open(TICKER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

@app.get("/api/ticker")
async def get_ticker_api():
    """Returns the running-text (ticker) configuration used by /ticker.html."""
    return _load_ticker_config()

@app.post("/api/ticker")
async def update_ticker_api(req: TickerConfigRequest):
    """Updates the ticker configuration, persists it, and notifies open overlays."""
    cfg = _load_ticker_config()

    if req.enabled is not None:
        cfg["enabled"] = req.enabled
    if req.speed is not None:
        if not 10 <= req.speed <= 300:
            raise HTTPException(status_code=400, detail="Speed must be between 10 and 300 px/s")
        cfg["speed"] = req.speed
    if req.direction is not None:
        if req.direction not in ("left", "right"):
            raise HTTPException(status_code=400, detail="Direction must be 'left' or 'right'")
        cfg["direction"] = req.direction
    if req.separator is not None:
        cfg["separator"] = req.separator[:20]
    if req.messages is not None:
        cleaned = []
        for msg in req.messages[:50]:  # cap the number of messages
            text = str(msg).strip()
            if text:
                cleaned.append(text[:500])  # cap each message's length
        cfg["messages"] = cleaned

    _save_ticker_config(cfg)
    # Notify open ticker overlays so they update live.
    await manager.broadcast({"type": "ticker_update", "config": cfg})
    logger.info(f"Ticker config updated: enabled={cfg['enabled']}, messages={len(cfg['messages'])}")
    return {"status": "success", "config": cfg}

# Application Settings Endpoints (.env configuration)
def _mask_key(key: str) -> str:
    """Returns a masked representation of an API key that is safe to display."""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "\u2022" * 8 + key[-4:]

@app.get("/api/settings")
async def get_settings_api():
    """Returns application settings. The raw API key is NEVER returned."""
    env_key = os.getenv("TIKTOK_SIGN_API_KEY", "") or (sign_api_key or "")
    return {
        "has_key": bool(env_key),
        "masked_key": _mask_key(env_key),
    }

@app.post("/api/settings")
async def update_settings_api(req: SettingsUpdateRequest):
    """Updates .env settings dynamically and reloads runtime variables.

    Semantics of `tiktok_sign_api_key`:
    - omitted / null  -> nothing changes
    - empty string    -> the stored key is cleared
    - anything else   -> the key is replaced
    """
    global sign_api_key
    if req.tiktok_sign_api_key is None:
        return {
            "status": "unchanged",
            "message": "No key provided; settings left unchanged.",
        }

    had_key = bool(os.getenv("TIKTOK_SIGN_API_KEY", "") or (sign_api_key or ""))
    new_key = req.tiktok_sign_api_key.strip()
    
    os.environ["TIKTOK_SIGN_API_KEY"] = new_key
    
    try:
        from TikTokLive.client.web.web_settings import WebDefaults
        WebDefaults.tiktok_sign_api_key = new_key
    except Exception:  # noqa: BLE001, S110
        pass
        
    sign_api_key = new_key
    
    env_path = ENV_FILE
    env_data = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_data[k.strip()] = v.strip().strip('"').strip("'")
                    
    env_data["TIKTOK_SIGN_API_KEY"] = new_key
    
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in env_data.items():
            f.write(f'{k}="{v}"\n')
            
    logger.info("Environment settings updated successfully via API.")
    # Switching between "key configured" and "no key" changes which provider
    # the app would use, but the provider is only picked at startup.
    restart_required = had_key != bool(new_key)
    return {
        "status": "success",
        "has_key": bool(new_key),
        "masked_key": _mask_key(new_key),
        "restart_required": restart_required,
        "note": "Restart the app to switch between the cloud and local TikTok provider." if restart_required else None,
    }

# Simulated Testing Endpoints (can be disabled via TIKTOBS_TEST_ENDPOINTS=0)
TEST_ENDPOINTS_ENABLED = os.getenv("TIKTOBS_TEST_ENDPOINTS", "1").strip().lower() not in ("0", "false", "no", "off")

def _require_test_endpoints():
    if not TEST_ENDPOINTS_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Test endpoints are disabled. Set TIKTOBS_TEST_ENDPOINTS=1 to enable them.",
        )

@app.post("/api/test/comment-vote")
async def simulate_comment_vote():
    _require_test_endpoints()
    if not poll_manager.is_active:
        raise HTTPException(status_code=400, detail="No active poll to vote on")
    
    import random
    usernames = ["Ronaldo", "Messi", "Neymar", "Mbappe", "Salah", "Lewandowski", "Kane"]
    user = random.choice(usernames)
    
    candidates = poll_manager.candidates
    if not candidates:
        raise HTTPException(status_code=400, detail="Active poll has no candidates")
    
    c = random.choice(candidates)
    vote_text = random.choice([c["id"], c["name"]])
    
    success = await poll_manager.record_vote(user, vote_text)
    if success:
        poll_status = await poll_manager.get_status()
        await manager.broadcast({
            "type": "poll_update",
            "poll": poll_status
        })
        return {"status": "success", "username": user, "vote": vote_text, "candidate": c["name"]}
    return {"status": "skipped", "message": "User already voted or match failed"}

@app.post("/api/test/gift-vote")
async def simulate_gift_vote():
    _require_test_endpoints()
    if not poll_manager.is_active:
        raise HTTPException(status_code=400, detail="No active poll to vote on")
    
    import random
    usernames = ["GamerGokil", "StreamLover", "SultanChat", "WibuJaya", "PocongImut"]
    user = random.choice(usernames)
    
    candidates_with_gifts = [c for c in poll_manager.candidates if c.get("gift_name")]
    if not candidates_with_gifts:
        # Dynamically auto-assign mock gift triggers for the sake of the simulation!
        mock_gifts = ["Rose", "TikTok", "Finger Heart", "Doughnut"]
        for idx, c in enumerate(poll_manager.candidates):
            c["gift_name"] = mock_gifts[idx % len(mock_gifts)]
        candidates_with_gifts = poll_manager.candidates
    
    c = random.choice(candidates_with_gifts)
    gift_name = c["gift_name"]
    diamond_count = random.choice([5, 10, 50, 99, 299])
    
    success, candidate_name, votes_added = await poll_manager.record_gift_vote(gift_name, diamond_count)
    if success:
        poll_status = await poll_manager.get_status()
        await manager.broadcast({
            "type": "poll_update",
            "poll": poll_status
        })
        await manager.broadcast({
            "type": "poll_gift_vote",
            "username": user,
            "nickname": f"{user} ✨",
            "gift_name": gift_name,
            "diamond_count": diamond_count,
            "candidate_name": candidate_name,
            "votes_added": votes_added
        })
        return {"status": "success", "username": user, "gift": gift_name, "votes": votes_added, "candidate": candidate_name}
    return {"status": "failed"}

@app.post("/api/test/gift-normal")
async def simulate_gift_normal():
    _require_test_endpoints()
    import random
    from datetime import datetime, timezone
    usernames = ["SultanMuda", "BagasGanteng", "RaraKawaii", "DikaGaming", "TiktokUser"]
    user = random.choice(usernames)
    
    gifts = [
        ("Ice Cream", 1, "🍦"),
        ("TikTok", 1, "🎁"),
        ("Finger Heart", 5, "🫰"),
        ("Doughnut", 30, "🍩"),
        ("Cap", 99, "🧢"),
        ("Rose", 1, "🌹"),
        ("Corgi", 399, "🐶")
    ]
    
    poll_gifts = [c.get("gift_name").lower() for c in poll_manager.candidates if c.get("gift_name")]
    available_gifts = [g for g in gifts if g[0].lower() not in poll_gifts]
    if not available_gifts:
        available_gifts = gifts
        
    gift_name, diamond_count, emoji = random.choice(available_gifts)
    quantity = random.choice([1, 1, 2, 5])
    
    event_data = {
        "type": "event",
        "event": {
            "id": f"mock-{random.randint(100000, 999999)}",
            "event_type": "gift",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "username": user,
            "nickname": f"{user} 💎",
            "data": {
                "gift_id": random.randint(1000, 9999),
                "gift_name": gift_name,
                "quantity": quantity,
                "diamond_count": diamond_count
            }
        }
    }
    await manager.broadcast(event_data)
    return {"status": "success", "username": user, "gift": gift_name, "quantity": quantity, "diamonds": diamond_count}

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Keep connection open, ignore incoming client messages for now
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket connection error")
        manager.disconnect(websocket)

# Helper to resolve static files path for PyInstaller .exe bundle
def get_static_dir() -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "static")
    return "static"

# Mount static files (Frontend Dashboard)
app.mount("/sounds", StaticFiles(directory=SOUNDS_DIR), name="sounds")
app.mount("/", StaticFiles(directory=get_static_dir(), html=True), name="static")
