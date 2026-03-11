import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.models.registration import RegistrationInput, RegistrationResponse
from app.services.registration_service import create_registration, process_qr_and_emails

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
def register(data: RegistrationInput, background_tasks: BackgroundTasks):
    """Register a group with one or more members.

    Synchronous part (user waits):
      - Validate input (Pydantic handles this before we get here)
      - Check country quota
      - Save registration + members to DB

    Async part (runs after response is sent):
      - Generate QR codes and upload to Supabase Storage
      - Send emails (QR + Travel Guide + Social)
    """
    try:
        result = create_registration(data)

        # Schedule QR generation + email sending as a background task.
        # This runs AFTER the response is returned to the FE,
        # so the user doesn't wait for QR generation and email delivery.
        background_tasks.add_task(
            process_qr_and_emails,
            result["registration_id"],
            result["members_data"],
            data.members[0].email,  # primary email = first member's email
            result["reference"],
        )

        return RegistrationResponse(
            success=True,
            reference=result["reference"],
            member_count=result["member_count"],
        )
    except ValueError as e:
        # Business logic errors (quota exceeded, etc.) → 400 with clear message
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        # Unexpected errors → log full traceback, return generic message to client.
        # Never expose internal error details (DB errors, stack traces) to FE.
        logger.exception("Registration failed")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")
