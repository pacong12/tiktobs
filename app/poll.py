import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("app.poll")

class PollManager:
    """
    Manages the active polling state in memory.
    Tracks candidates, votes, and voters to prevent duplicate votes.
    Supports countdown timers and automatic poll stopping.
    """
    def __init__(self):
        self.is_active = False
        self.title = ""
        self.candidates = []  # List of {"id": "1", "name": "Name", "image_url": "...", "votes": 0}
        self.voters = set()   # Set of usernames who have voted
        self.expires_at = None  # datetime | None
        self.timer_task = None  # asyncio.Task | None
        self.lock = asyncio.Lock()

    async def start_poll(self, title: str, candidates: list[dict], duration_seconds: int | None = None) -> None:
        """Starts a new poll and resets all existing votes and voters."""
        async with self.lock:
            # Cancel existing timer task if running
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None

            self.title = title
            self.candidates = []
            for idx, c in enumerate(candidates, start=1):
                name_val = c.get("name") or ""
                img_val = c.get("image_url") or ""
                gift_val = c.get("gift_name") or ""
                self.candidates.append({
                    "id": str(idx),
                    "name": name_val.strip(),
                    "image_url": img_val.strip(),
                    "gift_name": gift_val.strip(),
                    "votes": 0
                })
            self.voters.clear()
            self.is_active = True
            
            if duration_seconds and duration_seconds > 0:
                self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
                self.timer_task = asyncio.create_task(self._poll_timer_loop(duration_seconds))
            else:
                self.expires_at = None

            logger.info(f"Poll started: '{self.title}' (duration={duration_seconds}s) with {len(self.candidates)} candidates.")

    async def stop_poll(self) -> None:
        """Stops the current poll."""
        async with self.lock:
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None
            self.is_active = False
            self.expires_at = None
            logger.info(f"Poll stopped: '{self.title}'.")

    async def _poll_timer_loop(self, duration_seconds: int):
        try:
            await asyncio.sleep(duration_seconds)
            await self.stop_poll()
            
            # Broadcast the expiration to all websockets
            from app.main import manager
            poll_status = await self.get_status()
            await manager.broadcast({
                "type": "poll_update",
                "poll": poll_status
            })
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error in poll timer task: {e}")

    async def record_vote(self, username: str, comment_text: str) -> bool:
        """
        Attempts to register a vote based on a comment.
        Returns True if a valid vote was successfully recorded, False otherwise.
        """
        if not self.is_active or not username:
            return False

        # Fast path check for expired poll
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            await self.stop_poll()
            return False

        async with self.lock:
            if username in self.voters:
                # Already voted
                return False

            clean_comment = comment_text.strip().lower()
            clean_comment_no_hash = clean_comment.removeprefix("#")

            # Check matches
            matched = []
            for c in self.candidates:
                c_id = c["id"]
                c_name = c["name"].lower()
                
                # Check match by candidate ID (e.g. "1" or "#1")
                if clean_comment == c_id or clean_comment_no_hash == c_id:
                    matched.append(c)
                    continue
                
                # Check match by name mention (if name is longer than 2 characters)
                if len(c_name) > 2 and c_name in clean_comment:
                    matched.append(c)
                    continue
                
                # Check match by exact name (if name is short, e.g. 2 chars or less)
                if len(c_name) <= 2 and clean_comment == c_name:
                    matched.append(c)
                    continue

            # Record vote only if there is exactly one unambiguous candidate match
            matched_candidate = matched[0] if len(matched) == 1 else None

            if matched_candidate:
                matched_candidate["votes"] += 1
                self.voters.add(username)
                logger.info(f"Vote recorded: User @{username} voted for {matched_candidate['name']}.")
                return True

            return False

    async def record_gift_vote(self, gift_name: str, diamond_count: int) -> tuple[bool, str | None, int]:
        """
        Records votes from a gift event.
        Gift voting bypasses the username check and adds multiple votes based on diamond value.
        Returns (success, candidate_name, votes_added).
        """
        if not self.is_active or not gift_name:
            return False, None, 0

        # Fast path check for expired poll
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            await self.stop_poll()
            return False, None, 0

        async with self.lock:
            matched_candidate = None
            clean_gift = gift_name.strip().lower()
            for c in self.candidates:
                c_gift = (c.get("gift_name") or "").strip().lower()
                if c_gift and clean_gift == c_gift:
                     matched_candidate = c
                     break
            
            if matched_candidate:
                # 1 diamond = 1 vote (minimum 1 vote)
                votes_to_add = max(1, diamond_count)
                matched_candidate["votes"] += votes_to_add
                logger.info(f"Gift vote recorded: {votes_to_add} votes added to {matched_candidate['name']} via gift '{gift_name}'.")
                return True, matched_candidate["name"], votes_to_add

            return False, None, 0

    async def get_status(self) -> dict:
        """Returns the current poll status and calculated percentages."""
        async with self.lock:
            total_votes = sum(c["votes"] for c in self.candidates)
            status_candidates = []
            for c in self.candidates:
                votes = c["votes"]
                pct = round((votes / total_votes) * 100, 1) if total_votes > 0 else 0.0
                status_candidates.append({
                    "id": c["id"],
                    "name": c["name"],
                    "image_url": c["image_url"],
                    "gift_name": c.get("gift_name", ""),
                    "votes": votes,
                    "percentage": pct
                })

            time_left = None
            if self.is_active and self.expires_at:
                now = datetime.now(timezone.utc)
                time_left = max(0, int((self.expires_at - now).total_seconds()))

            return {
                "is_active": self.is_active,
                "title": self.title,
                "total_votes": total_votes,
                "candidates": status_candidates,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "time_left": time_left
            }

# Global singleton instance
poll_manager = PollManager()
