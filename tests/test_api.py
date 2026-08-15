"""End-to-end tests for the poll rounds, custom gifts, sound config, and CSV export."""

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

# ---------- Custom gifts ----------

def test_custom_gift_crud(client):
    add = client.post("/api/gifts", json={"name": "Naga Api", "diamonds": 500})
    assert add.status_code == 200
    assert add.json()["gift"]["name"] == "Naga Api"

    listed = client.get("/api/gifts").json()["gifts"]
    assert any(g["name"] == "Naga Api" and g["diamonds"] == 500 for g in listed)

    # Upsert with a different diamond count
    client.post("/api/gifts", json={"name": "Naga Api", "diamonds": 999})
    listed = client.get("/api/gifts").json()["gifts"]
    dragons = [g for g in listed if g["name"] == "Naga Api"]
    assert len(dragons) == 1
    assert dragons[0]["diamonds"] == 999

    delete = client.delete("/api/gifts/Naga%20Api")
    assert delete.status_code == 200
    assert all(g["name"] != "Naga Api" for g in client.get("/api/gifts").json()["gifts"])

    missing = client.delete("/api/gifts/TidakAda")
    assert missing.status_code == 404


def test_custom_gift_rejects_empty_or_long_name(client):
    assert client.post("/api/gifts", json={"name": "  "}).status_code == 400
    assert client.post("/api/gifts", json={"name": "x" * 100}).status_code == 400


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
