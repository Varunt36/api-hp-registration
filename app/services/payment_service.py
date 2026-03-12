import logging
from datetime import datetime, timezone

import stripe

from app.core.config import settings
from app.core.exceptions import PaymentError
from app.core.supabase import supabase
from app.models.registration import RegistrationInput, MemberInput
from app.services.registration_service import check_country_quota, create_registration, process_qr_and_emails

logger = logging.getLogger(__name__)


def create_stripe_session(data: RegistrationInput, amount: float) -> str:
    """Create Stripe Checkout Session. Registration data is stored in Stripe metadata."""
    stripe.api_key = settings.stripe_secret_key
    metadata = _build_metadata(data, amount)
    member_label = f"{len(data.members)} member{'s' if len(data.members) > 1 else ''}"

    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"HP 2026 Registration ({member_label})"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{settings.frontend_url}/payment/success",
            cancel_url=f"{settings.frontend_url}/payment/cancel",
            metadata=metadata,
        )
    except stripe.StripeError as e:
        logger.exception(f"Stripe session creation failed: {e}")
        raise PaymentError("Payment session could not be created. Please try again.")

    logger.info(f"Stripe session created: {data.country}, {member_label}, EUR {amount:.2f}")
    return session.url


def verify_stripe_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the parsed event."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def complete_payment(session: dict):
    """Process successful payment: insert registration, payment record, and send emails.

    Called as a background task from the webhook handler.
    Each step has individual error handling with logging for manual recovery.
    """
    metadata = session.get("metadata", {})
    transaction_id = session.get("payment_intent") or session["id"]
    session_id = session.get("id", "unknown")
    amount = float(metadata.get("amount", 0))
    log_ctx = f"session={session_id}, txn={transaction_id}"

    # Idempotency: skip if already processed
    existing = supabase.table("payments").select("id").eq("transaction_id", transaction_id).execute()
    if existing.data:
        logger.info(f"[SKIP] Already processed: {log_ctx}")
        return

    # Reconstruct registration from metadata
    try:
        data = _reconstruct_registration(metadata)
    except Exception:
        logger.exception(f"[FAIL] Metadata reconstruction: {log_ctx}")
        return

    log_ctx = f"{log_ctx}, country={data.country}, members={len(data.members)}"

    # Re-check quota (prevents race condition)
    try:
        check_country_quota(data.country, len(data.members))
    except Exception:
        logger.warning(f"[FAIL] Quota exceeded at payment time: {log_ctx} — MANUAL REFUND NEEDED")
        return

    # Insert registration + members
    try:
        result = create_registration(data)
    except Exception:
        logger.exception(f"[FAIL] DB insert: {log_ctx} — MANUAL RECOVERY NEEDED")
        return

    registration_id = result["registration_id"]
    reference = result["reference"]
    log_ctx = f"{log_ctx}, ref={reference}"

    # Insert payment record
    try:
        supabase.table("payments").insert({
            "registration_id": registration_id,
            "status": "paid",
            "amount": amount,
            "currency": "EUR",
            "payment_method": "stripe",
            "transaction_id": transaction_id,
            "paid_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        logger.exception(f"[FAIL] Payment record insert: {log_ctx}")
        return

    logger.info(f"[OK] Payment completed: {log_ctx}, EUR {amount:.2f}")

    # Generate QR codes + send emails
    primary_email = data.members[0].email
    try:
        process_qr_and_emails(registration_id, result["members_data"], primary_email, reference)
        supabase.table("payments").update({"emails_sent": True}).eq("registration_id", registration_id).execute()
        logger.info(f"[OK] Emails sent: {log_ctx}")
    except Exception:
        logger.exception(f"[FAIL] Emails: {log_ctx} — payment saved, emails need manual retry")
        try:
            supabase.table("payments").update({"emails_sent": False}).eq("registration_id", registration_id).execute()
        except Exception:
            logger.exception(f"[FAIL] Could not update emails_sent flag: {log_ctx}")


def _build_metadata(data: RegistrationInput, amount: float) -> dict:
    """Encode registration data into Stripe metadata dict."""
    metadata = {
        "country": data.country,
        "karyakarta": data.karyakarta,
        "member_count": str(len(data.members)),
        "amount": str(amount),
    }
    for i, member in enumerate(data.members, 1):
        metadata[f"m{i}_first"] = member.first_name
        metadata[f"m{i}_middle"] = member.middle_name or ""
        metadata[f"m{i}_last"] = member.last_name
        metadata[f"m{i}_gender"] = member.gender.value
        metadata[f"m{i}_dob"] = str(member.dob)
        metadata[f"m{i}_email"] = member.email or ""
        metadata[f"m{i}_phone"] = member.phone or ""
    return metadata


def _reconstruct_registration(metadata: dict) -> RegistrationInput:
    """Decode Stripe metadata back into a RegistrationInput."""
    member_count = int(metadata["member_count"])
    members = []
    for i in range(1, member_count + 1):
        members.append(MemberInput(
            first_name=metadata[f"m{i}_first"],
            middle_name=metadata.get(f"m{i}_middle") or None,
            last_name=metadata[f"m{i}_last"],
            gender=metadata[f"m{i}_gender"],
            dob=metadata[f"m{i}_dob"],
            email=metadata.get(f"m{i}_email") or None,
            phone=metadata.get(f"m{i}_phone") or None,
        ))
    return RegistrationInput(
        country=metadata["country"],
        karyakarta=metadata["karyakarta"],
        terms_accepted=True,
        members=members,
    )
