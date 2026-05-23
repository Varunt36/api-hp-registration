import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.exceptions import AppError
from app.routers import payment

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
for _noisy in ("httpcore", "httpcore.http2", "httpx", "hpack", "hpack.hpack", "hpack.table", "urllib3", "urllib3.connectionpool", "stripe"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def _mask(s: str) -> str:
    if not s:
        return "<MISSING>"
    return f"{s[:8]}...{s[-4:]}" if len(s) > 12 else "<set>"


logger.info("=" * 70)
logger.info("HP Registration API starting")
logger.info(f"  STRIPE_SECRET_KEY     = {_mask(settings.stripe_secret_key)}")
logger.info(f"  STRIPE_WEBHOOK_SECRET = {_mask(settings.stripe_webhook_secret)}")
logger.info(f"  RESEND_API_KEY        = {_mask(settings.resend_api_key)}")
logger.info(f"  RESEND_FROM_EMAIL     = {settings.resend_from_email}")
logger.info(f"  FRONTEND_URL          = {settings.frontend_url}")
logger.info("=" * 70)

# NOTE: get_remote_address uses the socket peer. Safe only when not behind a reverse proxy.
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="HP Registration API",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
_DEFAULT_CSP = "default-src 'self'; frame-ancestors 'none'"
_DOCS_CSP = "default-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers[k] = v
        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path.startswith(_DOCS_PATHS) else _DEFAULT_CSP
        )
        return response


_MAX_BODY_SIZE = 64 * 1024
_MAX_WEBHOOK_BODY_SIZE = 1024 * 1024


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = _MAX_WEBHOOK_BODY_SIZE if request.url.path.startswith("/webhooks/") else _MAX_BODY_SIZE
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > limit:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large."}},
            )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[u.strip() for u in settings.frontend_url.split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(payment.router)


@app.get("/health")
def health():
    return {"status": "ok"}
