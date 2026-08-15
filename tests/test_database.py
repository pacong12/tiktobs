"""Database-layer tests: retention purge and SQL-aggregated leaderboard."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import database


@pytest.fixture(autouse=True)
async def _init_db():
    await database.init_db()
    yield


async def _insert_event(created_at: str, event_type: str = "comment", payload: dict | None = None) -> tuple[str, str]:
    event_id = uuid.uuid4().hex
    # events have a FK to live_sessions, so the session must exist first
    session_id = await database.create_session("retention_test")
    await database.insert_event(
        session_id=session_id,
        event_id=event_id,
        event_type=event_type,
        username="someone",
        nickname="Someone",
        payload=payload or {"data": {}},
        created_at=created_at,
    )
    return event_id, session_id


async def test_purge_events_before_removes_only_old_rows():
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    recent_ts = (now - timedelta(hours=1)).isoformat()

    await _insert_event(old_ts)
    await _insert_event(old_ts)
    recent_id, _ = await _insert_event(recent_ts)

    cutoff = (now - timedelta(days=7)).isoformat()
    deleted = await database.purge_events_before(cutoff)
    assert deleted == 2

    recent = await database.get_recent_events(limit=100)
    ids = [e["id"] for e in recent]
    assert recent_id in ids

    # Purging again finds nothing left to delete.
    assert await database.purge_events_before(cutoff) == 0


async def test_purge_with_future_cutoff_deletes_nothing_extra():
    ts = datetime.now(timezone.utc).isoformat()
    await _insert_event(ts)
    deleted = await database.purge_events_before((datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    assert deleted == 0


async def test_leaderboard_sql_aggregation():
    # events have a FK to live_sessions, so create the session row first
    session_id = await database.create_session("leaderboard_test")
    assert session_id

    async def gift(user: str, nickname: str, gift_id: str, qty: int, diamonds: int):
        await database.insert_event(
            session_id=session_id,
            event_id=uuid.uuid4().hex,
            event_type="gift",
            username=user,
            nickname=nickname,
            payload={"data": {"gift_id": gift_id, "gift_name": "X", "quantity": qty, "diamond_count": diamonds}},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    await gift("alice", "Alice", "g1", 5, 2)     # 10 diamonds, 5 gifts
    await gift("alice", "Alice", "g2", 1, 40)    # +40 -> 50 total
    await gift("bob", "Bob", "g3", 1, 100)       # 100 diamonds, 1 gift
    await gift("nully", None, "g4", 2, 3)        # nickname falls back to username
    # Non-gift event must be ignored.
    await database.insert_event(
        session_id=session_id,
        event_id=uuid.uuid4().hex,
        event_type="comment",
        username="alice",
        nickname="Alice",
        payload={"data": {"comment": "hi"}},
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    board = await database.get_session_leaderboard(session_id)
    assert [row["username"] for row in board] == ["bob", "alice", "nully"]

    bob, alice, nully = board
    assert (bob["total_diamonds"], bob["total_gifts"]) == (100, 1)
    assert (alice["total_diamonds"], alice["total_gifts"]) == (50, 6)
    assert nully["nickname"] == "nully"  # NULL nickname falls back to username
    assert (nully["total_diamonds"], nully["total_gifts"]) == (6, 2)
