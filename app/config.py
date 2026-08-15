"""Shared application configuration: base paths and .env loading.

Centralizes logic that used to be duplicated (and inconsistent) across
app/main.py and the two TikTok providers.
"""

import os
import sys


def get_base_dir() -> str:
    """Returns the directory containing the executable or the script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
ENV_FILE = os.path.join(BASE_DIR, ".env")

def load_env_file() -> None:
    """Load the .env file next to the app into os.environ.

    Runs automatically at import time so that every module reading
    ``os.getenv`` (TIKTOBS_API_TOKEN, TIKTOBS_TEST_ENDPOINTS,
    TIKTOBS_RETENTION_DAYS, TIKTOBS_PORT, ...) picks up .env values.
    Real environment variables always take precedence over .env entries
    (existing keys are never overwritten).
    """
    try:
        if not os.path.exists(ENV_FILE):
            return
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key or key in os.environ:
                    continue
                os.environ[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass


load_env_file()


def load_sign_api_key() -> str | None:
    """Reads TIKTOK_SIGN_API_KEY from the environment, falling back to .env.

    Returns None when no key is configured. Note: this always resolves the
    .env file next to the app (not relative to the current working
    directory), so it works regardless of how the app was launched.
    """
    key = os.getenv("TIKTOK_SIGN_API_KEY")
    if key:
        return key.strip() or None
    try:
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("TIKTOK_SIGN_API_KEY="):
                        value = line.split("=", 1)[1].strip().strip('"').strip("'")
                        return value or None
    except OSError:
        pass
    return None
