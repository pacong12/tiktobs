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
| `TIKTOBS_TEST_ENDPOINTS` | `0` | Enables the `/api/test/*` simulation endpoints used by the Poll Admin "simulate" buttons. **Disabled by default (production-safe).** Set to `1` to enable them for local testing. |
| `TIKTOBS_HOST` | `127.0.0.1` | Bind address for `python run_app.py`. |
| `TIKTOBS_PORT` | `8000` | Port for `python run_app.py` and Docker. |

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

## Production Checklist

Before going live with a real audience:

1. **Copy the config template** — `cp .env.example .env` and review each value.
2. **Disable test endpoints** — keep `TIKTOBS_TEST_ENDPOINTS=0` (the default).
   This prevents anyone from injecting fake votes/gifts via `/api/test/*`.
3. **Set an API token** if the app is reachable beyond localhost
   (`TIKTOBS_API_TOKEN=<long random string>`), then append `?token=…` to every
   OBS Browser Source URL.
4. **Retention** — decide how long to keep events (`TIKTOBS_RETENTION_DAYS`).
5. **Run the tests** — `.venv/bin/python -m pytest tests/ -q` (all green).
6. **Restart cleanly** and confirm `GET /api/settings` shows only `has_key` /
   `masked_key` (never the raw key).

> The committed codebase defaults to a locked-down production posture
> (test endpoints off, no token, retention 7 days). The local `.env` you create
> is never committed, so a fresh clone always starts safe.

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
| Gift Bubbles | `/gift-bubbles.html` | Floating square candidate bubbles on incoming gifts |

The running text messages, speed, and direction are managed on the Settings
page ("Running Text" card) and apply to open overlays instantly.

### Gift Bubbles (floating candidate overlay)

`/gift-bubbles.html` is a full-screen transparent layer. Incoming gifts spawn
small **square bubbles** that float up the screen with a gentle sway and fade
out:

- A gift assigned to an active poll candidate spawns a **candidate bubble** —
  the candidate's photo framed in their border color, with the official gift
  icon and `×N` count.
- Any other gift spawns a **generic gift bubble** — a big official gift icon
  and the sender's name (gold frame), so every gift still gets a visual.
- Streakable/combo gifts (`gift_type == 1`) spawn a single bubble when the
  combo lands (`repeat_end == 1`), matching how poll votes are counted, so
  mid-combo events do not flood the screen.
- Candidate bubbles are driven by both the `event` stream and the
  `poll_gift_vote` message (what the Poll Admin "simulate gift vote" button
  emits), with de-duplication so a real candidate gift never bubbles twice.
- A safety cap keeps at most 18 bubbles on screen at once.

### Vote Overlay Badges (wins + gifts)

Each candidate card on the vote overlay can carry two floating badges:

- **Win badge** (win ×N) — how many poll rounds that candidate has won so far
  in the current session. A win is recorded every time a round ends with a
  single clear winner (at least one vote cast, no tie). Wins are stored in the
  database keyed by the live session (or `local` when no live connection), so
  they accumulate across rounds and survive app restarts within the session.
- **Gift badge** — the gift assigned to the candidate, shown as its official
  TikTok icon only (loaded from the TikTok CDN, emoji fallback; hover for the
  name), so viewers instantly see which gift boosts which candidate.

Both badges pin onto the card's top border in a futuristic style that follows
the candidate's border color, update live via WebSocket, and scale down
automatically on the smaller bento-grid cards.

### Card colors & layout

- Each candidate can have an **accent color** (border color), picked in Poll
  Admin via a color input. When empty, a built-in neon palette is assigned by
  rank. The color drives the border, number chip, votes outline, percentage
  badge, win badge, and a thin card gradient.
- Cards are transparent with a thin color gradient so no-background PNGs show
  through. Bottom of each card: one horizontal row `[number][votes][%]` with
  the candidate name underneath (no progress bar).

### Reuse candidates from history

On the Poll Admin page, every card in the **Riwayat Ronde** (round history)
panel has a **♻️ Pakai lagi** button. Clicking it refills the candidate setup
form with that round's candidates (name, photo URL, and assigned gift), so you
can re-run the same match-up without retyping anything.

### Gifts that match no candidate (comment fallback)

