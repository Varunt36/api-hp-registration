class AppError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class QuotaExceededError(AppError):
    code = "QUOTA_EXCEEDED"
    status_code = 409

    def __init__(self, country: str):
        super().__init__(
            f"Jay Swaminarayan, We're sorry, all spots for {country} have been filled. "
            "Registration is now closed. Please contact your regional leader for further information."
        )


class PaymentError(AppError):
    code = "PAYMENT_ERROR"
    status_code = 502
    default_message = "Payment processing failed. Please try again."


class PaymentConfigError(AppError):
    code = "PAYMENT_NOT_CONFIGURED"
    status_code = 503
    default_message = "Payment is not configured. Please contact support."


class WebhookVerificationError(AppError):
    code = "WEBHOOK_INVALID"
    status_code = 400
    default_message = "Invalid webhook signature."


class RegistrationInsertError(AppError):
    code = "REGISTRATION_FAILED"
    status_code = 500

    def __init__(self, reference: str = ""):
        detail = f" ({reference})" if reference else ""
        super().__init__(f"Registration failed{detail}. Please try again.")


class PaymentProviderUnreachable(PaymentError):
    """Transient: provider unreachable. User retries."""
    code = "PAYMENT_PROVIDER_UNREACHABLE"

    def __init__(self, provider: str = "stripe", detail: str = ""):
        self.detail = detail
        super().__init__("Stripe is temporarily unavailable. Please try again in a moment.")


class PaymentProviderRejected(PaymentError):
    """Permanent for this request: provider 4xx (config bug, not a decline)."""
    code = "PAYMENT_PROVIDER_REJECTED"

    def __init__(self, provider: str, detail: str = ""):
        self.detail = detail
        super().__init__("Payment could not be initiated. Please contact support.")


class AuthError(AppError):
    code = "UNAUTHORIZED"
    status_code = 401
    default_message = "Authentication required."


class RegistrationNotFoundError(AppError):
    code = "REGISTRATION_NOT_FOUND"
    status_code = 404
    default_message = "No registration found for this email."


class MultipleRegistrationsError(AppError):
    """Email maps to more than one registration; caller must disambiguate with a reference."""
    code = "MULTIPLE_REGISTRATIONS"
    status_code = 409
    default_message = "This email matches multiple registrations. Please choose one."

    def __init__(self, candidates: list[dict], message: str | None = None):
        self.candidates = candidates
        super().__init__(message)
