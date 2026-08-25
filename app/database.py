import json
import logging
import os
import uuid
import asyncio
from datetime import datetime, timezone

import aiosqlite

from app import config

DB_DIR = os.path.join(config.get_base_dir(), "data")
DB_PATH = os.path.join(DB_DIR, "tiktok_live.db")

logger = logging.getLogger("app.database")

# A single shared connection is used for the whole app. SQLite only allows one
# writer at a time, so opening a new connection per event (with TikTok firing
# dozens of events per second) caused heavy lock contention -> "database is locked".
# We keep one persistent WAL connection and serialize writes with a lock.
_shared_db: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()
_conn_lock = asyncio.Lock()


async def _get_shared_db() -> aiosqlite.Connection:
    """Returns the process-wide SQLite connection, creating it on first use."""
    global _shared_db
    if _shared_db is None:
        async with _conn_lock:
            if _shared_db is None:
                os.makedirs(DB_DIR, exist_ok=True)
                db = await aiosqlite.connect(DB_PATH)
                await db.execute("PRAGMA journal_mode = WAL;")
                await db.execute("PRAGMA busy_timeout = 5000;")
                await db.execute("PRAGMA synchronous = NORMAL;")
                await db.execute("PRAGMA foreign_keys = ON;")
                await db.commit()
                _shared_db = db
    return _shared_db


async def close_db():
    """Closes the shared connection (call on app shutdown)."""
    global _shared_db
    if _shared_db is not None:
        try:
            await _shared_db.close()
        except Exception as e:
            logger.warning(f"Error closing shared DB connection: {e}")
        finally:
            _shared_db = None


class get_db_connection:
    """Backwards-compatible async context manager that yields the shared connection.

    Note: the connection is NOT closed on exit; it is owned by the module and
    lives for the whole process."""
    def __init__(self):
        self.db = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self.db = await _get_shared_db()
        return self.db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Intentionally do not close the shared connection.
        return False

async def _reset_shared_db() -> None:
    """Discards the shared connection so the next access reopens a fresh one."""
    global _shared_db
    if _shared_db is not None:
        try:
            await _shared_db.close()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Ignoring error while resetting DB connection: {e}")
        finally:
            _shared_db = None

async def _execute_write(sql: str, params: tuple = ()):
    """Runs a single write statement with one automatic recovery attempt.

    If the shared connection errors out (stale handle, corruption, etc.) it is
    discarded and reopened, then the statement is retried once. Returns the
    cursor so callers can read rowcount / lastrowid.
    """
    last_err: Exception | None = None
    async with _write_lock:
        for attempt in (1, 2):
            try:
                db = await _get_shared_db()
                cursor = await db.execute(sql, params)
                await db.commit()
                return cursor
            except aiosqlite.Error as e:
                last_err = e
                logger.warning(f"DB write failed (attempt {attempt}/2): {e}")
                await _reset_shared_db()
    raise last_err

_read_lock = asyncio.Lock()

async def _fetch_all(sql: str, params: tuple = (), as_rows: bool = False):
    """Runs a SELECT and returns all rows, with one self-healing retry.

    Reads share the single connection, so the row_factory mutation and the
    query run under a lock to keep concurrent readers from clobbering each
    other. as_rows=True returns dict-like aiosqlite.Row objects (name access);
    otherwise plain tuples (index access).
    """
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            db = await _get_shared_db()
            async with _read_lock:
                db.row_factory = aiosqlite.Row if as_rows else None
                async with db.execute(sql, params) as cursor:
                    return await cursor.fetchall()
        except aiosqlite.Error as e:
            last_err = e
            logger.warning(f"DB read failed (attempt {attempt}/2): {e}")
            await _reset_shared_db()
    raise last_err

async def _fetch_one(sql: str, params: tuple = ()):
    """Runs a SELECT and returns the first row as a tuple, or None."""
    rows = await _fetch_all(sql, params, as_rows=False)
    return rows[0] if rows else None

