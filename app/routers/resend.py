import logging

from fastapi import APIRouter, Depends, Header

from app.core.exceptions import AuthError
from app.core.supabase import supabase
from app.models.resend import ResendConfirmationRequest, ResendConfirmationResponse
from app.services.resend_service import resend_confirmation

logger = logging.getLogger(__name__)
router = APIRouter()


def get_current_admin(authorization: str | None = Header(default=None)):
    """Validate the admin's Supabase JWT from the Authorization header.

    Missing/malformed/invalid/expired token -> 401. Because there is no public
    signup, any valid Supabase user is treated as an admin.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise AuthError("Missing bearer token.")
    try:
        result = supabase.auth.get_user(token)
    except Exception:
        raise AuthError("Invalid or expired token.")
    if result is None or getattr(result, "user", None) is None:
        raise AuthError("Invalid or expired token.")
    return result.user


@router.post("/resend-confirmation", response_model=ResendConfirmationResponse)
def resend_confirmation_endpoint(
    data: ResendConfirmationRequest,
    _admin=Depends(get_current_admin),
):
    result = resend_confirmation(str(data.email), data.reference)
    return ResendConfirmationResponse(**result)
