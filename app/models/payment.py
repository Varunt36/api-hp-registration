from enum import Enum
from typing import Optional
from pydantic import BaseModel
from app.models.registration import RegistrationInput


class PaymentMethod(str, Enum):
    stripe = "stripe"
    paypal = "paypal"


class CreatePaymentRequest(RegistrationInput):
    payment_method: PaymentMethod


class CreatePaymentResponse(BaseModel):
    payment_url: str
    reference: str


class PaymentStatusResponse(BaseModel):
    status: str
    reference: Optional[str] = None
