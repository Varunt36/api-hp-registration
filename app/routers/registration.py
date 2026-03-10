import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.models.registration import RegistrationInput, RegistrationResponse
from app.services.registration_service import create_registration, process_qr_and_emails

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
def register(data: RegistrationInput, background_tasks: BackgroundTasks):
    try:
        result = create_registration(data)

        # QR generation + email sending in background
        background_tasks.add_task(
            process_qr_and_emails,
            result["registration_id"],
            result["members_data"],
            data.members[0].email,
        )

        return RegistrationResponse(
            success=True,
            reference=result["reference"],
            member_count=result["member_count"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Registration failed")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")
