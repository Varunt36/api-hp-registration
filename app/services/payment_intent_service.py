"""Server-side store for registration payloads between /create-payment and webhook completion.

The intent UUID is what we hand to the provider (PayPal custom_id, Stripe client_reference_id),
so neither provider ever sees the registration data itself.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

from app.core.supabase import supabase
from app.models.registration import RegistrationInput

logger = logging.getLogger(__name__)

Provider = Literal["stripe", "paypal"]
_ALLOWED_PROVIDERS: tuple[str, ...] = ("stripe", "paypal")
_INTENT_TTL = timedelta(hours=1)


def create(
    *,
    reference: str,
    provider: Provider,
    payload: RegistrationInput,
    amount: float,
    currency: str = "EUR",
) -> str:
    """Insert a payment intent. Returns the new intent UUID."""
    if provider not in _ALLOWED_PROVIDERS:
        raise ValueError(f"Unknown payment provider: {provider!r}")

    expires_at = (datetime.now(timezone.utc) + _INTENT_TTL).isoformat()
    row = {
        "reference": reference,
        "provider": provider,
        "payload": payload.model_dump(mode="json"),
        "amount": amount,
        "currency": currency,
        "status": "pending",
        "expires_at": expires_at,
    }

    result = supabase.table("payment_intents").insert(row).execute()
    if not result.data:
        raise RuntimeError(f"Failed to create payment_intent for {reference}")
    intent_id = result.data[0]["id"]
    logger.info(f"payment_intent created: id={intent_id} ref={reference} provider={provider}")
    return intent_id


def get_pending(intent_id: str) -> Optional[dict]:
    """Return the intent row if it exists and is still pending. None otherwise."""
    result = (
        supabase.table("payment_intents")
        .select("id, reference, provider, payload, amount, currency, status")
        .eq("id", intent_id)
        .eq("status", "pending")
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def mark_consumed(intent_id: str) -> bool:
    """Transition pending -> consumed atomically. Returns True iff this call won the race."""
    result = (
        supabase.table("payment_intents")
        .update({"status": "consumed"})
        .eq("id", intent_id)
        .eq("status", "pending")
        .execute()
    )
    won = bool(result.data)
    if won:
        logger.info(f"payment_intent consumed: id={intent_id}")
    else:
        logger.info(f"payment_intent already consumed or missing: id={intent_id}")
    return won
