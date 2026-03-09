from pydantic import BaseModel
from datetime import date


class MemberInput(BaseModel):
    first_name: str
    middle_name: str | None = None
    last_name: str
    gender: str
    dob: date
    email: str | None = None
    phone: str | None = None


class RegistrationInput(BaseModel):
    country: str
    karyakarta: str
    members: list[MemberInput]


class RegistrationResponse(BaseModel):
    success: bool
    reference: str
    member_count: int


class CheckinResponse(BaseModel):
    ticket_number: str
    member_name: str
    checked_in: bool
