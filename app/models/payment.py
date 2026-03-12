from enum import Enum
from pydantic import BaseModel
from app.models.registration import RegistrationInput


class PaymentMethod(str, Enum):
    stripe = "stripe"


class CreatePaymentRequest(RegistrationInput):
    payment_method: PaymentMethod


class CreatePaymentResponse(BaseModel):
    payment_url: str
