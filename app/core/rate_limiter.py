import time
from typing import Dict, List
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Module-level dict tracking timestamps of recent requests per IP.
# Stored at module level (not instance level) so tests can import and clear it.
_request_log: Dict[str, List[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter for the /register endpoint.

    How it works:
      - Tracks request timestamps per client IP in a dict
      - On each request, removes timestamps older than the window
      - If remaining count >= max_requests, returns 429 Too Many Requests
      - Only applies to POST /register (other endpoints are unrestricted)

    Note: In-memory only — resets on server restart, not shared across workers.
    For production with multiple workers, use Redis-backed rate limiting.
    """

    def __init__(self, app, max_requests: int = 5, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        # Only rate-limit the registration endpoint
        if request.url.path == "/register" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()

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
