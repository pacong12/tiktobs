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
