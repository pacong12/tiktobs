import hashlib
import json
import logging
from datetime import datetime, timezone

from app import database
from app.bus import event_bus
from app.models import TikTokEvent
from app.poll import poll_manager, normalize_gift_name
from app.state import manager

logger = logging.getLogger("app.processor")


def _extract_avatar_url(user_info: dict) -> str:
    """Best-effort extraction of the sender's profile picture URL from a
    TikTok user payload. Handles both a direct url field and the proto
    ImageModel shapes (`avatar_thumb` / `avatar_medium` / ... each carrying
    a `url_list`)."""
    if not isinstance(user_info, dict):
        return ""
    direct = user_info.get("avatar_url") or user_info.get("avatarUrl")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for key in (
        "avatar_thumb", "avatarThumb",
        "avatar_medium", "avatarMedium",
        "avatar_large", "avatarLarge",
        "avatar_jpg", "avatarJpg",
    ):
        img = user_info.get(key)
        if not isinstance(img, dict):
            continue
        urls = img.get("url_list") or img.get("urlList") or []
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and url.strip():
                    return url.strip()
    return ""


class EventProcessor:
    def __init__(self):
        self.session_id: str | None = None

    def set_session_id(self, session_id: str | None):
        """Sets the active database session ID for incoming events."""
        self.session_id = session_id
        logger.info(f"EventProcessor active session updated to: {session_id}")

    async def process_raw_event(self, event_type: str, raw_data: dict) -> None:
        """Processes a raw event: normalizes, validates, persists, and publishes it."""
        # Connection status events are not stored as standard TikTokEvents in the DB
        if event_type in ("sys_log", "connect", "disconnect", "connection_failed"):
            # These will be broadcast/handled separately by the main server loop
            return

        try:
            if not self.session_id:
                logger.warning(f"No active session ID set. Ignoring incoming '{event_type}' event.")
                return

            # 1. Normalize raw event data into standard model
            event = self._normalize(event_type, raw_data)
            if not event:
                logger.debug(f"Normalization skipped or failed for '{event_type}' event.")
                return

            # 2. Validate
            if not event.id or not event.event_type:
                logger.error(f"Event validation failed: missing id or type: {event}")
                return

            # 3. Persist to SQLite
            is_new = await database.insert_event(
                session_id=self.session_id,
                event_id=event.id,
                event_type=event.event_type,
                username=event.username,
                nickname=event.nickname,
                payload=event.model_dump(mode='json'),
                created_at=event.timestamp.isoformat()
            )

            # 4. Publish if not a duplicate
            if is_new:
                logger.debug(f"Successfully processed new event: {event.event_type} - {event.id}")
                await event_bus.publish(event)

                # Check if this comment registers a valid vote in the active poll
                if event.event_type == "comment":
                    comment_text = event.data.get("comment", "")
                    is_vote_registered = await poll_manager.record_vote(event.username, comment_text)
                    if is_vote_registered:
                        poll_status = await poll_manager.get_status()
                        await manager.broadcast({
                            "type": "poll_update",
                            "poll": poll_status
                        })
                elif event.event_type == "gift":
                    gift_name = event.data.get("gift_name", "")
                    diamond_count = int(event.data.get("diamond_count") or 0)
                    quantity = int(event.data.get("quantity") or 1)
                    gift_type = event.data.get("gift_type")
                    repeat_end = event.data.get("repeat_end")

                    # TikTok streak semantics (gift.type == 1): the sender's
                    # combo emits ONE event per increment (repeat_end=0, with a
                    # growing repeat_count) and a FINAL event (repeat_end=1)
                    # carrying the full repeat_count. Counting every increment
                    # AND the final would multiply the total, so votes are only
                    # tallied once, on the final/non-streak event, for
                    # repeat_count x unit_diamonds. Mid-streak events are still
                    # stored/broadcast above for the live feed.
                    is_mid_streak = (gift_type == 1 and repeat_end == 0)

                    if not is_mid_streak:
                        total_diamonds = max(1, quantity) * max(1, diamond_count)
                        success, candidate_name, votes_added, via_comment = await poll_manager.record_gift_vote(
                            gift_name, total_diamonds, username=event.username
                        )
                        if success:
                            poll_status = await poll_manager.get_status()
                            await manager.broadcast({
                                "type": "poll_update",
                                "poll": poll_status
                            })
                            await manager.broadcast({
                                "type": "poll_gift_vote",
                                "username": event.username,
                                "nickname": event.nickname or event.username,
                                "gift_name": gift_name,
                                "diamond_count": total_diamonds,
                                "quantity": quantity,
                                "candidate_name": candidate_name,
                                "votes_added": votes_added,
                                # Sender's profile picture (when TikTok
                                # provides one) for overlays.
                                "avatar_url": event.data.get("avatar_url", ""),
                                # Set only for comment-fallback votes: the gift
                                # matched no candidate and was credited via the
                                # sender's last vote comment.
                                "via_comment": via_comment
                            })
                        elif poll_manager.is_active and normalize_gift_name(gift_name):
                            # Gift sent while a poll is running, but no candidate
                            # owns it AND the sender never voted by comment this
                            # round: it counts for NOBODY. Tell the overlays/admin
                            # so the sender learns how to make a gift count
                            # (comment the candidate number first).
                            logger.info(
                                f"Gift '{gift_name}' from @{event.username} not counted: "
                                f"no matching candidate and no vote comment this round "
                                f"(poll '{poll_manager.round_name}' active)."
                            )
                            await manager.broadcast({
                                "type": "poll_gift_ignored",
                                "username": event.username,
                                "nickname": event.nickname or event.username,
                                "gift_name": gift_name,
                                "diamond_count": total_diamonds,
                                "quantity": quantity,
                                # Sender's profile picture (when TikTok
                                # provides one) for overlays.
                                "avatar_url": event.data.get("avatar_url", ""),
                                "reason": "no_vote_comment"
                            })
            else:
                logger.debug(f"Duplicate event ignored: {event.event_type} - {event.id}")

        except Exception:
            logger.exception(f"Error processing raw event '{event_type}'")

    def _normalize(self, event_type: str, raw_data: dict) -> TikTokEvent | None:
        """Normalizes a raw provider event into a standard TikTokEvent model."""
        # Extract user information
        user_info = raw_data.get("user") if isinstance(raw_data.get("user"), dict) else {}
        username = (
            user_info.get("unique_id") or 
            user_info.get("uniqueId") or 
            user_info.get("display_id") or 
            user_info.get("displayId") or 
            raw_data.get("username") or
            "anonymous"
        )
        nickname = user_info.get("nickname") or user_info.get("nickName") or raw_data.get("nickname") or username
        avatar_url = _extract_avatar_url(user_info)

        # Parse timestamp (fallback to current time if missing or invalid)
        timestamp = datetime.now(timezone.utc)
        if "timestamp" in raw_data:
            try:
                ts = raw_data["timestamp"]
                # Convert milliseconds to seconds if needed
                if ts > 1e11:
                    ts = ts / 1000.0
                timestamp = datetime.fromtimestamp(ts, timezone.utc)
            except Exception:  # noqa: BLE001, S110
                pass

        # Parse type-specific data
        data = {}
        if event_type == "comment":
            data["comment"] = raw_data.get("comment") or raw_data.get("content") or ""
        elif event_type == "gift":
            gift_obj = raw_data.get("gift") if isinstance(raw_data.get("gift"), dict) else {}
            gift_details = raw_data.get("giftDetails") if isinstance(raw_data.get("giftDetails"), dict) else (raw_data.get("gift_details") if isinstance(raw_data.get("gift_details"), dict) else {})
            
            gift_id = str(
                raw_data.get("gift_id") or 
                raw_data.get("giftId") or 
                gift_obj.get("gift_id") or 
                gift_obj.get("giftId") or 
                gift_obj.get("id") or 
                gift_details.get("giftId") or 
                "0"
            )
            
            gift_name = (
                raw_data.get("gift_name") or 
                raw_data.get("giftName") or 
                gift_obj.get("name") or 
                gift_obj.get("gift_name") or 
                gift_obj.get("giftName") or 
                gift_obj.get("describe") or 
                gift_obj.get("describe_str") or 
                gift_details.get("name") or 
                gift_details.get("giftName") or 
                raw_data.get("describe") or 
                raw_data.get("name") or 
                f"Gift #{gift_id}"
            )
            
            quantity = int(
                raw_data.get("quantity") or 
                raw_data.get("repeat_count") or 
                raw_data.get("repeatCount") or 
                raw_data.get("combo_count") or 
                raw_data.get("comboCount") or 
                gift_obj.get("repeat_count") or 
                gift_obj.get("repeatCount") or 
                gift_obj.get("combo_count") or 
                1
            )
            
            diamond_count = int(
                raw_data.get("diamond_count") or 
                raw_data.get("diamondCount") or 
                raw_data.get("diamonds") or 
                gift_obj.get("diamond_count") or 
                gift_obj.get("diamondCount") or 
                gift_obj.get("diamonds") or 
                gift_details.get("diamondCount") or 
                gift_details.get("diamond_count") or 
                0
            )

            # --- TikTok gift schema (WebcastGiftMessage / Gift proto) ---
            # repeat_end: 1 = this is the FINAL event of a streak (carries the
            #   full repeat_count); 0 = mid-streak increment. 0 is meaningful,
            #   so we must NOT use truthy `or` chaining here.
            repeat_end = None
            for key in ("repeat_end", "repeatEnd"):
                if raw_data.get(key) is not None:
                    repeat_end = int(raw_data.get(key))
                    break

            # gift.type: 1 = streakable (combo-able, e.g. Rose, Finger Heart),
            #   anything else = non-streakable (big one-shot gifts like Lion).
            gift_type = None
            for src in (raw_data, gift_obj, gift_details):
                for key in ("gift_type", "type"):
                    v = src.get(key) if isinstance(src, dict) else None
                    if isinstance(v, int):
                        gift_type = v
                        break
                if gift_type is not None:
                    break

            data["gift_id"] = gift_id
            data["gift_name"] = gift_name
            data["quantity"] = quantity
            data["diamond_count"] = diamond_count
            data["repeat_end"] = repeat_end
            data["gift_type"] = gift_type
            if avatar_url:
                data["avatar_url"] = avatar_url
        elif event_type == "like":
            data["count"] = int(raw_data.get("like_count") or raw_data.get("count") or 1)
        elif event_type == "follow":
            data["action"] = "follow"
        elif event_type == "share":
            data["action"] = "share"
            data["share_target"] = raw_data.get("share_target") or raw_data.get("target") or ""
        elif event_type == "viewer":
            data["viewer_count"] = int(
                raw_data.get("viewer_count") or 
                raw_data.get("view_count") or 
                raw_data.get("total") or 
                raw_data.get("total_user") or 
                0
            )
        else:
            return None

        # Build Unique Deterministic ID if not provided
        msg_id = (
            raw_data.get("msg_id") or 
            raw_data.get("id") or 
            raw_data.get("message_id") or 
            raw_data.get("messageId")
        )

        if not msg_id or event_type == "viewer":
            # Generate deterministic hash of core fields
            data_serialized = json.dumps(data, sort_keys=True)
            raw_str = f"{event_type}:{username or ''}:{timestamp.isoformat()}:{data_serialized}"
            msg_id = hashlib.md5(raw_str.encode("utf-8")).hexdigest()

        return TikTokEvent(
            id=str(msg_id),
            event_type=event_type,
            username=username,
            nickname=nickname,
            timestamp=timestamp,
            data=data
        )
