from typing import List, Optional

from pydantic import BaseModel, EmailStr


class ResendConfirmationRequest(BaseModel):
    email: EmailStr
    reference: Optional[str] = None


class ResendConfirmationResponse(BaseModel):
    sent: int
    reference: str


class RegistrationCandidate(BaseModel):
    reference: str
    lead_name: str
    member_count: int
    country: str


class MultipleRegistrationsResponse(BaseModel):
    """Shape of the 409 candidate list (documented for the FE/OpenAPI)."""

    candidates: List[RegistrationCandidate]
