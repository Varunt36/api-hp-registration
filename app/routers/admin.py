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
    """Verify the request carries a Supabase JWT for a user with role=admin.

    Raises 401 if the token is missing or invalid, 403 if the user is authenticated
    but lacks the admin role. The role MUST live in app_metadata (server-set, not
    user-editable); user_metadata is unsafe for authorization decisions.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AdminUnauthorizedError("Missing or malformed Authorization header.")

    jwt = authorization.split(" ", 1)[1].strip()
    if not jwt:
        raise AdminUnauthorizedError("Missing bearer token.")

    try:
        response = supabase.auth.get_user(jwt)
    except Exception:
        logger.info("Admin JWT verification failed")
        raise AdminUnauthorizedError("Invalid or expired token.")

    user = getattr(response, "user", None) if response else None
    if user is None:
        raise AdminUnauthorizedError("Invalid or expired token.")

    app_metadata = getattr(user, "app_metadata", None) or {}
    if app_metadata.get("role") != "admin":
        logger.warning(f"Non-admin user attempted /admin access: user_id={getattr(user, 'id', 'unknown')}")
        raise AdminForbiddenError()

    return {"id": getattr(user, "id", None), "email": getattr(user, "email", None)}


@router.post("/registration", response_model=AdminRegistrationResponse)
def admin_registration(
    data: AdminRegistrationRequest,
    admin: dict = Depends(require_admin_user),
):
    logger.info(f"Admin registration requested by {admin.get('email')}")
    return AdminRegistrationResponse(**create_admin_registration(
        full_name=data.full_name,
        email=data.email,
        dob=data.dob,
        gender=data.gender,
        country=data.country,
    ))
