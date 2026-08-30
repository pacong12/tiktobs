"""Media endpoints: alert sound management and the running-text ticker."""

import json
import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import state
from app.schemas import SoundConfigRequest, TickerConfigRequest

router = APIRouter(prefix="/api", tags=["media"])

# ---------------------------------------------------------------------------
# Sound management
# ---------------------------------------------------------------------------
DEFAULT_SOUND_CONFIG = {
    "gift_sound": "",        # filename in data/sounds, "" = default synth chime
    "vote_sound": "",        # filename for vote-boost alerts
    "gift_volume": 1.0,      # 0.0 - 1.0
    "vote_volume": 1.0,
}


def _load_sound_config():
    """Reads sound_config.json, falling back to defaults for any missing key."""
    cfg = dict(DEFAULT_SOUND_CONFIG)
    if os.path.exists(state.SOUND_CONFIG_FILE):
        try:
            with open(state.SOUND_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_SOUND_CONFIG if k in data})
        except Exception as e:  # noqa: BLE001
            state.logger.warning(f"Could not read sound config, using defaults: {e}")
    return cfg


def _save_sound_config(cfg):
    with open(state.SOUND_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


@router.get("/sounds")
async def list_sounds_api():
    """Lists available sound files plus the current sound configuration."""
    files = []
    if os.path.exists(state.SOUNDS_DIR):
        files = [f for f in os.listdir(state.SOUNDS_DIR) if f.lower().endswith((".mp3", ".wav", ".ogg", ".m4a"))]
        files.sort()
    return {"sounds": files, "config": _load_sound_config()}


@router.get("/sound-config")
async def get_sound_config_api():
    """Returns just the active sound configuration."""
    return _load_sound_config()


@router.post("/sound-config")
async def update_sound_config_api(req: SoundConfigRequest):
    """Updates which sound file + volume each alert type uses. Persisted to disk."""
    cfg = _load_sound_config()

    def _valid(name):
        if not name:
            return True  # empty = default chime
        return os.path.exists(os.path.join(state.SOUNDS_DIR, name))

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
    await state.manager.broadcast({"type": "sound_config_update", "config": cfg})
    state.logger.info(f"Sound config updated: {cfg}")
    return {"status": "success", "config": cfg}


@router.delete("/sounds/{filename}")
async def delete_sound_api(filename: str):
    """Deletes an uploaded sound file. Clears it from config if it was selected."""
    # Prevent path traversal.
    safe_name = os.path.basename(filename)
    target = os.path.join(state.SOUNDS_DIR, safe_name)
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
        await state.manager.broadcast({"type": "sound_config_update", "config": cfg})

    state.logger.info(f"Sound file deleted: {safe_name}")
    return {"status": "success", "deleted": safe_name, "config": cfg}


@router.post("/upload-sound")
async def upload_sound_api(file: UploadFile = File(...)):
    """Uploads a custom audio file to data/sounds."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp3", ".wav", ".ogg", ".m4a"):
        raise HTTPException(status_code=400, detail="Only audio files (.mp3, .wav, .ogg, .m4a) are allowed")

    safe_name = os.path.basename(file.filename)
    save_path = os.path.join(state.SOUNDS_DIR, safe_name)
    content = await file.read()
    # Guard against huge uploads filling up the disk.
    MAX_SOUND_BYTES = 25 * 1024 * 1024  # 25 MB
    if len(content) > MAX_SOUND_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB)")
    with open(save_path, "wb") as f:
        f.write(content)

    state.logger.info(f"Custom sound file uploaded successfully: {safe_name}")
    return {"status": "success", "filename": safe_name, "url": f"/sounds/{safe_name}"}


# ---------------------------------------------------------------------------
# Candidate image upload endpoint
# ---------------------------------------------------------------------------
IMAGES_DIR = os.path.join(state.DATA_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

@router.post("/upload-image")
async def upload_image_api(file: UploadFile = File(...)):
    """Uploads a candidate photo directly in full resolution HD."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(status_code=400, detail="Only image files (.png, .jpg, .jpeg, .webp, .gif) are allowed")

    import uuid
    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    save_path = os.path.join(IMAGES_DIR, safe_name)
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image file too large (max 15 MB)")

    with open(save_path, "wb") as f:
        f.write(content)

    state.logger.info(f"Candidate image uploaded: {safe_name}")
    return {"status": "success", "url": f"/images/{safe_name}"}


# ---------------------------------------------------------------------------
# Running Text / Ticker overlay
# ---------------------------------------------------------------------------
DEFAULT_TICKER_CONFIG = {
    "enabled": True,
    "speed": 60,             # scroll speed in pixels per second
    "direction": "left",     # "left" or "right"
    "separator": "  \u2022  ",   # text shown between messages
    "messages": [],          # one entry per scrolling line (ads, notices, ...)
}


def _load_ticker_config():
    """Reads ticker_config.json, falling back to defaults for any missing key."""
    cfg = dict(DEFAULT_TICKER_CONFIG)
    if os.path.exists(state.TICKER_CONFIG_FILE):
        try:
            with open(state.TICKER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_TICKER_CONFIG if k in data})
        except Exception as e:  # noqa: BLE001
            state.logger.warning(f"Could not read ticker config, using defaults: {e}")
    return cfg


