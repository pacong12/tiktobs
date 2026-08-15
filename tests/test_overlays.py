"""Tests for the DB-backed OBS overlay registry (/api/overlays)."""


def test_overlays_endpoint_returns_seeded_list(client):
    resp = client.get("/api/overlays")
    assert resp.status_code == 200
    overlays = resp.json()["overlays"]

    expected = {"leaderboard", "gift-alert", "recent-gifts",
                "vote-overlay", "ticker", "gift-bubbles"}
    keys = {o["key"] for o in overlays}
    assert expected <= keys

    # Every entry must expose the fields the dashboard renders.
    for o in overlays:
        assert o["label"]
        assert o["url"].endswith(".html")
        assert "accent" in o and "icon" in o and "description" in o


def test_overlays_are_ordered_and_enabled(client):
    overlays = client.get("/api/overlays").json()["overlays"]
    orders = [o["sort_order"] for o in overlays]
    assert orders == sorted(orders)
    assert all(o["enabled"] for o in overlays)


def test_default_overlays_have_unique_keys():
    from app.database import DEFAULT_OVERLAYS

    keys = [o["key"] for o in DEFAULT_OVERLAYS]
    assert len(keys) == len(set(keys))
    for o in DEFAULT_OVERLAYS:
        assert o["key"] and o["label"]
        assert o["url"].startswith("/")


def test_seed_sql_is_idempotent():
    """INSERT OR IGNORE on the UNIQUE key must not duplicate rows on re-seed.

    Uses a standalone in-memory sqlite connection so it never touches the
    app's shared aiosqlite connection.
    """
    import sqlite3

    from app.database import DEFAULT_OVERLAYS

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE overlays (
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
        """
    )
    sql = (
        "INSERT OR IGNORE INTO overlays "
        "(key, label, url, icon, description, accent, sort_order, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1)"
    )
    # Seed three times in a row (simulates repeated startups).
    for _ in range(3):
        for i, ov in enumerate(DEFAULT_OVERLAYS):
            conn.execute(
                sql,
                (ov["key"], ov["label"], ov["url"], ov["icon"],
                 ov["description"], ov["accent"], i),
            )

    count = conn.execute("SELECT COUNT(*) FROM overlays").fetchone()[0]
    conn.close()
    assert count == len(DEFAULT_OVERLAYS)
