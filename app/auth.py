"""Optional API token authentication.

Set TIKTOBS_API_TOKEN in the environment (or .env) to require a token on
every /api/* request and on the /ws WebSocket. When unset, behaviour is
exactly as before (no auth).

Tokens are accepted from:
- the `X-API-Token` header, or
- a `token` query parameter (for OBS browser sources and WebSocket URLs).

`GET /api/auth/status` is always exempt so clients can detect the
requirement, and CORS preflight (OPTIONS) passes untouched.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import state

# Paths that never require a token.
EXEMPT_PATHS = {"/api/auth/status"}


def token_is_valid(provided: str | None) -> bool:
    return bool(state.API_TOKEN) is False or provided == state.API_TOKEN


def extract_token(request: Request) -> str | None:
    header = request.headers.get("X-API-Token")
    if header:
        return header
    return request.query_params.get("token")


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # CORS preflight must always pass.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path.startswith("/api") and path not in EXEMPT_PATHS:
            if state.API_TOKEN and not token_is_valid(extract_token(request)):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API token (X-API-Token header or ?token= parameter)."},
                )

        return await call_next(request)


def websocket_token_ok(request: Request) -> bool:
    """Validates a WebSocket handshake request against the configured token."""
    if not state.API_TOKEN:
        return True
    return extract_token(request) == state.API_TOKEN
