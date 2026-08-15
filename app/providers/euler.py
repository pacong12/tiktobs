import asyncio
import json
import logging
import os

import websockets

from app.providers.base import TikTokProvider

logger = logging.getLogger("app.providers.euler")

class EulerWebSocketProvider(TikTokProvider):
    """
    Managed Cloud WebSocket provider that connects directly to EulerStream's 
    servers to receive pre-parsed TikTok LIVE events, bypassing local IP blocks.
    """
    def __init__(self):
        super().__init__()
        self.username: str | None = None
        self.anchor_id: str | None = None
        self._running_task: asyncio.Task | None = None
        self._should_reconnect = False
        self._reconnect_delay = 2.0
        self._max_reconnect_delay = 20.0
        self._is_connecting = False
        self._is_connected_flag = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3

        # Load API key configuration
        self.api_key = os.getenv("TIKTOK_SIGN_API_KEY")
        if not self.api_key:
            try:
                if os.path.exists(".env"):
                    with open(".env") as f:
                        for line in f:
                            if line.strip().startswith("TIKTOK_SIGN_API_KEY="):
                                self.api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
            except Exception:  # noqa: BLE001, S110
                pass

    async def connect(self, username: str) -> None:
        """Starts the connection loop to EulerStream cloud WebSocket."""
        if self._running_task and not self._running_task.done():
            logger.info("Already connecting. Stopping previous session first.")
            await self.disconnect()

        self.username = username
        self._should_reconnect = True
        self._reconnect_delay = 2.0
        self._reconnect_attempts = 0
        self._running_task = asyncio.create_task(self._run_connection_loop())

    async def _run_connection_loop(self):
        """Asynchronous loop managing connection to EulerStream WebSocket."""
        try:
            self._is_connecting = True
            while self._should_reconnect:
                reconnect_cap = 20.0
                self._reconnect_attempts += 1

                cleaned_username = self.username.strip()
                cleaned_username = cleaned_username.removeprefix("@")

                uri = f"wss://ws.eulerstream.com?uniqueId={cleaned_username}&apiKey={self.api_key}"
                logger.info(f"Connecting to EulerStream managed WebSocket for @{cleaned_username}...")
                await self.emit_event("sys_log", {"message": f"Connecting to @{cleaned_username} via Euler Cloud..."})

                try:
                    async with websockets.connect(uri) as ws:
                        logger.info("Connected to EulerStream WebSocket successfully.")
                        self._is_connected_flag = True
                        self._reconnect_attempts = 0
                        self._reconnect_delay = 2.0

                        # Retrieve initial workerInfo and roomInfo parameters (usually arrive in first 2-3 packets)
                        room_id = "unknown"
                        anchor_id = "unknown"
                        for _ in range(5):
                            try:
                                # Use a short timeout of 1.0s to avoid blocking if fewer messages arrive
                                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                data = json.loads(msg)
                                messages = data.get("messages") or []
                                for m in messages:
                                    m_type = m.get("type")
                                    if m_type == "roomInfo":
                                        room_id = str(m.get("data", {}).get("roomInfo", {}).get("roomId") or room_id)
                                        anchor_id = str(m.get("data", {}).get("user", {}).get("numericUid") or anchor_id)
                                    elif m_type == "workerInfo" and room_id == "unknown":
                                        room_id = str(m.get("data", {}).get("webSocketId") or room_id)
                                
                                # Process the packet so we do not miss any comments/gifts sent in the first second
                                await self._handle_websocket_message(msg)

                                # If we successfully resolved both, we can break early
                                if room_id != "unknown" and anchor_id != "unknown":
                                    break
                            except asyncio.TimeoutError:
                                break

                        self.anchor_id = anchor_id
                        await self.emit_event("sys_log", {"message": f"Connected! Room ID: {room_id}, Creator ID: {anchor_id}"})
                        await self.emit_event("connect", {
                            "room_id": room_id,
                            "username": self.username,
                            "anchor_id": anchor_id
                        })

                        # Listen for incoming JSON events
                        async for message in ws:
                            if not self._should_reconnect:
                                break
                            await self._handle_websocket_message(message)

                except Exception as e:
                    self._is_connected_flag = False
                    logger.exception(f"EulerStream WebSocket connection error for @{self.username}")
                    await self.emit_event("sys_log", {
                        "message": f"Connection error: {e!s}. (Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})"
                    })

                # Check if we exceeded max attempts
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    logger.warning(f"Maximum reconnection attempts ({self._max_reconnect_attempts}) reached. Stopping.")
                    await self.emit_event("sys_log", {"message": f"Reconnection stopped after {self._max_reconnect_attempts} failed attempts."})
                    await self.emit_event("connection_failed", {"error": "Maximum reconnection attempts reached."})
                    self._should_reconnect = False
                    break

                if not self._should_reconnect:
                    break

                # Sleep and double backoff delay
                logger.info(f"Reconnecting in {self._reconnect_delay}s (Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})...")
                await self.emit_event("sys_log", {"message": f"Reconnecting in {self._reconnect_delay}s..."})
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, reconnect_cap)
        finally:
            self._is_connecting = False
            self._is_connected_flag = False

    async def disconnect(self) -> None:
        """Closes the connection loop."""
        logger.info("Requesting disconnect from EulerStream...")
        self._should_reconnect = False

        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None

        self.username = None
        self.anchor_id = None
        self._is_connected_flag = False
        logger.info("Disconnected successfully from EulerStream.")
        await self.emit_event("sys_log", {"message": "Disconnected."})
        await self.emit_event("disconnect", {})

    async def is_connected(self) -> bool:
        """Returns connection state."""
        return self._is_connected_flag

    async def is_connecting(self) -> bool:
        """Returns True while a connection attempt is in progress."""
        return self._is_connecting

    async def _handle_websocket_message(self, message: str):
        """Translates raw EulerStream events into standard normalized schema."""
        try:
            data = json.loads(message)
            messages = data.get("messages") or []
            for m in messages:
                m_type = m.get("type")
                m_data = m.get("data") or {}

                if not isinstance(m_data, dict):
                    continue

                user = m_data.get("user") or {}
                unique_id = user.get("uniqueId") or ""
                nickname = user.get("nickname") or unique_id
                msg_id = m_data.get("common", {}).get("msgId") or m_data.get("id") or f"evt_{data.get('timestamp')}_{m_type}"

                if m_type == "WebcastChatMessage":
                    raw_data = {
                        "msg_id": msg_id,
                        "user": {
                            "unique_id": unique_id,
                            "nickname": nickname
                        },
                        "comment": m_data.get("comment") or ""
                    }
                    await self.emit_event("comment", raw_data)

                elif m_type == "WebcastGiftMessage":
                    gift_details = m_data.get("giftDetails") if isinstance(m_data.get("giftDetails"), dict) else {}
                    gift_obj = m_data.get("gift") if isinstance(m_data.get("gift"), dict) else {}
                    gift_id = m_data.get("giftId") or m_data.get("gift_id") or gift_details.get("giftId") or gift_obj.get("id") or 0
                    
                    gift_name = (
                        m_data.get("giftName") or 
                        m_data.get("gift_name") or 
                        gift_details.get("name") or 
                        gift_details.get("giftName") or 
                        gift_obj.get("name") or 
                        m_data.get("describe") or 
                        f"Gift #{gift_id}"
                    )
                    
                    diamond_count = int(
                        m_data.get("diamondCount") or 
                        m_data.get("diamond_count") or 
                        gift_details.get("diamondCount") or 
                        gift_details.get("diamond_count") or 
                        gift_obj.get("diamond_count") or 
                        0
                    )
                    
                    repeat_count = int(
                        m_data.get("repeatCount") or 
                        m_data.get("comboCount") or 
                        m_data.get("repeat_count") or 
                        1
                    )
                    
                    raw_data = {
                        "msg_id": msg_id,
                        "user": {
                            "unique_id": unique_id,
                            "nickname": nickname
                        },
                        "gift_id": gift_id,
                        "gift_name": gift_name,
                        "diamond_count": diamond_count,
                        "quantity": repeat_count,
                        "gift": {
                            "name": gift_name,
                            "diamond_count": diamond_count
                        },
                        "repeat_count": repeat_count
                    }
                    await self.emit_event("gift", raw_data)

                elif m_type == "WebcastLikeMessage":
                    raw_data = {
                        "msg_id": msg_id,
                        "user": {
                            "unique_id": unique_id,
                            "nickname": nickname
                        },
                        "like_count": m_data.get("likeCount") or 1
                    }
                    await self.emit_event("like", raw_data)

                elif m_type == "WebcastSocialMessage":
                    action = m_data.get("action")
                    if action == 1:  # Follow
                        raw_data = {
                            "msg_id": msg_id,
                            "user": {
                                "unique_id": unique_id,
                                "nickname": nickname
                            }
                        }
                        await self.emit_event("follow", raw_data)
                    elif action in (3, 4):  # Share
                        raw_data = {
                            "msg_id": msg_id,
                            "user": {
                                "unique_id": unique_id,
                                "nickname": nickname
                            },
                            "share_target": m_data.get("shareTarget") or m_data.get("target") or ""
                        }
                        await self.emit_event("share", raw_data)

                elif m_type in ("WebcastRoomUserSeqMessage", "WebcastRoomUserMessage"):
                    raw_data = {
                        "msg_id": msg_id,
                        "viewer_count": m_data.get("viewerCount") or m_data.get("totalUser") or 0
                    }
                    await self.emit_event("viewer", raw_data)

        except Exception:
            logger.exception("Error decoding EulerStream WebSocket message")
