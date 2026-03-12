import logging
from datetime import datetime, timezone

import stripe

from app.core.config import settings
from app.core.supabase import supabase
from app.models.registration import RegistrationInput, MemberInput
from app.services.registration_service import check_country_quota, create_registration, process_qr_and_emails

logger = logging.getLogger(__name__)


# ── Stripe session creation ───────────────────────────────────

def create_stripe_session(data: RegistrationInput, amount: float) -> str:
    """Create a Stripe Checkout Session with all registration data stored in metadata.

    NO database insert happens here — data lives only in Stripe until payment succeeds.
    Stripe metadata limits: 50 keys, 500 chars per value, 8KB total.
    With 4 members × 7 fields + 4 base fields = 32 keys max — well within limits.
    """
    if not settings.stripe_secret_key:
        raise ValueError("Stripe is not configured. Please contact support.")

    stripe.api_key = settings.stripe_secret_key
    metadata = _build_metadata(data, amount)

    member_label = f"{len(data.members)} member{'s' if len(data.members) > 1 else ''}"
    session = stripe.checkout.Session.create(
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"HP 2026 Registration ({member_label})"},
                "unit_amount": int(amount * 100),  # Stripe expects cents
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{settings.frontend_url}/payment/success",
        cancel_url=f"{settings.frontend_url}/payment/cancel",
        metadata=metadata,
    )
    logger.info(f"Stripe session created for {data.country}, {member_label}, €{amount:.2f}")
    return session.url


def verify_stripe_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the parsed event."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )


# ── Payment completion (called by webhook after payment) ──────

def complete_payment(session: dict):
    """Called by webhook AFTER successful payment. This is where all DB writes happen.

    Flow:
      1. Reconstruct registration data from Stripe metadata
      2. Re-check country quota (definitive check — prevents over-subscription)
      3. Insert registration + members into DB
      4. Insert payment record as 'paid'
      5. Generate QR codes + send emails

    If any step fails, the error is logged with full context for manual recovery.
    Webhook still returns 200 to prevent Stripe from retrying endlessly.
    """
    metadata = session.get("metadata", {})
    transaction_id = session.get("payment_intent") or session["id"]
    session_id = session.get("id", "unknown")
    amount = float(metadata.get("amount", 0))

    # ── Step 1: Reconstruct registration data from metadata ──
    try:
        data = _reconstruct_registration(metadata)
    except Exception:
        logger.exception(f"Failed to reconstruct registration from Stripe metadata, session={session_id}, metadata={metadata}")
        return

    # ── Step 2: Re-check country quota (prevents race condition) ──
    try:
        check_country_quota(data.country, len(data.members))
    except ValueError:
        logger.warning(
            f"Quota exceeded at payment time for country={data.country}, "
            f"session={session_id}, txn={transaction_id} — manual refund needed"
        )
        return

    # ── Step 3: Insert registration + members ──
    try:
        result = create_registration(data)
    except Exception:
        logger.exception(
            f"DB insert failed after payment, session={session_id}, txn={transaction_id}, "
            f"country={data.country}, members={len(data.members)} — manual recovery needed"
        )
        return

    registration_id = result["registration_id"]
    reference = result["reference"]

    # ── Step 4: Insert payment record as 'paid' ──
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
        logger.exception(f"Payment record insert failed for {reference}, txn={transaction_id}")
        return

    logger.info(f"Payment completed: {reference}, txn={transaction_id}, €{amount:.2f}")

    # ── Step 5: Generate QR codes + send emails ──
    primary_email = data.members[0].email
    members_data = result["members_data"]

    try:
        process_qr_and_emails(registration_id, members_data, primary_email, reference)
        supabase.table("payments").update({
            "emails_sent": True,
        }).eq("registration_id", registration_id).execute()
        logger.info(f"Emails sent for {reference}")
    except Exception:
        logger.exception(f"Email sending failed for {reference} — payment is paid, emails need manual retry")
        supabase.table("payments").update({
            "emails_sent": False,
        }).eq("registration_id", registration_id).execute()


# ── Metadata encoding/decoding ────────────────────────────────

def _build_metadata(data: RegistrationInput, amount: float) -> dict:
    """Encode registration data into Stripe metadata dict.

    Structure:
      country, karyakarta, member_count, amount  (base fields)
      m{i}_first, m{i}_middle, m{i}_last, m{i}_gender, m{i}_dob, m{i}_email, m{i}_phone  (per member)
    """
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
    """Decode registration data from Stripe metadata back into a RegistrationInput."""
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
