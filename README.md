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
| `TIKTOBS_API_TOKEN` | *(none)* | When set, every `/api/*` request and the `/ws` socket require this token (via the `X-API-Token` header or a `?token=` query parameter). Leave unset for the default open, local-only mode. See [Security](#security). |
| `TIKTOBS_RETENTION_DAYS` | `7` | Events older than this many days are purged from the database (on startup and daily). Set to `0` to keep events forever. |
| `TIKTOBS_TEST_ENDPOINTS` | `1` | Enables the `/api/test/*` simulation endpoints used by the Poll Admin "simulate" buttons. Set to `0` to disable them (they answer 403). |

> **Note:** The API key can also be changed at runtime from the dashboard
> (Settings page). It is never displayed in full — only a masked preview is
> shown. Restart the app after adding or removing a key so the correct
> provider is selected.

## Security

By default the HTTP API is **open** and intended for trusted local networks
(your streaming PC and OBS). Before exposing the app beyond that, set a token:

```
TIKTOBS_API_TOKEN="choose-a-long-random-string"
```

- Every `/api/*` call and the `/ws` WebSocket then require the token.
- `GET /api/auth/status` stays open so clients can detect the requirement.
- The dashboard Settings page has an **API Access Token** card: enter the token
  once and the browser stores it locally, sending it automatically with every
  request (`auth.js` wraps `fetch` and `WebSocket` on every page).
- For OBS Browser Sources, append `?token=YOUR_TOKEN` to the overlay URL.
- Restart the app after setting or changing the token.

---

## Running with Docker

Alternatively, run the app in a container (useful on a server or NAS):

```bash
docker compose up -d        # build + start (data persists in a volume)
docker compose logs -f      # follow logs
docker compose down         # stop
```

Or without compose:

```bash
docker build -t tiktobs .
docker run -d --name tiktobs -p 8000:8000 -v tiktobs-data:/app/data tiktobs
```

- The dashboard and all overlays are then served from `http://localhost:8000`.
- Persistent state (database, ticker/sound config, logs) lives in the
  `tiktobs-data` volume.
- Pass configuration (`TIKTOK_SIGN_API_KEY`, `TIKTOBS_API_TOKEN`, ...) via
  `env_file: .env` in `docker-compose.yml` or `docker run -e VAR=value`.

---

## OBS Browser Source Overlays

Each overlay is a standalone page with a transparent background, ready to be
added to OBS as a Browser Source (use the Copy buttons on the dashboard for
the full URL):

| Overlay | URL | Purpose |
|:---|:---|:---|
| Gift Leaderboard | `/overlay.html` | Top gifters — toggle between the active session and full stored history |
| Gift Alert | `/gift-alert.html` | Animated alert + sound on incoming gifts |
| Recent Gifts Ticker | `/recent-gifts.html` | Feed of the latest gifts |
| Vote / Poll | `/vote-overlay.html` | Live poll progress |
| Running Text | `/ticker.html` | Scrolling text for ads, announcements, etc. |

The running text messages, speed, and direction are managed on the Settings
page ("Running Text" card) and apply to open overlays instantly.

---

## Project Structure

- `app/`: Python backend source code.
  - `main.py`: Assembles the FastAPI app (lifespan, middleware, routers, mounts).
  - `state.py`: Shared runtime state (paths, provider, WebSocket manager).
  - `schemas.py`: Pydantic request models shared by the routers.
  - `auth.py`: Optional `TIKTOBS_API_TOKEN` middleware and WebSocket check.
  - `routers/`: HTTP endpoints split by concern (connection, events, poll, media, settings, testsim).
  - `database.py`: Handles SQLite schemas and persistence.
  - `models.py`: Defines the `TikTokEvent` model.
  - `bus.py`: EventBus publish-subscribe utility.
  - `processor.py`: Normalizes, validates, and routes events.
  - `poll.py`: In-memory poll state machine.
  - `providers/`: TikTok Live client connection wrappers.
- `static/`: Frontend dashboard assets (HTML, CSS, JS).
- `docs/`: Technical integration details.
- `tests/`: Integration and unit test cases.
- `data/`: SQLite data storage directory.
- `requirements.txt`: Python package requirements.
