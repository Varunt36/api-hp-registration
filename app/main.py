import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.core.rate_limiter import RateLimitMiddleware
from app.routers import registration, admin, payment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Disable Swagger/ReDoc docs in production to avoid exposing API schema
app = FastAPI(
    title="HP Registration API",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)


# ── Security Headers Middleware ───────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        if settings.debug is False:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ── Request Body Size Limit Middleware ────────────────────────
MAX_BODY_SIZE = 64 * 1024  # 64 KB — more than enough for 4 members


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Exempt webhook endpoints (called by Stripe/PayPal, not user browsers)
        if request.url.path.startswith("/webhooks/"):
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
        return await call_next(request)


# Middleware order matters: outermost runs first
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=5, window_seconds=60)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(registration.router)
app.include_router(payment.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