# Built-in OBS browser-source overlays. Used to seed the `overlays` table so
# the dashboard list is DB-backed and extensible without editing HTML.
DEFAULT_OVERLAYS = [
    {"key": "leaderboard", "label": "Gift Leaderboard", "url": "/overlay.html",
     "icon": "\U0001F48E", "description": "Top gifters \u2014 session or full history", "accent": "cyan"},
    {"key": "gift-alert", "label": "Gift Alert (Sound)", "url": "/gift-alert.html",
     "icon": "\U0001F381", "description": "Animated alert + sound on incoming gifts", "accent": "pink"},
    {"key": "recent-gifts", "label": "Recent Gifts Ticker", "url": "/recent-gifts.html",
     "icon": "\U0001F389", "description": "Feed of the latest gifts", "accent": "green"},
    {"key": "vote-overlay", "label": "Vote / Poll Overlay", "url": "/vote-overlay.html",
     "icon": "\U0001F5F3\uFE0F", "description": "Live poll progress", "accent": "gold"},
    {"key": "ticker", "label": "Running Text (Ticker)", "url": "/ticker.html",
     "icon": "\U0001F4E2", "description": "Scrolling text for ads/announcements", "accent": "violet"},
    {"key": "gift-bubbles", "label": "Gift Bubbles (Floating)", "url": "/gift-bubbles.html",
     "icon": "\U0001FAE7", "description": "Floating square candidate bubbles on gifts", "accent": "orange"},
    {"key": "timer", "label": "Poll Timer Overlay", "url": "/timer-overlay.html",
     "icon": "\u23F1\uFE0F", "description": "Countdown timer for voting rounds", "accent": "pink"},
    {"key": "session-title", "label": "Session & Title Overlay", "url": "/session-title-overlay.html",
     "icon": "\U0001F4CB", "description": "Header display for round name & poll title", "accent": "cyan"},
    {"key": "fast-vote", "label": "Fast-Track Vote Overlay", "url": "/fast-vote-overlay.html",
     "icon": "\u26A1", "description": "Gift boost focused fast-track voting display", "accent": "gold"},
    {"key": "date-overlay", "label": "Date & Day Overlay", "url": "/date-overlay.html",
     "icon": "\U0001F4C5", "description": "Live day & date display", "accent": "cyan"},
    {"key": "running-text", "label": "Running Text (Marquee V2)", "url": "/running-text-overlay.html",
     "icon": "\U0001F4E2", "description": "Dynamic scrolling marquee card for announcements", "accent": "violet"},
]

async def get_overlays(only_enabled: bool = True) -> list[dict]:
    """Returns the OBS overlay registry ordered for display."""
    where = "WHERE enabled = 1" if only_enabled else ""
    rows = await _fetch_all(
        f"SELECT key, label, url, icon, description, accent, sort_order, enabled "
        f"FROM overlays {where} ORDER BY sort_order ASC, id ASC;",
        as_rows=True,
    )
    return [
        {
            "key": row["key"],
            "label": row["label"],
            "url": row["url"],
            "icon": row["icon"] or "",
            "description": row["description"] or "",
            "accent": row["accent"] or "cyan",
            "sort_order": row["sort_order"],
            "enabled": bool(row["enabled"]),
        }
        for row in rows
    ]

