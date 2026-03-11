from enum import Enum
from pydantic import BaseModel
from app.models.registration import RegistrationInput


class PaymentMethod(str, Enum):
    stripe = "stripe"
    paypal = "paypal"


class CreatePaymentRequest(RegistrationInput):
    """Registration data + payment method. Inherits all registration validation."""
    payment_method: PaymentMethod


class CreatePaymentResponse(BaseModel):
    reference: str
    payment_url: str
