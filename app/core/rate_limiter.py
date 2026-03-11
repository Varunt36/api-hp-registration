import time
from typing import Dict, List
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Module-level dict tracking timestamps of recent requests per IP.
# Stored at module level (not instance level) so tests can import and clear it.
_request_log: Dict[str, List[float]] = defaultdict(list)

# Max unique IPs to track — prevents unbounded memory growth from spoofed IPs
_MAX_TRACKED_IPS = 10000


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2 — first IP is the real client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter for the /register endpoint.

    How it works:
      - Tracks request timestamps per client IP in a dict
      - On each request, removes timestamps older than the window
      - If remaining count >= max_requests, returns 429 Too Many Requests
      - Only applies to POST /register (other endpoints are unrestricted)
      - Caps tracked IPs to prevent memory exhaustion from spoofed IPs

    Note: In-memory only — resets on server restart, not shared across workers.
    For production with multiple workers, use Redis-backed rate limiting.
    """

    def __init__(self, app, max_requests: int = 5, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/register" and request.method == "POST":
            client_ip = _get_client_ip(request)
            now = time.time()

            # Evict oldest IPs if dict grows too large (DoS protection)
            if len(_request_log) > _MAX_TRACKED_IPS:
                _request_log.clear()

            # Sliding window: keep only timestamps within the last N seconds
            _request_log[client_ip] = [
                t for t in _request_log[client_ip]
                if now - t < self.window_seconds
            ]

            if len(_request_log[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                )

            _request_log[client_ip].append(now)

        response = await call_next(request)
        return response
