"""End-to-end tests for the poll rounds, sound config, and CSV export."""

import pytest


# ---------- Poll start validation ----------

def test_start_poll_requires_two_candidates(client):
    resp = client.post("/api/poll/start", json={
        "title": "T", "candidates": [{"name": "Solo"}],
    })
    assert resp.status_code == 400


def test_start_poll_rejects_empty_name(client):
    resp = client.post("/api/poll/start", json={
        "title": "T", "candidates": [{"name": "A"}, {"name": "   "}],
    })
    assert resp.status_code == 400


def test_start_poll_rejects_short_duration(client):
    resp = client.post("/api/poll/start", json={
        "title": "T", "duration_seconds": 2,
        "candidates": [{"name": "A"}, {"name": "B"}],
    })
    assert resp.status_code == 400


# ---------- Full poll lifecycle ----------

def test_poll_lifecycle_and_archive(client):
    start = client.post("/api/poll/start", json={
        "title": "Warna favorit",
        "round_name": "Ronde Uji 1",
        "candidates": [
            {"name": "Merah"},
            {"name": "Biru", "gift_name": "Rose"},
        ],
    })
    assert start.status_code == 200
    body = start.json()
    assert body["is_active"] is True
    assert body["round_name"] == "Ronde Uji 1"

    status = client.get("/api/poll/status").json()
    assert status["is_active"] is True

    stop = client.post("/api/poll/stop").json()
    assert stop["poll"]["is_active"] is False
    assert stop["archived"]["round_name"] == "Ronde Uji 1"

    rounds = client.get("/api/poll/rounds").json()["rounds"]
    assert any(r["round_name"] == "Ronde Uji 1" for r in rounds)


# ---------- Event stream clear ----------

