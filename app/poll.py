import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.state import manager

logger = logging.getLogger("app.poll")

class PollManager:
    """
    Manages the active polling state in memory.
    Tracks candidates, votes, and voters to prevent duplicate votes.
    Supports countdown timers and automatic poll stopping.
    Completed rounds are archived to the database for later review.
    """
    def __init__(self):
        self.is_active = False
        self.title = ""
        self.round_name = ""
        self.candidates = []  # List of {"id": "1", "name": "Name", "image_url": "...", "votes": 0}
        self.voters = set()   # Set of usernames who have voted
        self.expires_at = None  # datetime | None
        self.started_at = None  # datetime | None
        self.duration_seconds = None  # int | None
        self.timer_task = None  # asyncio.Task | None
        self.lock = asyncio.Lock()

    async def start_poll(self, title: str, candidates: list[dict], duration_seconds: int | None = None, round_name: str = "") -> None:
        """Starts a new poll and resets all existing votes and voters."""
        async with self.lock:
            # Cancel existing timer task if running
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None

            self.title = title
            self.round_name = (round_name or "").strip() or title
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
            self.started_at = datetime.now(timezone.utc)
            self.duration_seconds = duration_seconds if (duration_seconds and duration_seconds > 0) else None

            if self.duration_seconds:
                self.expires_at = self.started_at + timedelta(seconds=self.duration_seconds)
                self.timer_task = asyncio.create_task(self._poll_timer_loop(self.duration_seconds))
            else:
                self.expires_at = None

            logger.info(f"Poll started: round='{self.round_name}' title='{self.title}' (duration={duration_seconds}s) with {len(self.candidates)} candidates.")
            await self._persist_state()

    async def stop_poll(self, archive: bool = True) -> dict | None:
        """Stops the current poll. If archive=True and there was an active poll,
        the final result is saved to the database. Returns the archived round dict (or None)."""
        async with self.lock:
            # Cancel the timer task, but NOT if stop_poll is being called from
            # within the timer task itself (that would cancel the current task
            # mid-execution and abort the archive/cleanup below).
            if self.timer_task and self.timer_task is not asyncio.current_task():
                self.timer_task.cancel()
            self.timer_task = None

            was_active = self.is_active
            archived = None

            if was_active and archive:
                total_votes = sum(c["votes"] for c in self.candidates)
                result_candidates = []
                for c in self.candidates:
                    pct = round((c["votes"] / total_votes) * 100, 1) if total_votes > 0 else 0.0
                    result_candidates.append({
                        "id": c["id"],
                        "name": c["name"],
                        "image_url": c["image_url"],
                        "gift_name": c.get("gift_name", ""),
                        "votes": c["votes"],
                        "percentage": pct,
                    })
                ended_at = datetime.now(timezone.utc)
                try:
                    from app import database
                    round_id = await database.save_poll_round(
                        round_name=self.round_name or self.title,
                        title=self.title,
                        total_votes=total_votes,
                        candidates=result_candidates,
                        duration_seconds=self.duration_seconds,
                        started_at=self.started_at.isoformat() if self.started_at else None,
                        ended_at=ended_at.isoformat(),
                    )
                    archived = {
                        "id": round_id,
                        "round_name": self.round_name or self.title,
                        "title": self.title,
                        "total_votes": total_votes,
                        "candidates": result_candidates,
                        "duration_seconds": self.duration_seconds,
                        "started_at": self.started_at.isoformat() if self.started_at else None,
                        "ended_at": ended_at.isoformat(),
                    }
                    logger.info(f"Poll round '{self.round_name}' archived (id={round_id}, total_votes={total_votes}).")
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Failed to archive poll round '{self.round_name}': {e}")

            self.is_active = False
            self.expires_at = None
            logger.info(f"Poll stopped: '{self.title}'.")
            # Voting is over: drop the persisted state so a restart won't revive it.
            try:
                from app import database
                await database.clear_active_poll()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to clear persisted poll state: {e}")
            return archived

    async def _poll_timer_loop(self, duration_seconds: int):
        try:
            await asyncio.sleep(duration_seconds)
            archived = await self.stop_poll()

            # Broadcast the expiration to all websockets
            poll_status = await self.get_status()
            await manager.broadcast({
                "type": "poll_update",
                "poll": poll_status
            })
            if archived:
                await manager.broadcast({
                    "type": "poll_round_archived",
                    "round": archived
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
                await self._persist_state()
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
                await self._persist_state()
                return True, matched_candidate["name"], votes_to_add

            return False, None, 0

    async def _persist_state(self) -> None:
        """Saves the current poll state to the DB so it survives app restarts."""
        try:
            from app import database
            state = {
                "is_active": self.is_active,
                "title": self.title,
                "round_name": self.round_name,
                "candidates": self.candidates,
                "voters": sorted(self.voters),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "duration_seconds": self.duration_seconds,
            }
            await database.save_active_poll(state)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to persist poll state: {e}")

    async def restore(self) -> None:
        """Restores a poll that was active when the app last shut down.

        If the persisted poll has already expired it is archived like a normal
        stop; otherwise the countdown timer is resumed with the remaining time.
        """
        try:
            from app import database
            state = await database.get_active_poll()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not read persisted poll state: {e}")
            return
        if not state or not state.get("is_active"):
            return

        async with self.lock:
            self.title = state.get("title") or ""
            self.round_name = state.get("round_name") or self.title
            self.candidates = state.get("candidates") or []
            self.voters = set(state.get("voters") or [])
            self.duration_seconds = state.get("duration_seconds")
            self.started_at = None
            if state.get("started_at"):
                try:
                    self.started_at = datetime.fromisoformat(state["started_at"])
                except ValueError:
                    pass
            self.expires_at = None
            if state.get("expires_at"):
                try:
                    self.expires_at = datetime.fromisoformat(state["expires_at"])
                except ValueError:
                    pass
            self.is_active = True

        if self.expires_at and datetime.now(timezone.utc) >= self.expires_at:
            # Already expired while we were down: archive it properly.
            logger.info(f"Restored poll '{self.round_name}' had expired while offline; archiving.")
            await self.stop_poll()
        else:
            remaining = None
            if self.expires_at:
                remaining = int((self.expires_at - datetime.now(timezone.utc)).total_seconds())
                self.timer_task = asyncio.create_task(self._poll_timer_loop(remaining))
            logger.info(f"Poll restored from disk: round='{self.round_name}' (remaining={remaining}s).")

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
                "round_name": self.round_name,
                "total_votes": total_votes,
                "candidates": status_candidates,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "time_left": time_left
            }

# Global singleton instance
poll_manager = PollManager()
