import logging
import time
from typing import Dict, List
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Module-level dict tracking timestamps of recent requests per IP.
# Stored at module level (not instance level) so tests can import and clear it.
_request_log: Dict[str, List[float]] = defaultdict(list)

# Max unique IPs to track — prevents unbounded memory growth from spoofed IPs
_MAX_TRACKED_IPS = 10000


def _get_client_ip(request: Request) -> str:
    """Extract client IP. Only trusts X-Forwarded-For from known reverse proxies.

    IMPORTANT: Trusting X-Forwarded-For from all clients allows rate limit bypass.
    Only use it when the request comes from a trusted proxy (load balancer, nginx, etc.).
    """
    client_host = request.client.host if request.client else "unknown"

    # Only trust X-Forwarded-For if request comes from localhost/Docker (reverse proxy)
    # In production, replace with your actual proxy IPs
    trusted_proxies = {"127.0.0.1", "::1", "172.17.0.1", "10.0.0.1"}
    if client_host in trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return client_host


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
        if request.method == "POST" and request.url.path in ("/register", "/create-payment"):
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
                logger.warning(f"Rate limit exceeded: ip={client_ip}, path={request.url.path}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                )

            _request_log[client_ip].append(now)

        response = await call_next(request)
        return response
