import logging
from datetime import datetime, timezone

import stripe

from app.core.config import settings
from app.core.exceptions import PaymentError
from app.core.supabase import supabase
from app.models.registration import RegistrationInput, MemberInput
from app.services.registration_service import check_country_quota, insert_registration_members, process_qr_and_emails

logger = logging.getLogger(__name__)


def create_stripe_session(data: RegistrationInput, amount: float, reference: str) -> str:
    """Create Stripe Checkout Session. Registration data is stored in Stripe metadata."""
    stripe.api_key = settings.stripe_secret_key
    metadata = _build_metadata(data, amount)
    metadata["reference"] = reference
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
            success_url=f"{settings.frontend_url}/payment/success?ref={reference}",
            cancel_url=f"{settings.frontend_url}/payment/cancel",
            metadata=metadata,
        )
    except stripe.StripeError as e:
        logger.exception(f"Stripe session creation failed: {e}")
        raise PaymentError("Payment session could not be created. Please try again.")

    logger.info(f"Stripe session created: {reference}, {data.country}, {member_label}, EUR {amount:.2f}")
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

    reference = metadata.get("reference")
    log_ctx = f"{log_ctx}, country={data.country}, members={len(data.members)}, ref={reference}"

    # Re-check quota (prevents race condition)
    try:
        check_country_quota(data.country, len(data.members))
    except Exception:
        logger.warning(f"[FAIL] Quota exceeded at payment time: {log_ctx} — MANUAL REFUND NEEDED")
        return

    # Look up the pre-allocated registration by reference
    reg_lookup = supabase.table("registrations").select("id").eq("reference", reference).execute()
    if not reg_lookup.data:
        logger.error(f"[FAIL] Pre-allocated registration not found: {log_ctx} — MANUAL RECOVERY NEEDED")
        return
    registration_id = reg_lookup.data[0]["id"]

    # Insert members for the pre-allocated registration
    try:
        result = insert_registration_members(registration_id, reference, data)
    except Exception:
        logger.exception(f"[FAIL] Member insert: {log_ctx} — MANUAL RECOVERY NEEDED")
        return

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
