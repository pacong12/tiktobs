# TikTok LIVE Connection & Data Collector (Phase 1)

A real-time data collector that connects to public TikTok LIVE streams, processes events, persists them in a local SQLite database, and broadcasts them via WebSockets to a sleek glassmorphic dashboard.

---

## Quickstart

### 1. Activate Virtual Environment
Activate the local virtual environment:
```powershell
.venv\Scripts\activate
```

### 2. Start the FastAPI Web Server
Run Uvicorn to host the app:
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 3. Open the Dashboard
Navigate in your browser to:
[http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Running Verification Tests
Execute the integration test suite:
```powershell
.venv\Scripts\python.exe tests/verify.py
```

Or with pytest (dev dependencies: `pip install -r requirements-dev.txt`):
```powershell
.venv\Scripts\python.exe -m pytest tests/
```

---

## Configuration

All settings are optional. They can be set as environment variables or in a
`.env` file placed next to the app (executable or project root).

| Variable | Default | Description |
|:---|:---|:---|
| `TIKTOK_SIGN_API_KEY` | *(none)* | EulerStream signing API key. When set, the app uses the managed cloud WebSocket provider; otherwise it falls back to the local `TikTokLive` library. Can also be managed from the Settings page in the dashboard. |
| `TIKTOBS_RETENTION_DAYS` | `7` | Events older than this many days are purged from the database (on startup and daily). Set to `0` to keep events forever. |
| `TIKTOBS_TEST_ENDPOINTS` | `1` | Enables the `/api/test/*` simulation endpoints used by the Poll Admin "simulate" buttons. Set to `0` to disable them (they answer 403). |

> **Note:** The API key can also be changed at runtime from the dashboard
> (Settings page). It is never displayed in full — only a masked preview is
> shown. Restart the app after adding or removing a key so the correct
> provider is selected.

---

## OBS Browser Source Overlays

Each overlay is a standalone page with a transparent background, ready to be
added to OBS as a Browser Source (use the Copy buttons on the dashboard for
the full URL):

| Overlay | URL | Purpose |
|:---|:---|:---|
| Gift Leaderboard | `/overlay.html` | Top gifters of the active session |
| Gift Alert | `/gift-alert.html` | Animated alert + sound on incoming gifts |
| Recent Gifts Ticker | `/recent-gifts.html` | Feed of the latest gifts |
| Vote / Poll | `/vote-overlay.html` | Live poll progress |
| Running Text | `/ticker.html` | Scrolling text for ads, announcements, etc. |

The running text messages, speed, and direction are managed on the Settings
page ("Running Text" card) and apply to open overlays instantly.

---

## Project Structure

- `app/`: Python backend source code.
  - `database.py`: Handles SQLite schemas and persistence.
  - `models.py`: Defines the `TikTokEvent` model.
  - `bus.py`: EventBus publish-subscribe utility.
  - `processor.py`: Normalizes, validates, and routes events.
  - `main.py`: Entrypoint routes and WebSocket broadcaster.
  - `providers/`: TikTok Live client connection wrappers.
- `static/`: Frontend dashboard assets (HTML, CSS, JS).
- `docs/`: Technical integration details.
- `tests/`: Integration and unit test cases.
- `data/`: SQLite data storage directory.
- `requirements.txt`: Python package requirements.
