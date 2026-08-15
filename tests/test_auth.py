"""Tests for the optional TIKTOBS_API_TOKEN authentication layer."""

import pytest


@pytest.fixture()
def token_enabled(monkeypatch):
    from app import state

    monkeypatch.setattr(state, "API_TOKEN", "s3cret-token")
    yield
    # API token auth also applies to the WebSocket handshake.


def test_no_token_required_by_default(client):
    """Without TIKTOBS_API_TOKEN everything stays open (backwards compatible)."""
    from app import state

    assert state.API_TOKEN == "" or state.API_TOKEN is None
    assert client.get("/api/status").status_code == 200


def test_auth_status_is_exempt_and_reports_requirement(client, token_enabled):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json()["token_required"] is True


def test_api_requires_token_when_configured(client, token_enabled):
    resp = client.get("/api/status")
    assert resp.status_code == 401


def test_valid_header_token_is_accepted(client, token_enabled):
    resp = client.get("/api/status", headers={"X-API-Token": "s3cret-token"})
    assert resp.status_code == 200


def test_valid_query_token_is_accepted(client, token_enabled):
    # Query tokens exist so OBS browser sources can authenticate via URL.
    resp = client.get("/api/status?token=s3cret-token")
    assert resp.status_code == 200


def test_wrong_token_is_rejected(client, token_enabled):
    resp = client.get("/api/status", headers={"X-API-Token": "wrong"})
    assert resp.status_code == 401
    resp = client.get("/api/status?token=wrong")
    assert resp.status_code == 401


def test_mutating_endpoints_are_protected_too(client, token_enabled):
    resp = client.post("/api/events/clear")
    assert resp.status_code == 401
    resp = client.post("/api/ticker", json={"speed": 100})
    assert resp.status_code == 401


def test_websocket_requires_token(client, token_enabled):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws"):
            pass
    assert excinfo.value.code == 4401


def test_websocket_accepts_valid_token(client, token_enabled):
    with client.websocket_connect("/ws?token=s3cret-token") as ws:
        # Connection accepted: the server keeps it open waiting for messages.
        assert ws is not None
