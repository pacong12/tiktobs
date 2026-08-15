"""Security tests: API key masking, settings semantics, and test-endpoint gating."""

import pytest


@pytest.fixture()
def clean_key_state(monkeypatch):
    """Ensure settings tests see a known key state and restore it afterwards."""
    import app.main as m

    monkeypatch.setattr(m, "sign_api_key", "")
    monkeypatch.delenv("TIKTOK_SIGN_API_KEY", raising=False)
    yield


def test_settings_get_never_returns_raw_key(client, clean_key_state, monkeypatch):
    monkeypatch.setenv("TIKTOK_SIGN_API_KEY", "supersecret123")

    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()

    # The raw key must never be exposed anywhere in the response.
    assert "tiktok_sign_api_key" not in data
    assert "supersecret123" not in resp.text
    assert data["has_key"] is True
    assert data["masked_key"].endswith("t123")


def test_settings_get_without_key(client, clean_key_state):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_key"] is False
    assert data["masked_key"] == ""


def test_settings_post_omitted_key_is_unchanged(client, clean_key_state, monkeypatch):
    monkeypatch.setenv("TIKTOK_SIGN_API_KEY", "keepme1234")

    resp = client.post("/api/settings", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unchanged"
    # Nothing was overwritten.
    assert resp.json().get("masked_key") is None


def test_settings_post_sets_key_and_masks_response(client, clean_key_state):
    resp = client.post("/api/settings", json={"tiktok_sign_api_key": "brandnewkey99"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["has_key"] is True
    assert data["masked_key"].endswith("y99")
    assert "brandnewkey99" not in resp.text  # raw key not echoed back
    assert data["restart_required"] is True  # no key -> key: provider changes


def test_settings_post_empty_string_clears_key(client, clean_key_state, monkeypatch):
    monkeypatch.setenv("TIKTOK_SIGN_API_KEY", "oldkey1234")

    resp = client.post("/api/settings", json={"tiktok_sign_api_key": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_key"] is False
    assert data["restart_required"] is True


def test_test_endpoints_can_be_disabled(client, monkeypatch):
    import app.main as m

    monkeypatch.setattr(m, "TEST_ENDPOINTS_ENABLED", False)
    for path in ("/api/test/comment-vote", "/api/test/gift-vote", "/api/test/gift-normal"):
        resp = client.post(path)
        assert resp.status_code == 403, path


def test_test_endpoints_enabled_by_default(client, monkeypatch):
    import app.main as m

    monkeypatch.setattr(m, "TEST_ENDPOINTS_ENABLED", True)
    # No active poll -> 400 (business error), proving the gate itself passed.
    resp = client.post("/api/test/comment-vote")
    assert resp.status_code == 400
