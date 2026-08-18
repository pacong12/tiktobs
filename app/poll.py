import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from app.state import manager

logger = logging.getLogger("app.poll")

# ---------------------------------------------------------------------------
# Session key + candidate key helpers for the per-session win registry.
# ---------------------------------------------------------------------------

def _session_key() -> str:
    """Returns the current live-session id, or 'local' when no live
    connection is active (polls run standalone, e.g. during testing)."""
    try:
        from app import state
        if state.processor is not None and getattr(state.processor, "session_id", None):
            return str(state.processor.session_id)
    except Exception:  # noqa: BLE001
        pass
    return "local"

def _candidate_key(name: str) -> str:
    """Normalizes a candidate name for win matching (lowercase, collapsed
    whitespace)."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())

# Strips emoji/punctuation/symbols from gift names so live names like
# "Rose \U0001f339" still match the configured "Rose".
_GIFT_NOISE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

def normalize_gift_name(name: str) -> str:
    """Normalizes a gift name for comparison: lowercase, no emoji/punctuation,
    collapsed whitespace. Returns '' for names that are only noise."""
    if not name:
        return ""
    s = name.strip().lower()
    s = _GIFT_NOISE_RE.sub(" ", s)
    return _WHITESPACE_RE.sub(" ", s).strip()

class PollManager:
    """
    Manages the active polling state in memory.
    Tracks candidates, votes, and unique voters (stats only).
    Every matching comment counts as a vote — a user may vote as many
    times as they comment.
    Supports countdown timers and automatic poll stopping.
    Completed rounds are archived to the database for later review.
    """
    def __init__(self):
        self.is_active = False
        self.title = ""
        self.round_name = ""
        self.candidates = []  # List of {"id": "1", "name": "Name", "image_url": "...", "votes": 0}
        self.voters = set()   # Set of usernames who voted at least once (stat only, never blocks)
        # Per-user vote intent for the current round: username_key ->
        # {"candidate_id": str, "comment": str, "at": iso}. Written whenever a
        # comment registers a vote; used by the gift fallback so a gift that
        # matches no candidate is credited to the candidate the sender last
        # voted for by comment. Reset on every start_poll, so only comments
        # made during the ACTIVE round ever count.
        self.vote_intent: dict[str, dict] = {}
        self.expires_at = None  # datetime | None
        self.started_at = None  # datetime | None
        self.duration_seconds = None  # int | None
        self.timer_task = None  # asyncio.Task | None
        self.lock = asyncio.Lock()
        # Per-session win counts: session_key -> {candidate_key -> wins}.
        # Lazily loaded from the DB the first time a session is used.
        self.wins_cache: dict[str, dict[str, int]] = {}

    async def start_poll(self, title: str, candidates: list[dict], duration_seconds: int | None = None, round_name: str = "") -> None:
        """Starts a new poll and resets all existing votes and voters.

        Raises ValueError when two candidates are configured with the same
        gift name \u2014 that would make every such gift count only for the first
        candidate (a 'gift leak'), so it is rejected up front.
        """
        async with self.lock:
            # Build + validate BEFORE touching current state so a validation
            # error leaves the previous poll untouched.
            new_candidates = []
            gift_owners: dict[str, str] = {}
            for idx, c in enumerate(candidates, start=1):
                name_val = (c.get("name") or "").strip()
                img_val = (c.get("image_url") or "").strip()
                gift_val = (c.get("gift_name") or "").strip()
                color_val = (c.get("color") or "").strip()
                gift_key = normalize_gift_name(gift_val)
                if gift_key:
                    if gift_key in gift_owners:
                        raise ValueError(
                            f"Gift '{gift_val}' dipakai oleh dua kandidat "
                            f"('{gift_owners[gift_key]}' dan '{name_val}'). "
                            f"Satu gift hanya boleh ditetapkan ke satu kandidat."
                        )
                    gift_owners[gift_key] = name_val
                new_candidates.append({
                    "id": str(idx),
                    "name": name_val,
                    "image_url": img_val,
                    "gift_name": gift_val,
                    "color": color_val,
                    "votes": 0
                })

            # Cancel existing timer task if running
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None

            self.title = title
            self.round_name = (round_name or "").strip() or title
            self.candidates = new_candidates
            self.voters.clear()
            # New round = fresh intent: comments from previous rounds must not
            # steer gift fallback votes in this one.
            self.vote_intent.clear()
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

                # Determine the round winner BEFORE archiving: a win only
                # counts when votes were cast and ONE candidate leads clearly
                # (a tie awards nobody). Wins are recorded per session so the
                # overlay badges accumulate across rounds and survive restarts.
                winner_name = None
                if total_votes > 0:
                    leader_votes = max(c["votes"] for c in self.candidates)
                    leaders = [c for c in self.candidates if c["votes"] == leader_votes]
                    if len(leaders) == 1:
                        winner_name = leaders[0]["name"]
                        await self._record_win(leaders[0])
                result_candidates = []
                for c in self.candidates:
                    pct = round((c["votes"] / total_votes) * 100, 1) if total_votes > 0 else 0.0
                    result_candidates.append({
                        "id": c["id"],
                        "name": c["name"],
                        "image_url": c["image_url"],
                        "gift_name": c.get("gift_name", ""),
                        "color": c.get("color", ""),
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
                        "winner": winner_name,
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

        Matching rules:
          1. Sequence number: comment is only digits, leading zeros allowed,
             optional '#' prefix ("1", "01", "#01" -> candidate #1).
          2. Candidate ID (kept for backwards compatibility).
          3. Name mention (substring for names > 2 chars, exact otherwise).

        Every matching comment counts: a user can vote as many times as they
        comment (spam-voting). Duplicate *messages* are still filtered at the
        event level by msg_id, and gift votes remain a separate fast track.
        """
        username_key = (username or "").strip().lower()
        if not self.is_active or not username_key:
            return False

        # Fast path check for expired poll
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            await self.stop_poll()
            return False

        async with self.lock:
            clean_comment = comment_text.strip().lower()
            clean_comment_no_hash = clean_comment.removeprefix("#").strip()

            # Rule 1: bare sequence number, leading zeros allowed ("01" -> 1)
            vote_number = None
            if clean_comment_no_hash.isdigit():
                vote_number = int(clean_comment_no_hash)

            # Check matches
            matched = []
            for idx, c in enumerate(self.candidates, start=1):
                c_id = c["id"]
                c_name = c["name"].strip().lower()

                # Check match by sequence number (handles "01", "001", "#01")
                if vote_number is not None and vote_number == idx:
                    matched.append(c)
                    continue

                # Check match by candidate ID (e.g. "1" or "#1")
                if clean_comment == c_id or clean_comment_no_hash == c_id:
                    matched.append(c)
                    continue
                
                # Check match by name mention case-insensitively (handles uppercase/lowercase/mixed case)
                if len(c_name) > 2 and c_name in clean_comment:
                    matched.append(c)
                    continue
                
                # Check match by exact name case-insensitively (if name is short, e.g. 2 chars or less)
                if len(c_name) <= 2 and clean_comment == c_name:
                    matched.append(c)
                    continue

            # Record vote only if there is exactly one unambiguous candidate match
            matched_candidate = matched[0] if len(matched) == 1 else None

            if matched_candidate:
                matched_candidate["votes"] += 1
                self.voters.add(username_key)  # unique-voter stat only
                # Vote intent for the gift fallback: if this user later sends
                # a gift that matches no candidate's gift, it is credited to
                # this candidate. Only unambiguous matches (exactly one
                # candidate) are stored; the latest vote comment wins.
                self.vote_intent[username_key] = {
                    "candidate_id": matched_candidate["id"],
                    "comment": comment_text.strip(),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                logger.info(f"Vote recorded: User @{username_key} voted for {matched_candidate['name']}.")
                await self._persist_state()
                return True

            return False

    async def record_gift_vote(self, gift_name: str, diamond_count: int, username: str | None = None) -> tuple[bool, str | None, int, str | None]:
        """
        Records votes from a gift event.
        Gift voting bypasses the username check and adds multiple votes based on diamond value.

        `diamond_count` is the TOTAL diamond contribution of the event as
        computed by the processor (repeat_count x unit price; per TikTok's
        streak schema only the final event of a combo is counted). 1 diamond
        = 1 vote (minimum 1 vote).

        Comment fallback: when the gift matches NO candidate's gift and
        `username` is provided, the gift is credited (same 1 diamond = 1 vote
        conversion) to the candidate the sender last voted for by comment in
        the CURRENT round (see `vote_intent`). Senders without a vote comment
        this round count for nobody.

        Returns (success, candidate_name, votes_added, via_comment).
        `via_comment` is the text of the sender's last vote comment when the
        gift was credited through the fallback, otherwise None.

        Gifts that match no candidate and have no fallback intent count for
        nobody (strict isolation, no leak); the caller surfaces them via a
        poll_gift_ignored broadcast when a poll is active.
        """
        if not self.is_active or not gift_name:
            return False, None, 0, None

        # Fast path check for expired poll
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            await self.stop_poll()
            return False, None, 0, None

        async with self.lock:
            matched_candidate = None
            clean_gift = normalize_gift_name(gift_name)
            if not clean_gift:
                return False, None, 0, None
            for c in self.candidates:
                # Strict isolation: a gift only ever counts for the candidate
                # whose configured gift normalizes to the exact same name.
                # Unmatched gifts count for NOBODY (no leak between candidates).
                if normalize_gift_name(c.get("gift_name") or "") == clean_gift:
                     matched_candidate = c
                     break

            via_comment = None
            if matched_candidate is None and username:
                # Comment fallback: credit the gift to the candidate this
                # sender last voted for by comment during the active round.
                username_key = (username or "").strip().lower()
                intent = self.vote_intent.get(username_key)
                if intent:
                    candidate_id = intent.get("candidate_id")
                    matched_candidate = next(
                        (c for c in self.candidates if c["id"] == candidate_id), None
                    )
                    if matched_candidate is not None:
                        via_comment = intent.get("comment") or ""

            if matched_candidate:
                # 1 diamond = 1 vote (minimum 1 vote)
                votes_to_add = max(1, diamond_count)
                matched_candidate["votes"] += votes_to_add
                if via_comment is not None:
                    logger.info(
                        f"Gift vote via comment fallback: {votes_to_add} votes added to "
                        f"{matched_candidate['name']} via gift '{gift_name}' "
                        f"(sender @{(username or '').strip().lower()} last commented '{via_comment}')."
                    )
                else:
                    logger.info(f"Gift vote recorded: {votes_to_add} votes added to {matched_candidate['name']} via gift '{gift_name}'.")
                await self._persist_state()
                return True, matched_candidate["name"], votes_to_add, via_comment

            # INFO (not debug): a real viewer just spent coins on a gift that
            # counts for nobody — operators need to see it in the server log
            # and the processor turns this into a poll_gift_ignored broadcast
            # so the overlays can warn the sender.
            logger.info(
                f"Gift '{gift_name}' not counted: no candidate owns this gift "
                f"and the sender has no vote comment this round."
            )
            return False, None, 0, None

    async def _load_wins(self, session_key: str) -> None:
        """Loads win counts for a session from the DB into the cache."""
        try:
            from app import database
            self.wins_cache[session_key] = await database.get_session_wins(session_key)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to load session wins for '{session_key}': {e}")
            self.wins_cache.setdefault(session_key, {})

    async def _record_win(self, candidate: dict) -> None:
        """Persists one win for the round winner (DB + cache)."""
        session_key = _session_key()
        key = _candidate_key(candidate["name"])
        if not key:
            return
        try:
            from app import database
            await database.record_poll_win(
                session_id=session_key,
                candidate_name=candidate["name"],
                candidate_key=key,
                votes=candidate["votes"],
                round_name=self.round_name or self.title,
            )
            cache = self.wins_cache.setdefault(session_key, {})
            cache[key] = cache.get(key, 0) + 1
            logger.info(f"Win recorded: '{candidate['name']}' now has {cache[key]} win(s) in session '{session_key}'.")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to record poll win: {e}")

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
                "vote_intent": self.vote_intent,
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
            # Normalize voter keys so old persisted states (raw usernames)
            # still match the lowercase keys used by record_vote.
            self.voters = {(v or "").strip().lower() for v in (state.get("voters") or [])}
            # Vote intent survives restarts too, so a gift sent right after a
            # restart can still fall back to the sender's last vote comment.
            self.vote_intent = {
                (k or "").strip().lower(): v
                for k, v in (state.get("vote_intent") or {}).items()
                if isinstance(v, dict)
            }
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
            # Per-session win counts (lazy-loaded from DB, cached afterwards).
            session_key = _session_key()
            if session_key not in self.wins_cache:
                await self._load_wins(session_key)
            wins_map = self.wins_cache.get(session_key, {})

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
                    "color": c.get("color", ""),
                    "votes": votes,
                    "percentage": pct,
                    "wins": wins_map.get(_candidate_key(c["name"]), 0)
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
                "unique_voters": len(self.voters),
                "candidates": status_candidates,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "time_left": time_left
            }

# Global singleton instance
poll_manager = PollManager()
