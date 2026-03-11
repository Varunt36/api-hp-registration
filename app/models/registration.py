from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator, model_validator
from datetime import date
from enum import Enum

ALLOWED_COUNTRIES = {"DE", "AT", "CH", "GB", "US", "IN", "NZ"}
MAX_MEMBERS_PER_REGISTRATION = 10


class Gender(str, Enum):
    male = "male"
    female = "female"


class MemberInput(BaseModel):
    """A single member in a registration group.

    Required: first_name, last_name, gender, dob
    Optional: middle_name, email, phone
    Note: The first member in the group MUST have an email (validated at RegistrationInput level).
    """
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    gender: Gender
    dob: date
    email: Optional[EmailStr] = None   # Validated as proper email format by Pydantic
    phone: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name_length(cls, v):
        v = v.strip()
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Name must be 1-100 characters")
        return v

    @field_validator("middle_name")
    @classmethod
    def validate_middle_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) > 100:
                raise ValueError("Middle name must be under 100 characters")
        return v

    @field_validator("dob")
    @classmethod
    def validate_dob(cls, v):
        if v > date.today():
            raise ValueError("Date of birth cannot be in the future")
        if v.year < 1900:
            raise ValueError("Date of birth is not valid")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) > 20:
                raise ValueError("Phone number too long")
        return v


class RegistrationInput(BaseModel):
    """Full registration payload from the FE.

    Validates:
      - country must be one of the allowed country codes
      - terms_accepted must be true
      - 1-10 members allowed
      - first member must have an email (used as primary contact for the group)
    """
    country: str
    karyakarta: str                    # Group leader / coordinator name
    terms_accepted: bool
    members: List[MemberInput]

    @field_validator("country")
    @classmethod
    def validate_country(cls, v):
        v = v.strip().upper()
        if v not in ALLOWED_COUNTRIES:
            raise ValueError(f"Country must be one of: {', '.join(sorted(ALLOWED_COUNTRIES))}")
        return v

    @field_validator("karyakarta")
    @classmethod
    def validate_karyakarta(cls, v):
        v = v.strip()
        if len(v) < 1 or len(v) > 200:
            raise ValueError("Karyakarta name must be 1-200 characters")
        return v

    @field_validator("terms_accepted")
    @classmethod
    def validate_terms(cls, v):
        if not v:
            raise ValueError("Terms must be accepted")
        return v

    @field_validator("members")
    @classmethod
    def validate_members_count(cls, v):
        if len(v) < 1:
            raise ValueError("At least one member is required")
        if len(v) > MAX_MEMBERS_PER_REGISTRATION:
            raise ValueError(f"Maximum {MAX_MEMBERS_PER_REGISTRATION} members per registration")
        return v

    @model_validator(mode="after")
    def validate_first_member_email(self):
        """First member's email is the primary contact for the entire group.
        All proxy emails (for members without email) go to this address."""
        if self.members and not self.members[0].email:
            raise ValueError("First member must have an email address")
        return self


class RegistrationResponse(BaseModel):
    success: bool
    reference: str          # e.g. "HP-2026-00042"
    member_count: int


class CheckinResponse(BaseModel):
    ticket_number: str      # e.g. "HP-2026-00042-M1"
    member_name: str
    checked_in: bool
