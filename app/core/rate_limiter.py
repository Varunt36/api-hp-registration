import time
from typing import Dict, List
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Module-level state so it can be reset in tests
_request_log: Dict[str, List[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 5, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/register" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()

            # Remove expired entries
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
