import logging
from fastapi import APIRouter, HTTPException
from app.models.registration import RegistrationInput, RegistrationResponse
from app.services.registration_service import check_country_quota

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
def register(data: RegistrationInput):
    """Validate registration data and return success.

    This endpoint only validates the data — no DB insert, no payment.
    The actual registration happens after payment via /create-payment → Stripe webhook.
    FE uses this to validate before redirecting to payment.
    """
    try:
        check_country_quota(data.country, len(data.members))

        return RegistrationResponse(
            success=True,
            reference="pending",
            member_count=len(data.members),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Registration validation failed")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")
