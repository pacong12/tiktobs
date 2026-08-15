"""Shared fixtures: run every test against an isolated temp data dir."""
import os
import shutil
import sys
import tempfile

import pytest

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch storage paths BEFORE importing app modules so nothing ever touches
# the real user data directory.
_TMP = tempfile.mkdtemp(prefix="tiktobs_test_")
_DATA = os.path.join(_TMP, "data")
os.makedirs(_DATA, exist_ok=True)

from app import database  # noqa: E402

database.DB_DIR = _DATA
database.DB_PATH = os.path.join(_DATA, "tiktok_live.db")


@pytest.fixture(scope="session")
def tmp_data_dir():
    yield _TMP
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def client(tmp_data_dir):
    """FastAPI TestClient wired to isolated storage."""
    import app.main as m

    # Redirect every module-level path used at request time.
    m.DATA_DIR = _DATA
    m.SOUNDS_DIR = os.path.join(_DATA, "sounds")
    os.makedirs(m.SOUNDS_DIR, exist_ok=True)
    m.SOUND_CONFIG_FILE = os.path.join(_DATA, "sound_config.json")
    m.ENV_FILE = os.path.join(tmp_data_dir, ".env")

    from fastapi.testclient import TestClient

    with TestClient(m.app) as c:
        yield c

    # Leave poll state clean for the next test (best effort).
    from app.poll import poll_manager

    if poll_manager.is_active:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(poll_manager.stop_poll())
        finally:
            loop.close()


def pytest_sessionfinish(session, exitstatus):
    """Close the shared DB connection so pytest can actually exit.

    aiosqlite runs a NON-daemon worker thread per connection. Tests open the
    shared connection but nothing ever closes it, so the interpreter blocked
    on that thread at shutdown and pytest hung after all tests had passed.
    """
    import asyncio

    from app import database
    from app.poll import poll_manager

    # Best effort: cancel any poll timer task left over from a test.
    timer = getattr(poll_manager, "timer_task", None)
    if timer is not None:
        try:
            if not timer.done():
                timer.cancel()
        except Exception:  # noqa: BLE001
            pass

    async def _close():
        await database.close_db()

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_close())
        finally:
            loop.close()
    except Exception:  # noqa: BLE001
        pass
