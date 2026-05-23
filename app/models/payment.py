from typing import Optional
from pydantic import BaseModel
from app.models.registration import RegistrationInput


class CreatePaymentRequest(RegistrationInput):
    amount: float


class CreatePaymentResponse(BaseModel):
    payment_url: str
    intent_id: str


class PaymentStatusResponse(BaseModel):
    status: str
    reference: Optional[str] = None
    failure_reason: Optional[str] = None