Gift votes use strict isolation: during an active poll, a gift only counts
directly for the candidate whose assigned gift name matches it
(case/emoji/whitespace insensitive). A gift assigned to **no** candidate never
leaks to another candidate directly — but instead of dropping it, the app
applies a **comment fallback**:

- Every comment that registers a vote also records the sender's *vote intent*
  (which candidate, which comment, when). Intent is scoped to the current
  round (cleared when a new poll starts), and the latest vote comment wins.
  Non-vote chatter like "wkwkwk" does not overwrite the intent.
- When such a user sends a gift that matches no candidate's gift, the gift is
  credited to the candidate of their last vote comment, using the same
  1 diamond = 1 vote conversion (e.g. comment `01`, then send a Rocket → all
  of the Rocket's diamond value goes to candidate #1).
- Fallback votes are marked as such: the `poll_gift_vote` WebSocket message
  carries `via_comment` with the backing comment. The Vote Gift Alert overlay
  shows a small "via last comment" badge, the vote overlay shows a
  `via komentar` toast, the candidate bubble credits the right candidate, and
  Poll Admin shows a toast explaining where the votes came from.
- Senders with **no** vote comment this round count for nobody: the server
  broadcasts `poll_gift_ignored` (`reason: no_vote_comment`) so the Vote Gift
  Alert overlay shows a red "+0 VOTES" card, the vote overlay shows a red
  on-stream warning banner, Gift Bubbles shows a red bubble with the sender's
  profile picture, Poll Admin shows a warning toast, and the event is logged
  at INFO level. The fallback also applies to the session-history
  replay at poll start (events replay in chronological order).

> 📄 Full technical reference: [`docs/05-gift-voting-fallback.md`](docs/05-gift-voting-fallback.md)
> · Operator guide (Bahasa Indonesia): [`docs/06-panduan-gift-vote-fallback.md`](docs/06-panduan-gift-vote-fallback.md)

---

## TikTok Gift Schema (streak / combo handling)

Gift events follow TikTok's `WebcastGiftMessage` protobuf schema. The two
fields that matter for correct counting are:

- `gift.type` — `1` means the gift is **streakable** (combo-able, e.g. Rose,
  Finger Heart). Anything else is a one-shot gift (e.g. Lion, TikTok Universe).
- `repeat_end` — `1` marks the **final** event of a streak, which carries the
  full `repeat_count`. Mid-streak increments arrive as separate events with
  `repeat_end=0` and a growing `repeat_count`.

Therefore a `Rose x5` combo emits five events. Counting every event (or
summing their growing quantities) would inflate totals, so tiktobs only
tallies votes and leaderboard diamonds from the final (`repeat_end=1`)
event, using `repeat_count x diamond_count`. Mid-streak events are still
stored and broadcast so the live feed stays responsive.

A verified snapshot of TikTok's gift catalog (749 gifts: id, name, coin
price, icon URL) is bundled at `app/gift_catalog.json` for reference. The vote overlay resolves gift names to official TikTok icons via `static/gift-icons.js`. Note that TikTok
reuses gift names with different prices (e.g. "Love you" exists as both a
1-coin and a 199-coin gift), so gift names are matched strictly and
case-insensitively.

While votes and leaderboard totals only move on the final event, the
overlays use the mid-streak events for live feedback:

- **Recent Gifts** collapses a whole combo into a single row whose `xN`
  counter climbs in place until the combo ends.
- **Gift Alert** shows one alert per combo (sound plays once) and updates
  the counter as the streak grows.
- **Vote Overlay** shows a floating toast naming the gift, the climbing
  count, and the candidate receiving it.

To try this without a live stream, `POST /api/test/gift-combo`
(optional body `{username, gift_name, count, diamond_count}`) emits a full
synthetic streak.

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
  - `processor.py`: Normalizes, validates, and routes events (including streak-safe gift counting).
  - `poll.py`: In-memory poll state machine.
  - `gift_catalog.json`: Verified reference of 749 TikTok gifts (id, name, coins).
  - `providers/`: TikTok Live client connection wrappers.
- `static/`: Frontend dashboard assets (HTML, CSS, JS).
- `docs/`: Technical integration details.
- `tests/`: Integration and unit test cases.
- `data/`: SQLite data storage directory.
- `requirements.txt`: Python package requirements.
