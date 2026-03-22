import logging
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_request_log = defaultdict(list)
_MAX_TRACKED_IPS = 10000

RATE_LIMITED_PATHS = {"/register", "/create-payment"}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 20, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path in RATE_LIMITED_PATHS:
            client_ip = _get_client_ip(request)
            now = time.time()

            if len(_request_log) > _MAX_TRACKED_IPS:
                _request_log.clear()

            _request_log[client_ip] = [
                t for t in _request_log[client_ip]
                if now - t < self.window_seconds
            ]

            if len(_request_log[client_ip]) >= self.max_requests:
                logger.warning(f"Rate limit exceeded: ip={client_ip}, path={request.url.path}")
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}},
                )

            _request_log[client_ip].append(now)

        return await call_next(request)
