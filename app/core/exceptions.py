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


class AdminUnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required."):
        super().__init__(message, code="ADMIN_UNAUTHORIZED", status_code=401)


class AdminForbiddenError(AppError):
    def __init__(self):
        super().__init__("Admin access required.", code="ADMIN_FORBIDDEN", status_code=403)


_PROVIDER_DISPLAY_NAMES = {
    "paypal": "PayPal",
    "stripe": "Stripe",
}


class PaymentProviderUnreachable(PaymentError):
    """Transient: the payment provider could not be reached (network, DNS, timeout, 5xx).

    Surfaced to the user as "try again". Log the `detail` for ops.
    """
    def __init__(self, provider: str, detail: str = ""):
        self.detail = detail
        display = _PROVIDER_DISPLAY_NAMES.get(provider.lower(), provider.capitalize())
        super().__init__(
            f"{display} is temporarily unavailable. Please try again in a moment.",
        )
        self.code = "PAYMENT_PROVIDER_UNREACHABLE"
        self.status_code = 502


class PaymentProviderRejected(PaymentError):
    """Permanent for this request: the provider returned a 4xx that is not a user decline.

    Examples: malformed amount, invalid currency, missing field, bad credentials.
    Almost always indicates a config bug on our side — page an engineer.
    """
    def __init__(self, provider: str, detail: str = ""):
        self.detail = detail
        super().__init__("Payment could not be initiated. Please contact support.")
        self.code = "PAYMENT_PROVIDER_REJECTED"
        self.status_code = 502


class PaymentDeclinedError(PaymentError):
    """The buyer's instrument was declined (card, bank, balance, fraud rule).

    402 Payment Required is the semantically correct status. Surfaced to the user
    as "your payment method was declined — please try a different one".
    """
    def __init__(self, provider: str):
        super().__init__(
            "Your payment was declined. Please try a different payment method.",
        )
        self.code = "PAYMENT_DECLINED"
        self.status_code = 402
