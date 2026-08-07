import json
import logging
import os
import uuid
from datetime import datetime, timezone

import aiosqlite

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "tiktok_live.db")

logger = logging.getLogger("app.database")

class get_db_connection:
    """Asynchronous context manager to retrieve configured SQLite connection with busy timeout and WAL mode."""
    def __init__(self):
        self.db = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.execute("PRAGMA busy_timeout = 5000;")
        return self.db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.db:
            await self.db.close()

async def init_db():
    """Initializes the database and creates the necessary tables if they do not exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    async with get_db_connection() as db:
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA foreign_keys = ON;")
        
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
        await db.commit()

async def create_session(username: str) -> str:
    """Creates a new LIVE session and stores it in the database. Returns the session ID."""
    session_id = uuid.uuid4().hex[:8]  # Compact 8-character ID
    connected_at = datetime.now(timezone.utc).isoformat()
    
    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO live_sessions (id, username, connected_at, status) VALUES (?, ?, ?, ?)",
            (session_id, username, connected_at, "CONNECTED")
        )
        await db.commit()
        
    return session_id

async def close_session(session_id: str):
    """Closes an active session by updating status and disconnection timestamp."""
    disconnected_at = datetime.now(timezone.utc).isoformat()
    try:
        async with get_db_connection() as db:
            await db.execute(
                "UPDATE live_sessions SET disconnected_at = ?, status = ? WHERE id = ?",
                (disconnected_at, "DISCONNECTED", session_id)
            )
            await db.commit()
    except aiosqlite.OperationalError as e:
        logger.warning(f"Database locked or error closing session {session_id} (safe to ignore during shutdown): {e}")

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
        async with get_db_connection() as db, db.execute(
            """
            INSERT OR IGNORE INTO tiktok_events (id, session_id, event_type, username, nickname, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, session_id, event_type, username, nickname, payload_str, created_at),
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0
    except aiosqlite.OperationalError as e:
        logger.error(f"Failed to insert event {event_id} due to database error: {e}")
        return False

async def get_recent_events(limit: int = 100) -> list[dict]:
    """Retrieves the most recent events from the database."""
    async with get_db_connection() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, session_id, event_type, username, nickname, payload, created_at
            FROM tiktok_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            events = []
            for row in rows:
                events.append({
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "event_type": row["event_type"],
                    "username": row["username"],
                    "nickname": row["nickname"],
                    "payload": json.loads(row["payload"]) if row["payload"] else {},
                    "created_at": row["created_at"]
                })
            return events

async def get_session_leaderboard(session_id: str) -> list[dict]:
    """
    Calculates the gift leaderboard for a given session by querying and aggregating gift events.
    Returns a sorted list of dictionaries with columns: username, nickname, total_diamonds, total_gifts.
    """
    async with get_db_connection() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT username, nickname, payload
            FROM tiktok_events
            WHERE session_id = ? AND event_type = 'gift'
            """,
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            
            leaderboard_map = {}
            for row in rows:
                username = row["username"]
                if not username:
                    continue
                nickname = row["nickname"] or username
                payload = json.loads(row["payload"]) if row["payload"] else {}
                event_data = payload.get("data") or {}
                
                quantity = int(event_data.get("quantity") or 1)
                diamond_count = int(event_data.get("diamond_count") or 0)
                diamonds_gained = quantity * diamond_count
                
                if username not in leaderboard_map:
                    leaderboard_map[username] = {
                        "username": username,
                        "nickname": nickname,
                        "total_diamonds": 0,
                        "total_gifts": 0
                    }
                
                if row["nickname"]:
                    leaderboard_map[username]["nickname"] = row["nickname"]
                    
                leaderboard_map[username]["total_diamonds"] += diamonds_gained
                leaderboard_map[username]["total_gifts"] += quantity
                
            leaderboard = list(leaderboard_map.values())
            leaderboard.sort(key=lambda x: (-x["total_diamonds"], -x["total_gifts"], x["username"]))
            return leaderboard