def _save_ticker_config(cfg):
    with open(state.TICKER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


@router.get("/ticker")
async def get_ticker_api():
    """Returns the running-text (ticker) configuration used by /ticker.html."""
    return _load_ticker_config()


@router.post("/ticker")
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
    await state.manager.broadcast({"type": "ticker_update", "config": cfg})
    state.logger.info(f"Ticker config updated: enabled={cfg['enabled']}, messages={len(cfg['messages'])}")
    return {"status": "success", "config": cfg}


DEFAULT_RUNNING_TEXT_CONFIG = {
    "enabled": True,
    "speed": 60,
    "direction": "left",
    "separator": "  •  ",
    "groups": [
        {"title": "INFO", "color": "#ff0055", "message": "Follow & share live stream ini!"},
        {"title": "PROMO", "color": "#00f0ff", "message": "Gift Rose untuk berikan suara!"},
        {"title": "SOSMED", "color": "#7c4dff", "message": "Instagram: @yourhandle"}
    ]
}


def _load_running_text_config():
    cfg = dict(DEFAULT_RUNNING_TEXT_CONFIG)
    if os.path.exists(state.RUNNING_TEXT_CONFIG_FILE):
        try:
            with open(state.RUNNING_TEXT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_RUNNING_TEXT_CONFIG if k in data})
        except Exception as e:  # noqa: BLE001
            state.logger.warning(f"Could not read running text config, using defaults: {e}")
    return cfg


def _save_running_text_config(cfg):
    with open(state.RUNNING_TEXT_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


@router.get("/running-text")
async def get_running_text_api():
    """Returns the configuration for /running-text-overlay.html."""
    return _load_running_text_config()


@router.post("/running-text")
async def update_running_text_api(req: TickerConfigRequest):
    """Updates the running text V2 configuration separately."""
    cfg = _load_running_text_config()

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
    if req.header_title is not None:
        cfg["header_title"] = req.header_title.strip()[:30]
    if req.header_color is not None:
        cfg["header_color"] = req.header_color.strip()[:20]
    if req.groups is not None:
        cleaned_groups = []
        for g in req.groups[:30]:
            t = (g.title or "INFO").strip()[:30]
            c = (g.color or "#ff0055").strip()[:20]
            m = (g.message or "").strip()[:500]
            if m:
                cleaned_groups.append({"title": t, "color": c, "message": m})
        cfg["groups"] = cleaned_groups
        # Also sync fallback messages array so both schemas stay consistent
        cfg["messages"] = [g["message"] for g in cleaned_groups]
    elif req.messages is not None:
        cleaned = []
        for msg in req.messages[:50]:
            text = str(msg).strip()
            if text:
                cleaned.append(text[:500])
        cfg["messages"] = cleaned

    _save_running_text_config(cfg)
    await state.manager.broadcast({"type": "running_text_update", "config": cfg})
    state.logger.info(f"Running text V2 config updated: enabled={cfg['enabled']}, messages={len(cfg['messages'])}")
    return {"status": "success", "config": cfg}
