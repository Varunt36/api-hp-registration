import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header

from app.core.exceptions import AdminForbiddenError, AdminUnauthorizedError
from app.core.supabase import supabase
from app.models.admin import AdminRegistrationRequest, AdminRegistrationResponse
from app.services.registration_service import create_admin_registration

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


def require_admin_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Verify a Supabase JWT and that the user has app_metadata.role == 'admin'.

    Role MUST live in app_metadata (server-set). user_metadata is user-editable
    and is intentionally not trusted.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AdminUnauthorizedError("Missing or malformed Authorization header.")
    jwt = authorization.split(" ", 1)[1].strip()
    if not jwt:
        raise AdminUnauthorizedError("Missing bearer token.")

    try:
        user = getattr(supabase.auth.get_user(jwt), "user", None)
    except Exception:
        logger.info("Admin JWT verification failed")
        raise AdminUnauthorizedError("Invalid or expired token.")
    if user is None:
        raise AdminUnauthorizedError("Invalid or expired token.")

    if (getattr(user, "app_metadata", None) or {}).get("role") != "admin":
        logger.warning(f"Non-admin user attempted /admin access: user_id={getattr(user, 'id', '?')}")
        raise AdminForbiddenError()

    return {"id": getattr(user, "id", None), "email": getattr(user, "email", None)}


@router.post("/registration", response_model=AdminRegistrationResponse)
def admin_registration(data: AdminRegistrationRequest, admin: dict = Depends(require_admin_user)):
    logger.info(f"Admin registration by {admin.get('email')}")
    return AdminRegistrationResponse(**create_admin_registration(
        full_name=data.full_name,
        email=data.email,
        dob=data.dob,
        gender=data.gender,
        country=data.country,
    ))