async def init_db():
    """Initializes the database and creates the necessary tables if they do not exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    db = await _get_shared_db()
    # Create live_sessions table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS live_sessions (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            connected_at TEXT NOT NULL,
            disconnected_at TEXT,
            status TEXT NOT NULL
        );
    """)

    # Create tiktok_events table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS tiktok_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            username TEXT,
            nickname TEXT,
            payload TEXT, -- Stored as JSON string
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
        );
    """)
    # Helpful indexes for the common queries (recent events, per-session gifts).
    await db.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON tiktok_events(created_at DESC);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_events_session_type ON tiktok_events(session_id, event_type);")

    # Create poll_rounds table (archive of completed voting rounds/sessions)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS poll_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_name TEXT NOT NULL,
            title TEXT NOT NULL,
            total_votes INTEGER NOT NULL DEFAULT 0,
            candidates TEXT NOT NULL, -- JSON array of {name, votes, percentage, gift_name, image_url}
            duration_seconds INTEGER,
            started_at TEXT,
            ended_at TEXT NOT NULL
        );
    """)

    # Single-row table persisting the currently active poll so it survives restarts.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS active_poll (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state TEXT NOT NULL -- JSON blob of the full poll state
        );
    """)

    # Per-session poll wins. One row every time a poll round ends with a
    # single clear winner, so badges survive app restarts within a session.
    # session_id is the live-session id, or 'local' when no live connection.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS poll_wins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            candidate_name TEXT NOT NULL,
            candidate_key TEXT NOT NULL,
            votes INTEGER NOT NULL,
            round_name TEXT,
            won_at TEXT NOT NULL
        );
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_poll_wins_session ON poll_wins(session_id, candidate_key);")

    # Registry of the OBS browser-source overlays shown on the dashboard.
    # Seeded with the built-in set on first run (INSERT OR IGNORE keyed on
    # `key`, so future overlays appear automatically while any locally edited
    # rows are preserved).
    await db.execute("""
        CREATE TABLE IF NOT EXISTS overlays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            icon TEXT,
            description TEXT,
            accent TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1
        );
    """)
    for i, ov in enumerate(DEFAULT_OVERLAYS):
        await db.execute(
            """
            INSERT INTO overlays
                (key, label, url, icon, description, accent, sort_order, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(key) DO UPDATE SET
                label = excluded.label,
                url = excluded.url,
                icon = excluded.icon,
                description = excluded.description,
                accent = excluded.accent;
            """,
            (ov["key"], ov["label"], ov["url"], ov["icon"], ov["description"], ov["accent"], i),
        )

    # Legacy cleanup: the user-defined gift catalog was removed; the built-in
    # catalog (static/poll-admin.js) + manual entry cover all cases now.
    await db.execute("DROP TABLE IF EXISTS custom_gifts;")
    await db.commit()


async def save_poll_round(
    round_name: str,
    title: str,
    total_votes: int,
    candidates: list[dict],
    duration_seconds: int | None,
    started_at: str | None,
    ended_at: str,
) -> int:
    """Archives a completed voting round. Returns the new round's row id."""
    cursor = await _execute_write(
        """
        INSERT INTO poll_rounds
            (round_name, title, total_votes, candidates, duration_seconds, started_at, ended_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (round_name, title, total_votes, json.dumps(candidates), duration_seconds, started_at, ended_at),
    )
    return cursor.lastrowid


async def get_poll_rounds(limit: int = 100) -> list[dict]:
    """Returns archived voting rounds, most recent first."""
    rows = await _fetch_all(
        """
        SELECT id, round_name, title, total_votes, candidates, duration_seconds, started_at, ended_at
        FROM poll_rounds
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
        as_rows=True,
    )
    return [
        {
            "id": row["id"],
            "round_name": row["round_name"],
            "title": row["title"],
            "total_votes": row["total_votes"],
            "candidates": json.loads(row["candidates"]) if row["candidates"] else [],
            "duration_seconds": row["duration_seconds"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }
        for row in rows
    ]


async def delete_poll_round(round_id: int) -> None:
    """Deletes a single archived round by id."""
    await _execute_write("DELETE FROM poll_rounds WHERE id = ?", (round_id,))


async def clear_poll_rounds() -> None:
    """Deletes all archived rounds."""
    await _execute_write("DELETE FROM poll_rounds")

# ---------------------------------------------------------------------------
# Per-session poll wins (badge data, restart-safe)
# ---------------------------------------------------------------------------

async def record_poll_win(
    session_id: str,
    candidate_name: str,
    candidate_key: str,
    votes: int,
    round_name: str | None = None,
) -> None:
    """Records one poll-round win for a candidate within a session."""
    await _execute_write(
        """
        INSERT INTO poll_wins
            (session_id, candidate_name, candidate_key, votes, round_name, won_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, candidate_name, candidate_key, votes, round_name,
         datetime.now(timezone.utc).isoformat()),
    )

async def clear_poll_wins(session_id: str | None = None) -> None:
    """Deletes recorded wins — all sessions when session_id is None."""
    if session_id is None:
        await _execute_write("DELETE FROM poll_wins;")
    else:
        await _execute_write("DELETE FROM poll_wins WHERE session_id = ?;", (session_id,))

async def get_session_wins(session_id: str | None = None) -> dict[str, int]:
    """Returns win counts keyed by candidate_key.

    If a specific live session has wins, returns those. Otherwise returns
    all recorded wins so candidate win badges persist across restarts
    and new sessions.
    """
    target = session_id or "local"
    rows = await _fetch_all(
        "SELECT candidate_key, COUNT(*) FROM poll_wins WHERE session_id = ? GROUP BY candidate_key;",
        (target,),
    )
    if not rows:
        # Fallback to all recorded wins across sessions so badges survive restarts
        rows = await _fetch_all("SELECT candidate_key, COUNT(*) FROM poll_wins GROUP BY candidate_key;")
    return {row[0]: row[1] for row in rows}

# ---------------------------------------------------------------------------
# Active poll persistence (restart-safe voting state)
# ---------------------------------------------------------------------------

async def save_active_poll(state: dict) -> None:
    """Upserts the active poll state blob (single row)."""
    await _execute_write(
        "INSERT INTO active_poll (id, state) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET state = excluded.state;",
        (json.dumps(state),),
    )

async def get_active_poll() -> dict | None:
    """Returns the persisted active poll state, or None."""
    row = await _fetch_one("SELECT state FROM active_poll WHERE id = 1;")
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return None

async def clear_active_poll() -> None:
    """Removes the persisted active poll row."""
    await _execute_write("DELETE FROM active_poll;")

async def create_session(username: str) -> str:
    """Creates a new LIVE session and stores it in the database. Returns the session ID."""
    session_id = uuid.uuid4().hex[:8]  # Compact 8-character ID
    connected_at = datetime.now(timezone.utc).isoformat()

    await _execute_write(
        "INSERT INTO live_sessions (id, username, connected_at, status) VALUES (?, ?, ?, ?)",
        (session_id, username, connected_at, "CONNECTED"),
    )

    return session_id

async def close_session(session_id: str):
    """Closes an active session by updating status and disconnection timestamp."""
    disconnected_at = datetime.now(timezone.utc).isoformat()
    try:
        await _execute_write(
            "UPDATE live_sessions SET disconnected_at = ?, status = ? WHERE id = ?",
            (disconnected_at, "DISCONNECTED", session_id),
        )
    except aiosqlite.Error as e:
        logger.warning(f"Database error closing session {session_id} (safe to ignore during shutdown): {e}")

async def insert_event(
    session_id: str,
    event_id: str,
    event_type: str,
    username: str | None,
    nickname: str | None,
    payload: dict,
    created_at: str
) -> bool:
    """
    Inserts a normalized event into the tiktok_events table.
    Uses INSERT OR IGNORE to prevent duplicate processing.
    Returns True if the event was newly inserted, False if it was a duplicate and ignored.
    """
    payload_str = json.dumps(payload)
    try:
        cursor = await _execute_write(
            """
            INSERT OR IGNORE INTO tiktok_events (id, session_id, event_type, username, nickname, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, session_id, event_type, username, nickname, payload_str, created_at),
        )
        return cursor.rowcount > 0
    except aiosqlite.Error as e:
        logger.error(f"Failed to insert event {event_id} due to database error: {e}")
        return False

async def get_recent_events(limit: int = 100) -> list[dict]:
    """Retrieves the most recent events from the database."""
    rows = await _fetch_all(
        """
        SELECT id, session_id, event_type, username, nickname, payload, created_at
        FROM tiktok_events
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
        as_rows=True,
    )
    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "username": row["username"],
            "nickname": row["nickname"],
            "payload": json.loads(row["payload"]) if row["payload"] else {},
            "created_at": row["created_at"],
        }
        for row in rows
    ]

async def get_session_events(session_id: str) -> list[dict]:
    """
    Retrieves every stored event of one session in chronological order
    (oldest first), so history can be replayed in the order it happened.
    """
    rows = await _fetch_all(
        """
        SELECT id, session_id, event_type, username, nickname, payload, created_at
        FROM tiktok_events
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,),
        as_rows=True,
    )
    return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "username": row["username"],
                "nickname": row["nickname"],
                "payload": json.loads(row["payload"]) if row["payload"] else {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

async def _aggregate_leaderboard(where: str, params: tuple) -> list[dict]:
    """
    Aggregates gift events directly in SQL (json_extract over the stored
    payload), so large histories no longer load every row into Python.
    Returns a sorted list of dicts: username, nickname, total_diamonds,
    total_gifts.
    """
    sql = """
        SELECT
            username,
            COALESCE(MAX(nickname), username) AS nickname,
            SUM(COALESCE(json_extract(payload, '$.data.quantity'), 1) *
                COALESCE(json_extract(payload, '$.data.diamond_count'), 0)) AS total_diamonds,
            SUM(COALESCE(json_extract(payload, '$.data.quantity'), 1)) AS total_gifts
        FROM tiktok_events
        WHERE event_type = 'gift'
          AND username IS NOT NULL AND username != ''
          /* TikTok streak schema: gift_type=1 with repeat_end=0 is a mid-streak
             increment; the final event (repeat_end=1) already carries the full
             quantity, so increments must be excluded to avoid inflation. */
          AND NOT (
              COALESCE(json_extract(payload, '$.data.gift_type'), 0) = 1
              AND COALESCE(json_extract(payload, '$.data.repeat_end'), 1) = 0
          )
    """
    if where:
        sql += " AND " + where
    sql += " GROUP BY username ORDER BY total_diamonds DESC, total_gifts DESC, username ASC"
    rows = await _fetch_all(sql, params, as_rows=True)
    return [
            {
                "username": row["username"],
                "nickname": row["nickname"],
                "total_diamonds": int(row["total_diamonds"] or 0),
                "total_gifts": int(row["total_gifts"] or 0),
            }
            for row in rows
        ]

async def get_session_leaderboard(session_id: str) -> list[dict]:
    """Gift leaderboard for a single session only."""
    return await _aggregate_leaderboard("session_id = ?", (session_id,))

async def get_all_time_leaderboard() -> list[dict]:
    """
    Gift leaderboard over the full stored history: reuses gift events from
    every session still in the database (subject to the retention purge).
    """
    return await _aggregate_leaderboard("", ())

async def clear_events() -> int:
    """Deletes ALL stored TikTok events (across every session).

    Used by the dashboard's "Clear" action. Returns the number of deleted
    rows. Note: this also resets the gift leaderboard, which aggregates
    these events.
    """
    cursor = await _execute_write("DELETE FROM tiktok_events")
    return cursor.rowcount

async def purge_events_before(before_iso: str) -> int:
    """Deletes all events with created_at older than the given ISO timestamp.
    Returns the number of deleted rows."""
    cursor = await _execute_write(
        "DELETE FROM tiktok_events WHERE created_at < ?",
        (before_iso,),
    )
    return cursor.rowcount
