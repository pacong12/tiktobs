"""Application settings (.env) and the EulerStream rankings proxy."""

import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException

from app import state
from app.schemas import SettingsUpdateRequest

router = APIRouter(prefix="/api", tags=["settings"])


def _mask_key(key: str) -> str:
    """Returns a masked representation of an API key that is safe to display."""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "\u2022" * 8 + key[-4:]


@router.get("/auth/status")
async def get_auth_status_api():
    """Reports whether the API requires a token. Exempt from auth itself so
    clients can detect the requirement before they have a token."""
    return {"token_required": bool(state.API_TOKEN)}


@router.get("/settings")
async def get_settings_api():
    """Returns application settings. The raw API key is NEVER returned."""
    env_key = os.getenv("TIKTOK_SIGN_API_KEY", "") or (state.sign_api_key or "")
    return {
        "has_key": bool(env_key),
        "masked_key": _mask_key(env_key),
        "token_required": bool(state.API_TOKEN),
    }


@router.post("/settings")
async def update_settings_api(req: SettingsUpdateRequest):
    """Updates .env settings dynamically and reloads runtime variables.

    Semantics of `tiktok_sign_api_key`:
    - omitted / null  -> nothing changes
    - empty string    -> the stored key is cleared
    - anything else   -> the key is replaced
    """
    if req.tiktok_sign_api_key is None:
        return {
            "status": "unchanged",
            "message": "No key provided; settings left unchanged.",
        }

    had_key = bool(os.getenv("TIKTOK_SIGN_API_KEY", "") or (state.sign_api_key or ""))
    new_key = req.tiktok_sign_api_key.strip()

    os.environ["TIKTOK_SIGN_API_KEY"] = new_key

    try:
        from TikTokLive.client.web.web_settings import WebDefaults
        WebDefaults.tiktok_sign_api_key = new_key
    except Exception:  # noqa: BLE001, S110
        pass

    state.sign_api_key = new_key

    env_path = state.ENV_FILE
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

    state.logger.info("Environment settings updated successfully via API.")
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


@router.get("/rankings")
async def get_rankings_api(anchor_id: str):
    """Queries the EulerStream Rankings API for the given creator (last 30 days)."""
    # Use the globally configured API key
    if not state.sign_api_key:
        raise HTTPException(status_code=400, detail="API Key not configured.")

    now_utc = datetime.now(timezone.utc)
    to_date = now_utc.date().isoformat()
    from_date = (now_utc - timedelta(days=30)).date().isoformat()

    url = f"https://tiktok.eulerstream.com/webcast/rankings/catalog/anchors/{anchor_id}/rank_names"
    headers = {
        "x-api-key": state.sign_api_key
    }
    params = {
        "from": from_date,
        "to": to_date
    }

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=10.0)
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=f"EulerStream API Error: {r.text}")
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Request failed to EulerStream: {e}")
