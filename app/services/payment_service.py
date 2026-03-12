import json
import logging
from datetime import datetime, timezone

import httpx
import stripe

from app.core.config import settings
from app.core.supabase import supabase
from app.services.registration_service import process_qr_and_emails

logger = logging.getLogger(__name__)


# ── Pending payment record ────────────────────────────────────

def create_pending_payment(registration_id: str, amount: float, payment_method: str):
    """Insert a pending payment row in the DB."""
    supabase.table("payments").insert({
        "registration_id": registration_id,
        "status": "pending",
        "amount": amount,
        "currency": "EUR",
        "payment_method": payment_method,
    }).execute()


# ── Stripe ────────────────────────────────────────────────────

def create_stripe_session(registration_id: str, reference: str, amount: float) -> str:
    """Create a Stripe Checkout Session and return the checkout URL."""
    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"HP 2026 Registration – {reference}"},
                "unit_amount": int(amount * 100),  # Stripe expects cents
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{settings.frontend_url}/payment/success?ref={reference}",
        cancel_url=f"{settings.frontend_url}/payment/cancel?ref={reference}",
        metadata={"registration_id": registration_id, "reference": reference},
    )
    return session.url


def verify_stripe_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the parsed event."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )


# ── PayPal ────────────────────────────────────────────────────

def create_paypal_order(registration_id: str, reference: str, amount: float) -> str:
    """Create a PayPal order and return the approval URL for redirect."""
    access_token = _get_paypal_access_token()
    base_url = _paypal_base_url()

    response = httpx.post(
        f"{base_url}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": registration_id,
                "custom_id": reference,
                "amount": {
                    "currency_code": "EUR",
                    "value": f"{amount:.2f}",
                },
                "description": f"HP 2026 Registration – {reference}",
            }],
            "application_context": {
                "return_url": f"{settings.frontend_url}/payment/success?ref={reference}",
                "cancel_url": f"{settings.frontend_url}/payment/cancel?ref={reference}",
            },
        },
    )
    response.raise_for_status()
    order = response.json()

    for link in order["links"]:
        if link["rel"] == "approve":
            return link["href"]
    raise ValueError("PayPal did not return an approval URL")


def verify_paypal_webhook(headers: dict, body: bytes) -> bool:
    """Verify PayPal webhook signature via their verification API."""
    access_token = _get_paypal_access_token()
    base_url = _paypal_base_url()

    response = httpx.post(
        f"{base_url}/v1/notifications/verify-webhook-signature",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": settings.paypal_webhook_id,
            "webhook_event": json.loads(body),
        },
    )
    return response.json().get("verification_status") == "SUCCESS"


def capture_paypal_order(order_id: str) -> dict:
    """Capture an approved PayPal order and return the capture response."""
    access_token = _get_paypal_access_token()
    base_url = _paypal_base_url()

    response = httpx.post(
        f"{base_url}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    return response.json()


# ── Payment completion (called by both webhooks) ──────────────

def complete_payment(registration_id: str, transaction_id: str):
    """Mark payment as paid and trigger QR code generation + email sending.

    Idempotent — safe to call multiple times (webhooks can retry).
    """
    # Check if already paid (idempotency guard)
    existing = (
        supabase.table("payments")
        .select("status")
        .eq("registration_id", registration_id)
        .execute()
    )
    if existing.data and existing.data[0]["status"] == "paid":
        logger.info(f"Payment already completed for {registration_id}, skipping")
        return

    # Update payment to paid
    supabase.table("payments").update({
        "status": "paid",
        "transaction_id": transaction_id,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }).eq("registration_id", registration_id).execute()

    # Fetch registration + members for QR/email processing
    reg = (
        supabase.table("registrations")
        .select("reference")
        .eq("id", registration_id)
        .execute()
    )
    members = (
        supabase.table("members")
        .select("*")
        .eq("registration_id", registration_id)
        .order("ticket_number")
        .execute()
    )

    if not reg.data or not members.data:
        logger.error(f"Registration or members not found for {registration_id}")
        return

    reference = reg.data[0]["reference"]
    primary_email = members.data[0]["email"]

    # Build members_data in the format process_qr_and_emails expects
    members_data = []
    for m in members.data:
        members_data.append({
            "ticket_number": m["ticket_number"],
            "first_name": m["first_name"],
            "last_name": m["last_name"],
            "email": m.get("email"),
        })

    logger.info(f"Payment completed for {reference}, triggering QR + emails")
    process_qr_and_emails(registration_id, members_data, primary_email, reference)


# ── Internal helpers ──────────────────────────────────────────

def _paypal_base_url() -> str:
    if settings.paypal_mode == "sandbox":
        return "https://api-m.sandbox.paypal.com"
    return "https://api-m.paypal.com"


def _get_paypal_access_token() -> str:
    """Get a PayPal OAuth2 access token using client credentials."""
    base_url = _paypal_base_url()
    response = httpx.post(
        f"{base_url}/v1/oauth2/token",
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()["access_token"]
