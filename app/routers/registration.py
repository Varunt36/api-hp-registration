from fastapi import APIRouter

from app.models.registration import RegistrationInput, RegistrationResponse
from app.services.registration_service import check_country_quota, check_duplicate_member

router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
def register(data: RegistrationInput):
    check_country_quota(data.country, len(data.members))

    if data.members[0].email:
        check_duplicate_member(data.members[0].email)

    return RegistrationResponse(
        success=True,
        reference="pending",
        member_count=len(data.members),
    )
