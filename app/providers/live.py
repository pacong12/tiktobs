import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    FollowEvent,
    GiftEvent,
    LikeEvent,
    RoomUserSeqEvent,
    ShareEvent,
)

from app.providers.base import TikTokProvider

logger = logging.getLogger("app.providers.live")

class StreamOfflineError(Exception):
    """Exception raised when attempting to connect to an offline stream."""

def serialize_object(obj: Any) -> Any:
    """Recursively serializes complex objects (including Datetime, Betterproto messages, Pydantic, etc.) into json-compatible dicts."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple, set)):
        return [serialize_object(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): serialize_object(v) for k, v in obj.items()}
    if isinstance(obj, bytes):
        return obj.hex()
    
    # Betterproto support (which TikTokLive uses under the hood)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return serialize_object(obj.to_dict())
        except Exception:  # noqa: BLE001, S110
            pass
            
    # Standard __dict__ serializing
    if hasattr(obj, "__dict__"):
        res = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            res[k] = serialize_object(v)
        return res
        
    return str(obj)

class TikTokLiveProvider(TikTokProvider):
    def __init__(self):
        super().__init__()
        self.client: TikTokLiveClient | None = None
        self.username: str | None = None
        self._running_task: asyncio.Task | None = None
        self._should_reconnect = False
        self._reconnect_delay = 2.0
        self._max_reconnect_delay = 20.0
        self._is_connecting = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3

        # Load API key configuration synchronously on initialization
        sign_api_key = os.getenv("TIKTOK_SIGN_API_KEY")
        if not sign_api_key:
            try:
                if os.path.exists(".env"):
                    with open(".env") as f:
                        for line in f:
                            if line.strip().startswith("TIKTOK_SIGN_API_KEY="):
                                sign_api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
            except Exception:  # noqa: BLE001, S110
                pass

        if sign_api_key:
            WebDefaults.tiktok_sign_api_key = sign_api_key
            logger.info("Using custom EulerStream API key for signature requests.")

    async def connect(self, username: str) -> None:
        """Disconnects any existing sessions and starts a new connection loop task."""
        if self._running_task and not self._running_task.done():
            logger.info("Already running or connecting. Stopping previous session first.")
            await self.disconnect()

        self.username = username
        self._should_reconnect = True
        self._reconnect_delay = 2.0
        self._reconnect_attempts = 0
        self._running_task = asyncio.create_task(self._run_connection_loop())

    async def _run_connection_loop(self):
        """Asynchronous reconnection loop that manages the TikTok LIVE client lifecycle."""
        try:
            self._is_connecting = True
            while self._should_reconnect:
                reconnect_cap = 20.0
                self._reconnect_attempts += 1
                try:
                    cleaned_username = self.username.strip()
                    cleaned_username = cleaned_username.removeprefix("@")

                    logger.info(f"Connecting to TikTok live for username: @{cleaned_username}...")
                    await self.emit_event("sys_log", {"message": f"Connecting to @{cleaned_username}..."})

                    self.client = TikTokLiveClient(unique_id=cleaned_username)
                    
                    # Check if stream is live first to avoid fake connection events
                    try:
                        is_live = await asyncio.wait_for(self.client.is_live(), timeout=5.0)
                        if not is_live:
                            raise StreamOfflineError("Stream is offline")
                    except asyncio.TimeoutError:
                        logger.warning("Timeout checking stream status. Proceeding to connect directly.")
                    except StreamOfflineError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Error checking stream status ({e}). Proceeding to connect directly.")

                    self._register_handlers()
                    
                    # client.start() returns the WebSocket event loop task.
                    # We must await the task to block until the connection terminates.
                    loop_task = await self.client.start()
                    await loop_task
                    self._reconnect_attempts = 0

                except StreamOfflineError:
                    logger.info(f"Connection failed for @{self.username}: User is offline.")
                    await self.emit_event("sys_log", {
                        "message": f"Creator is offline. (Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})"
                    })
                    reconnect_cap = 300.0
                except Exception as e:
                    logger.exception(f"Connection failed for @{self.username}")
                    await self.emit_event("sys_log", {
                        "message": f"Connection error: {e!s}. (Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})"
                    })
                    reconnect_cap = 20.0

                # Check if we exceeded max attempts
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    logger.warning(f"Maximum reconnection attempts ({self._max_reconnect_attempts}) reached. Stopping.")
                    await self.emit_event("sys_log", {"message": f"Reconnection stopped after {self._max_reconnect_attempts} failed attempts."})
                    await self.emit_event("connection_failed", {"error": "Maximum reconnection attempts reached."})
                    self._should_reconnect = False
                    break

                if not self._should_reconnect:
                    break

                # Reconnection wait with exponential backoff
                logger.info(f"Reconnecting to @{self.username} in {self._reconnect_delay}s (Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})...")
                await self.emit_event("sys_log", {"message": f"Reconnecting in {self._reconnect_delay}s..."})
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, reconnect_cap)
        finally:
            self._is_connecting = False

    async def disconnect(self) -> None:
        """Stops connection loop and shuts down client."""
        logger.info("Requesting disconnect...")
        self._should_reconnect = False
        
        if self.client and await self.is_connected():
            try:
                await self.client.disconnect()
            except Exception:
                logger.exception("Error calling disconnect on TikTokLiveClient")

        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None

        self.client = None
        self.username = None
        logger.info("Disconnected successfully.")
        await self.emit_event("sys_log", {"message": "Disconnected."})
        await self.emit_event("disconnect", {})

    async def is_connected(self) -> bool:
        if self.client:
            return getattr(self.client, "connected", False)
        return False

    async def is_connecting(self) -> bool:
        return self._is_connecting

    def _register_handlers(self):
        if not self.client:
            return

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            logger.info(f"Successfully connected to room {event.room_id}")
            self._reconnect_attempts = 0
            await self.emit_event("sys_log", {"message": f"Connected! Room ID: {event.room_id}"})
            await self.emit_event("connect", {
                "room_id": event.room_id,
                "username": self.username
            })
            
            # Reset backoff only if the connection stays stable for 10 seconds
            async def reset_delay_after_stable():
                await asyncio.sleep(10)
                if await self.is_connected():
                    self._reconnect_delay = 2.0
                    logger.info("Connection has been stable for 10s. Reconnect delay reset to 2.0s.")

            asyncio.create_task(reset_delay_after_stable())


        @self.client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            logger.info("Received disconnect event from client.")
            await self.emit_event("sys_log", {"message": "Stream connection closed."})
            # Do not emit client-side disconnect callback if we did not trigger it manually,
            # as the reconnect loop will manage that.

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            raw_data = serialize_object(event)
            await self.emit_event("comment", raw_data)

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            raw_data = serialize_object(event)
            await self.emit_event("gift", raw_data)

        @self.client.on(LikeEvent)
        async def on_like(event: LikeEvent):
            raw_data = serialize_object(event)
            await self.emit_event("like", raw_data)

        @self.client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            raw_data = serialize_object(event)
            await self.emit_event("follow", raw_data)

        @self.client.on(ShareEvent)
        async def on_share(event: ShareEvent):
            raw_data = serialize_object(event)
            await self.emit_event("share", raw_data)

        @self.client.on(RoomUserSeqEvent)
        async def on_viewer_update(event: RoomUserSeqEvent):
            viewer_count = getattr(event, "total", 0) or getattr(event, "total_user", 0)
            raw_data = serialize_object(event)
            raw_data["viewer_count"] = viewer_count
            await self.emit_event("viewer", raw_data)
