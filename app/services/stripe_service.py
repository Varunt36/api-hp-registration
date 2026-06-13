"""Stripe Checkout adapter. Intent UUID is carried via `client_reference_id`."""
from __future__ import annotations

import logging

import stripe

from app.core.config import settings
from app.core.exceptions import PaymentError

logger = logging.getLogger(__name__)
stripe.api_key = settings.stripe_secret_key


def create_stripe_session(intent_id: str, amount: float, member_count: int) -> str:
    label = f"{member_count} member{'s' if member_count > 1 else ''}"
    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"HP Amrut Mahotsav Registration ({label})"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            allow_promotion_codes=True,
            success_url=f"{settings.frontend_url}/payment/success?intent_id={intent_id}",
            cancel_url=f"{settings.frontend_url}/payment/cancel",
            client_reference_id=intent_id,
        )
    except stripe.StripeError:
        logger.exception("Stripe session creation failed")
        raise PaymentError("Payment session could not be created. Please try again.")

    logger.info(f"Stripe session created: intent={intent_id} members={member_count} EUR{amount:.2f}")
    return session.url


def verify_stripe_event(payload: bytes, sig_header: str) -> dict:
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
