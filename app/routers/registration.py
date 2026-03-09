from fastapi import APIRouter, HTTPException
from app.models.registration import RegistrationInput, RegistrationResponse
from app.services.registration_service import create_registration

router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
def register(data: RegistrationInput):
    """
    Register a group with one or more members.

    - First member MUST have an email (primary contact).
    - Other members: email and phone are optional.
    - If a member has no email, their QR code is sent to the first member's email.

    **Request body example:**
    ```json
    {
      "country": "DE",
      "karyakarta": "John Doe",
      "members": [
        {
          "first_name": "John",
          "last_name": "Doe",
          "gender": "male",
          "dob": "1990-05-15",
          "email": "john@example.com",
          "phone": "+491234567890"
        },
        {
          "first_name": "Jane",
          "last_name": "Doe",
          "gender": "female",
          "dob": "1992-08-20"
        }
      ]
    }
    ```

    **Response example:**
    ```json
    {
      "success": true,
      "reference": "HP-2026-00001",
      "member_count": 2
    }
    ```
    """
    if not data.members:
        raise HTTPException(status_code=400, detail="At least one member is required")

    if not data.members[0].email:
        raise HTTPException(status_code=400, detail="First member must have an email address")

    try:
        result = create_registration(data)
        return RegistrationResponse(success=True, **result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
