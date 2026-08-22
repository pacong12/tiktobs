"""Unit tests for per-session poll win tracking (overlay badge data)."""

import pytest

from app import database, state
from app.poll import PollManager, _candidate_key


class _FakeProcessor:
    """Stand-in for the event processor carrying a live session id."""

    def __init__(self, session_id: str | None):
        self.session_id = session_id


@pytest.fixture(autouse=True)
async def clean_state(monkeypatch):
    await database.init_db()
    await database.clear_poll_wins()
    monkeypatch.setattr(state, "processor", None)
    yield
    await database.clear_poll_wins()
    await database.clear_poll_rounds()
    await database.clear_active_poll()


async def _run_round(pm: PollManager, votes: dict[str, int], round_name: str = "R") -> dict | None:
    """Starts a poll, applies the given vote counts, stops, returns the archive."""
    candidates = [{"name": name} for name in votes]
    await pm.start_poll("T", candidates, round_name=round_name)
    for c in pm.candidates:
        c["votes"] = votes[c["name"]]
    return await pm.stop_poll()


async def test_clear_winner_records_win():
    pm = PollManager()
    # 5 vs 2 -> 5/7 = 71.4% (> 50%) -> 2 wins
    archived = await _run_round(pm, {"A": 5, "B": 2})
    assert archived is not None
    assert archived["winner"] == "A"
    wins = await database.get_session_wins("local")
    assert wins == {_candidate_key("A"): 2}


async def test_winner_at_or_below_50_pct_records_single_win():
    pm = PollManager()
    # 4 vs 3 vs 3 -> 4/10 = 40% (<= 50%) -> 1 win
    archived = await _run_round(pm, {"A": 4, "B": 3, "C": 3})
    assert archived is not None
    assert archived["winner"] == "A"
    wins = await database.get_session_wins("local")
    assert wins == {_candidate_key("A"): 1}


async def test_tie_records_no_win():
    pm = PollManager()
    archived = await _run_round(pm, {"A": 3, "B": 3})
    assert archived["winner"] is None
    assert await database.get_session_wins("local") == {}


async def test_zero_votes_records_no_win():
    pm = PollManager()
    archived = await _run_round(pm, {"A": 0, "B": 0})
    assert archived["winner"] is None
    assert await database.get_session_wins("local") == {}


async def test_wins_accumulate_and_show_in_next_status():
    pm = PollManager()
    # R1: 4/5 = 80% (>50%) -> +2 Merah
    await _run_round(pm, {"Merah": 4, "Biru": 1}, round_name="R1")
    # R2: 9/11 = 81.8% (>50%) -> +2 Biru
    await _run_round(pm, {"Merah": 2, "Biru": 9}, round_name="R2")
    # R3: 7/7 = 100% (>50%) -> +2 Merah
    await _run_round(pm, {"Merah": 7, "Biru": 0}, round_name="R3")

    # Next round with the same candidates: badges show accumulated wins.
    await pm.start_poll("T", [{"name": "Merah"}, {"name": "Biru"}], round_name="R4")
    status = await pm.get_status()
    by_name = {c["name"]: c["wins"] for c in status["candidates"]}
    assert by_name == {"Merah": 4, "Biru": 2}
    await pm.stop_poll()


async def test_wins_are_scoped_to_session(monkeypatch):
    pm = PollManager()
    monkeypatch.setattr(state, "processor", _FakeProcessor("sess-A"))
    # 5/6 = 83.3% (>50%) -> +2 A
    await _run_round(pm, {"A": 5, "B": 1})

    monkeypatch.setattr(state, "processor", _FakeProcessor("sess-B"))
    # 5/6 -> +2 A
    await _run_round(pm, {"A": 5, "B": 1})
    # 6/6 -> +2 B
    await _run_round(pm, {"A": 0, "B": 6})

    assert await database.get_session_wins("sess-A") == {"a": 2}
    assert await database.get_session_wins("sess-B") == {"a": 2, "b": 2}

    # Status only reflects the CURRENT session's wins.
    await pm.start_poll("T", [{"name": "A"}, {"name": "B"}])
    status = await pm.get_status()
    by_name = {c["name"]: c["wins"] for c in status["candidates"]}
    assert by_name == {"A": 2, "B": 2}
    await pm.stop_poll()


async def test_wins_survive_fresh_poll_manager():
    """A restart (new PollManager) must reload wins from the DB."""
    pm1 = PollManager()
    await _run_round(pm1, {"A": 5, "B": 1})

    pm2 = PollManager()
    await pm2.start_poll("T", [{"name": "A"}, {"name": "B"}])
    status = await pm2.get_status()
    by_name = {c["name"]: c["wins"] for c in status["candidates"]}
    assert by_name == {"A": 2, "B": 0}
    await pm2.stop_poll()
