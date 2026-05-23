from typing import Literal, Optional
from pydantic import BaseModel
from app.models.registration import RegistrationInput


class CreatePaymentRequest(RegistrationInput):
    payment_method: Literal["stripe", "paypal"] = "stripe"


class CreatePaymentResponse(BaseModel):
    payment_url: str
    reference: str


class PaymentStatusResponse(BaseModel):
    status: str
    reference: Optional[str] = None
    failure_reason: Optional[str] = None