async def test_clear_events_deletes_stored_events(client):
    from datetime import datetime, timezone

    from app import database

    # Seed a few events directly through the database layer.
    session_id = await database.create_session("clear_test")
    for i in range(3):
        await database.insert_event(
            session_id=session_id,
            event_id=f"clear-evt-{i}",
            event_type="comment",
            username=f"u{i}",
            nickname=f"U{i}",
            payload={"data": {"comment": "hi"}},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    resp = client.post("/api/events/clear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["deleted"] >= 3

    # The stream source is empty now.
    assert client.get("/api/events/recent").json() == []

    # Clearing again is a harmless no-op.
    again = client.post("/api/events/clear")
    assert again.status_code == 200
    assert again.json()["deleted"] == 0

# ---------- Running text (ticker) ----------

def test_ticker_defaults(client, tmp_path, monkeypatch):
    from app import state

    monkeypatch.setattr(state, "TICKER_CONFIG_FILE", str(tmp_path / "ticker.json"))

    resp = client.get("/api/ticker")
    assert resp.status_code == 200
    cfg = resp.json()
    assert cfg["enabled"] is True
    assert cfg["speed"] == 60
    assert cfg["direction"] == "left"
    assert cfg["messages"] == []

def test_ticker_update_validation_and_persistence(client, tmp_path, monkeypatch):
    from app import state

    config_file = tmp_path / "ticker.json"
    monkeypatch.setattr(state, "TICKER_CONFIG_FILE", str(config_file))

    # Update with messy input: blanks stripped, values clamped/saved.
    resp = client.post("/api/ticker", json={
        "messages": ["  Promo A  ", "", "Promo B"],
        "speed": 120,
        "direction": "right",
    })
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert cfg["messages"] == ["Promo A", "Promo B"]
    assert cfg["speed"] == 120
    assert cfg["direction"] == "right"
    assert config_file.exists()  # persisted to disk

    # A fresh GET sees the same values (loaded from disk).
    again = client.get("/api/ticker").json()
    assert again["messages"] == ["Promo A", "Promo B"]
    assert again["speed"] == 120

    # Invalid direction and out-of-range speed are rejected.
    assert client.post("/api/ticker", json={"direction": "up"}).status_code == 400
    assert client.post("/api/ticker", json={"speed": 5}).status_code == 400
    assert client.post("/api/ticker", json={"speed": 9999}).status_code == 400

    # Partial updates leave the other fields untouched.
    resp = client.post("/api/ticker", json={"enabled": False})
    cfg = resp.json()["config"]
    assert cfg["enabled"] is False
    assert cfg["messages"] == ["Promo A", "Promo B"]



# ---------- CSV export ----------

def test_csv_export(client):
    client.post("/api/poll/start", json={
        "title": "CSV", "round_name": "R1",
        "candidates": [{"name": "A"}, {"name": "B"}],
    })
    client.post("/api/poll/stop")

    resp = client.get("/api/poll/rounds/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("round_id,round_name,title")
    assert any(",R1," in ln for ln in lines)


# ---------- Sound configuration ----------

def test_sound_config_rejects_missing_file(client):
    resp = client.post("/api/sound-config", json={"gift_sound": "ghost.mp3"})
    assert resp.status_code == 400


def test_sound_config_clamps_volume(client):
    resp = client.post("/api/sound-config", json={"gift_volume": 5.0, "vote_volume": -2})
    assert resp.status_code == 200
    cfg = client.get("/api/sound-config").json()
    assert cfg["gift_volume"] == 1.0
    assert cfg["vote_volume"] == 0.0


def test_upload_sound_rejects_non_audio(client):
    resp = client.post(
        "/api/upload-sound",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_sound_accepts_mp3(client):
    resp = client.post(
        "/api/upload-sound",
        files={"file": ("ding.mp3", b"ID3fakeaudio", "audio/mpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "ding.mp3"

    names = client.get("/api/sounds").json()["sounds"]
    assert "ding.mp3" in names

    # Assign it as the gift sound, then delete it -> config falls back to default.
    assert client.post("/api/sound-config", json={"gift_sound": "ding.mp3"}).status_code == 200
    assert client.delete("/api/sounds/ding.mp3").status_code == 200
    cfg = client.get("/api/sound-config").json()
    assert cfg["gift_sound"] == ""


def test_delete_sound_rejects_traversal(client):
    # Encoded slashes get decoded and the multi-segment path never matches the
    # single-segment route, so traversal attempts are rejected outright
    # (404 = no such sound, 405 = path didn't match the route).
    resp = client.delete("/api/sounds/..%2F..%2F.env")
    assert resp.status_code in (400, 404, 405)
    # And the plain-basename case: "../" is stripped by the handler itself.
    assert client.delete("/api/sounds/.env").status_code == 404

# ---------- Poll history replay ----------

async def test_start_poll_include_history_replays_session_events(client):
    """include_history=true reuses stored events of the current session:
    comments and gifts that arrived before the poll started are counted."""
    import uuid
    from datetime import datetime, timezone

    import app.main as app_main
    from app import database

    session_id = await database.create_session("poll_history_test")
    old_session = app_main.processor.session_id
    app_main.processor.session_id = session_id

    async def ev(event_type: str, username: str, data: dict):
        await database.insert_event(
            session_id=session_id,
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            username=username,
            nickname=username,
            payload={"data": data},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    # Pre-poll history of this session.
    await ev("comment", "voter_a", {"comment": "1"})            # -> Merah
    await ev("comment", "voter_b", {"comment": "pilih Biru!"})  # -> Biru (name mention)
    await ev("comment", "voter_a", {"comment": "1"})            # same user, counts again
    await ev("gift", "whale", {"gift_name": "Rose", "quantity": 1, "diamond_count": 25})  # -> Biru
    await ev("comment", "noise", {"comment": "haha lucu banget"})  # matches nothing

    try:
        resp = client.post("/api/poll/start", json={
            "title": "Pakai riwayat",
            "candidates": [{"name": "Merah"}, {"name": "Biru", "gift_name": "Rose"}],
            "include_history": True,
        })
        assert resp.status_code == 200
        body = resp.json()

        assert body["history_applied"]["comments"] == 3
        assert body["history_applied"]["gifts"] == 1
        assert body["history_applied"]["votes"] == 253  # 3 comment votes + 250 gift votes (25 diamonds x 10)

        votes = {c["name"]: c["votes"] for c in body["candidates"]}
        assert votes["Merah"] == 2
        assert votes["Biru"] == 251  # 1 comment + 250 gift votes
    finally:
        client.post("/api/poll/stop")
        app_main.processor.session_id = old_session

def test_start_poll_without_history_ignores_previous_events(client):
    """Default behavior stays unchanged: without the flag nothing is replayed."""
    resp = client.post("/api/poll/start", json={
        "title": "Tanpa riwayat",
        "candidates": [{"name": "A"}, {"name": "B"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["history_applied"] == {"comments": 0, "gifts": 0, "votes": 0}
    assert all(c["votes"] == 0 for c in body["candidates"])
    client.post("/api/poll/stop")

async def test_history_replay_counts_only_final_streak_event(client):
    """Mid-streak increments in stored history must not inflate replayed votes."""
    import uuid
    from datetime import datetime, timezone

    import app.main as app_main
    from app import database

    session_id = await database.create_session("streak_history_test")
    old_session = app_main.processor.session_id
    app_main.processor.session_id = session_id

    async def gift_ev(quantity: int, repeat_end: int):
        await database.insert_event(
            session_id=session_id,
            event_id=uuid.uuid4().hex,
            event_type="gift",
            username="combo_sender",
            nickname="Combo",
            payload={"data": {
                "gift_name": "Rose",
                "quantity": quantity,
                "diamond_count": 1,
                "gift_type": 1,
                "repeat_end": repeat_end,
            }},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    # Rose x4 combo: three mid-streak increments + final event.
    await gift_ev(1, 0)
    await gift_ev(2, 0)
    await gift_ev(3, 0)
    await gift_ev(4, 1)

    try:
        resp = client.post("/api/poll/start", json={
            "title": "Riwayat streak",
            "candidates": [
                {"name": "Merah", "gift_name": "Rose"},
                {"name": "Biru"},
            ],
            "include_history": True,
        })
        assert resp.status_code == 200
        body = resp.json()
        # Only the final event counts: 1 gift, 40 votes (4 x 1 diamond x 10).
        assert body["history_applied"] == {"comments": 0, "gifts": 1, "votes": 40}
        votes = {c["name"]: c["votes"] for c in body["candidates"]}
        assert votes["Merah"] == 40
        assert votes["Biru"] == 0
    finally:
        client.post("/api/poll/stop")
        app_main.processor.session_id = old_session

# ---------- Gift leaderboard scope ----------

async def test_leaderboard_scope_all_reuses_history(client):
    import uuid
    from datetime import datetime, timezone

    from app import database

    # Seed a gift in a session that is NOT the active one.
    session_id = await database.create_session("leaderboard_api_test")
    await database.insert_event(
        session_id=session_id,
        event_id=uuid.uuid4().hex,
        event_type="gift",
        username="zoe",
        nickname="Zoe",
        payload={"data": {"gift_name": "Rose", "quantity": 2, "diamond_count": 7}},
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # Default (session) scope: no active session -> empty board.
    assert client.get("/api/leaderboard").json() == []

    # scope=all reuses the stored history regardless of the active session.
    resp = client.get("/api/leaderboard", params={"scope": "all"})
    assert resp.status_code == 200
    board = resp.json()
    zoe = next(row for row in board if row["username"] == "zoe")
    assert zoe["total_diamonds"] == 14
    assert zoe["total_gifts"] == 2
