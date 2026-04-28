from datetime import date

from pydantic import BaseModel, EmailStr, field_validator

from app.models.registration import (
    ALLOWED_COUNTRIES,
    Gender,
    validate_dob_value,
    validate_safe_text,
)


class AdminRegistrationRequest(BaseModel):
    full_name: str
    email: EmailStr
    dob: date
    gender: Gender
    country: str

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        v = v.strip()
        if len(v) < 1 or len(v) > 200:
            raise ValueError("Full name must be 1-200 characters")
        return validate_safe_text(v, "Full name")

    @field_validator("dob")
    @classmethod
    def validate_dob(cls, v):
        return validate_dob_value(v)

    @field_validator("country")
    @classmethod
    def validate_country(cls, v):
        v = v.strip().upper()
        if v not in ALLOWED_COUNTRIES:
            raise ValueError(f"Country must be one of: {', '.join(sorted(ALLOWED_COUNTRIES))}")
        return v


class AdminRegistrationResponse(BaseModel):
    reference: str
    ticket_number: str
