"""Stripe Checkout adapter — hosted-redirect flow.

After this refactor the registration payload is carried via `client_reference_id`
(the payment_intent UUID), not flattened into `metadata`.
"""
from __future__ import annotations

import logging

import stripe

from app.core.config import settings
from app.core.exceptions import PaymentError
from app.core.supabase import supabase

logger = logging.getLogger(__name__)


def create_stripe_session(intent_id: str, amount: float, reference: str, member_count: int) -> str:
    """Create a Stripe Checkout Session. Returns the hosted URL."""
    stripe.api_key = settings.stripe_secret_key
    member_label = f"{member_count} member{'s' if member_count > 1 else ''}"
    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"HP Amrut Mahotsav Registration ({member_label})"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{settings.frontend_url}/payment/success?ref={reference}",
            cancel_url=f"{settings.frontend_url}/payment/cancel",
            client_reference_id=intent_id,
            metadata={"reference": reference, "intent_id": intent_id},
        )
    except stripe.StripeError as e:
        logger.exception(f"Stripe session creation failed: {e}")
        raise PaymentError("Payment session could not be created. Please try again.")

    logger.info(f"Stripe session created: ref={reference} members={member_count} EUR{amount:.2f}")
    return session.url


def verify_stripe_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the parsed event."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def extract_intent_id(session: dict) -> str | None:
    """Pull the payment_intent UUID we stored at session creation."""
    return session.get("client_reference_id") or session.get("metadata", {}).get("intent_id")


def extract_transaction_id(session: dict) -> str:
    """Stripe PaymentIntent id is the durable transaction id for the row."""
    return session.get("payment_intent") or session["id"]


def get_payment_status(session_id: str) -> dict:
    """Look up payment reference by Stripe session ID."""
    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:
        logger.warning(f"Stripe session not found: {session_id}")
        return {"status": "not_found"}
    if session.payment_status != "paid":
        return {"status": "pending"}

    transaction_id = session.payment_intent or session.id
    payment = (
        supabase.table("payments")
        .select("registration_id, registrations(reference)")
        .eq("transaction_id", transaction_id)
        .execute()
    )
    if not payment.data:
        return {"status": "processing"}
    reference = payment.data[0].get("registrations", {}).get("reference")
    return {"status": "paid", "reference": reference}
