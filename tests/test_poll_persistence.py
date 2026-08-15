"""Unit tests for PollManager persistence, restore, and vote dedup."""

import asyncio

import pytest

from app import database
from app.poll import PollManager


@pytest.fixture(autouse=True)
async def clean_state():
    await database.init_db()
    yield
    await database.clear_poll_rounds()
    await database.clear_active_poll()


async def _fresh():
    pm = PollManager()
    return pm


async def test_start_persists_and_stop_clears():
    pm = await _fresh()
    await pm.start_poll("T", [{"name": "A"}, {"name": "B"}], round_name="R1")
    state = await database.get_active_poll()
    assert state is not None
    assert state["round_name"] == "R1"
    assert state["is_active"] is True

    await pm.stop_poll()
    assert await database.get_active_poll() is None


async def test_vote_dedup():
    pm = await _fresh()
    await pm.start_poll("T", [{"name": "A"}, {"name": "B"}], round_name="R2")
    assert await pm.record_vote("alice", "1") is True
    assert await pm.record_vote("alice", "2") is False  # same voter, blocked
    assert await pm.record_vote("bob", "B") is True
    status = await pm.get_status()
    assert status["total_votes"] == 2
    await pm.stop_poll()


async def test_gift_vote_maps_to_candidate():
    pm = await _fresh()
    await pm.start_poll("T", [
        {"name": "A"},
        {"name": "B", "gift_name": "Rose"},
    ], round_name="R3")
    ok, name, added = await pm.record_gift_vote("Rose", 10)
    assert ok is True
    assert name == "B"
    assert added == 10
    status = await pm.get_status()
    assert status["total_votes"] == 10
    await pm.stop_poll()


async def test_restore_recovers_votes_and_voters():
    pm1 = await _fresh()
    await pm1.start_poll("Restart", [{"name": "A"}, {"name": "B"}],
                         duration_seconds=600, round_name="RR")
    await pm1.record_vote("alice", "1")
    await pm1.record_gift_vote("nope", 5)

    # Simulate restart with a brand-new manager.
    pm2 = await _fresh()
    await pm2.restore()
    status = await pm2.get_status()
    assert status["is_active"] is True
    assert status["round_name"] == "RR"
    assert status["total_votes"] == 1
    # Voter list survives so double-votes stay blocked.
    assert await pm2.record_vote("alice", "1") is False

    await pm2.stop_poll()


async def test_restore_expired_poll_archives():
    pm1 = await _fresh()
    await pm1.start_poll("Old", [{"name": "A"}, {"name": "B"}],
                         duration_seconds=1, round_name="EXP")
    # Manually force expiry (simulate downtime) without waiting on the timer.
    from datetime import datetime, timezone, timedelta
    pm1.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    if pm1.timer_task:
        pm1.timer_task.cancel()
    await database.save_active_poll({
        "is_active": True, "title": pm1.title, "round_name": pm1.round_name,
        "candidates": pm1.candidates, "voters": sorted(pm1.voters),
        "started_at": pm1.started_at.isoformat(),
        "expires_at": pm1.expires_at.isoformat(),
        "duration_seconds": pm1.duration_seconds,
    })

    pm2 = await _fresh()
    await pm2.restore()
    status = await pm2.get_status()
    assert status["is_active"] is False  # expired poll must be archived, not revived
    rounds = await database.get_poll_rounds(10)
    assert any(r["round_name"] == "EXP" for r in rounds)


async def test_concurrent_inserts_no_lock():
    session_id = await database.create_session("concurrency_test")
    errors = []

    async def worker(i):
        try:
            await database.insert_event(
                session_id=session_id,
                event_id=f"evt-{i}",
                event_type="comment",
                username=f"u{i}",
                nickname=f"U{i}",
                payload={"content": "hi"},
                created_at="2026-01-01T00:00:00",
            )
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))

    await asyncio.gather(*(worker(i) for i in range(60)))
    assert not errors, f"got DB errors: {errors[:5]}"
