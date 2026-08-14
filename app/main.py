import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import database
from app.bus import event_bus
from app.models import TikTokEvent
from app.poll import poll_manager
from app.processor import EventProcessor
from app.providers.euler import EulerWebSocketProvider
from app.providers.live import TikTokLiveProvider

def get_base_dir() -> str:
    """Returns the directory containing the executable or the script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
LOG_FILE = os.path.join(DATA_DIR, "app.log")
ENV_FILE = os.path.join(BASE_DIR, ".env")
SOUNDS_DIR = os.path.join(DATA_DIR, "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    ]
)
logger = logging.getLogger("app.main")

# Initialize global components (Managed Cloud WebSockets if API key exists, local fallback otherwise)
sign_api_key = os.getenv("TIKTOK_SIGN_API_KEY")
if not sign_api_key:
    try:
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE) as f:
                for line in f:
                    if line.strip().startswith("TIKTOK_SIGN_API_KEY="):
                        sign_api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    except Exception:  # noqa: BLE001, S110
        pass

if sign_api_key:
    live_provider = EulerWebSocketProvider()
    logger.info("Managed Cloud WebSocket provider initialized.")
else:
    live_provider = TikTokLiveProvider()
    logger.info("Local TikTokLive provider initialized (No API key found).")

processor = EventProcessor()

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
    
    yield
    
    # Shutdown tasks
    logger.info("Shutting down live connections and cleaning up...")
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
    if not await live_provider.is_connected() and not live_provider._is_connecting:
        return {"status": "already_disconnected"}

    await live_provider.disconnect()
    
    if processor.session_id:
        await database.close_session(processor.session_id)
        processor.set_session_id(None)

    return {"status": "disconnected"}

@app.get("/api/status")
async def get_connection_status():
    is_connected = await live_provider.is_connected()
    is_connecting = live_provider._is_connecting
    
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

# Sound Management Endpoints
@app.get("/api/sounds")
async def list_sounds_api():
    """Lists available sound files in data/sounds."""
    if not os.path.exists(SOUNDS_DIR):
        return {"sounds": []}
    
    files = [f for f in os.listdir(SOUNDS_DIR) if f.lower().endswith((".mp3", ".wav", ".ogg", ".m4a"))]
    return {"sounds": files}

@app.post("/api/upload-sound")
async def upload_sound_api(file: UploadFile = File(...)):
    """Uploads a custom audio file to data/sounds."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp3", ".wav", ".ogg", ".m4a"):
        raise HTTPException(status_code=400, detail="Only audio files (.mp3, .wav, .ogg, .m4a) are allowed")
    
    save_path = os.path.join(SOUNDS_DIR, file.filename)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
        
    logger.info(f"Custom sound file uploaded successfully: {file.filename}")
    return {"status": "success", "filename": file.filename, "url": f"/sounds/{file.filename}"}

# Application Settings Endpoints (.env configuration)
@app.get("/api/settings")
async def get_settings_api():
    """Returns application configuration settings."""
    env_key = os.getenv("TIKTOK_SIGN_API_KEY", "")
    return {
        "tiktok_sign_api_key": env_key
    }

@app.post("/api/settings")
async def update_settings_api(req: SettingsUpdateRequest):
    """Updates .env settings dynamically and reloads runtime variables."""
    new_key = (req.tiktok_sign_api_key or "").strip()
    
    os.environ["TIKTOK_SIGN_API_KEY"] = new_key
    
    try:
        from TikTokLive.client.web.web_settings import WebDefaults
        WebDefaults.tiktok_sign_api_key = new_key
    except Exception:  # noqa: BLE001, S110
        pass
        
    global sign_api_key
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
    return {"status": "success", "tiktok_sign_api_key": new_key}

# Simulated Testing Endpoints
@app.post("/api/test/comment-vote")
async def simulate_comment_vote():
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
