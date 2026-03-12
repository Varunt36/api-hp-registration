class AppError(Exception):
    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class QuotaExceededError(AppError):
    def __init__(self, country: str):
        super().__init__(
            f"Jay Swaminarayan, We're sorry, all spots for {country} have been filled. "
            "Registration is now closed. Please contact your regional leader for further information.",
            code="QUOTA_EXCEEDED",
            status_code=409,
        )



class PaymentError(AppError):
    def __init__(self, message: str = "Payment processing failed. Please try again."):
        super().__init__(message, code="PAYMENT_ERROR", status_code=502)


class PaymentConfigError(AppError):
    def __init__(self):
        super().__init__(
            "Payment is not configured. Please contact support.",
            code="PAYMENT_NOT_CONFIGURED",
            status_code=503,
        )


class WebhookVerificationError(AppError):
    def __init__(self):
        super().__init__("Invalid webhook signature.", code="WEBHOOK_INVALID", status_code=400)


class RegistrationInsertError(AppError):
    def __init__(self, reference: str = ""):
        detail = f" ({reference})" if reference else ""
        super().__init__(
            f"Registration failed{detail}. Please try again.",
            code="REGISTRATION_FAILED",
            status_code=500,
        )
