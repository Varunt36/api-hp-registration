"""Provider-agnostic payment finisher.

Called by both /webhooks/stripe and /webhooks/paypal as a BackgroundTask after
signature verification. Looks up the intent, reconstructs the RegistrationInput,
inserts members + payment row, sends emails. Idempotent on transaction_id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.supabase import supabase
from app.models.registration import RegistrationInput
from app.services import payment_intent_service
from app.services.registration_service import (
    check_country_quota,
    insert_registration_members,
    process_qr_and_emails,
)

logger = logging.getLogger(__name__)


def complete_payment(
    intent_id: str,
    transaction_id: str,
    provider: str,
    provider_order_id: str | None = None,
) -> None:
    """Finish the registration once the provider has confirmed payment."""
    log_ctx = f"provider={provider} txn={transaction_id} intent={intent_id}"

    # Idempotency #1: skip if we've already recorded this transaction.
    existing = supabase.table("payments").select("id").eq("transaction_id", transaction_id).execute()
    if existing.data:
        logger.info(f"[SKIP] Already processed: {log_ctx}")
        return

    # Idempotency #2: atomically claim the intent (pending -> consumed).
    intent = payment_intent_service.get_pending(intent_id)
    if not intent:
        logger.warning(f"[FAIL] Intent not found or already consumed: {log_ctx} - MANUAL RECOVERY")
        return
    if not payment_intent_service.mark_consumed(intent_id):
        logger.info(f"[SKIP] Intent consumed concurrently: {log_ctx}")
        return

    reference = intent["reference"]
    amount = float(intent["amount"])
    try:
        data = RegistrationInput(**intent["payload"])
    except Exception:
        logger.exception(f"[FAIL] Payload deserialization: {log_ctx} ref={reference} - MANUAL RECOVERY")
        return

    log_ctx = f"{log_ctx} ref={reference} country={data.country} members={len(data.members)}"

    # Race-condition guard: re-check the country quota at payment time.
    try:
        check_country_quota(data.country, len(data.members))
    except Exception:
        logger.warning(f"[FAIL] Quota exceeded at payment time: {log_ctx} - MANUAL REFUND NEEDED")
        return

    reg_lookup = supabase.table("registrations").select("id").eq("reference", reference).execute()
    if not reg_lookup.data:
        logger.error(f"[FAIL] Pre-allocated registration not found: {log_ctx} - MANUAL RECOVERY")
        return
    registration_id = reg_lookup.data[0]["id"]

    try:
        result = insert_registration_members(registration_id, reference, data)
    except Exception:
        logger.exception(f"[FAIL] Member insert: {log_ctx} - MANUAL RECOVERY")
        return

    try:
        supabase.table("payments").insert({
            "registration_id": registration_id,
            "status": "paid",
            "amount": amount,
            "currency": intent.get("currency", "EUR"),
            "payment_method": provider,
            "transaction_id": transaction_id,
            "provider_order_id": provider_order_id,
            "paid_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        logger.exception(f"[FAIL] Payment record insert: {log_ctx}")
        return

    logger.info(f"[OK] Payment completed: {log_ctx} EUR{amount:.2f}")

    primary_email = data.members[0].email
    try:
        process_qr_and_emails(registration_id, result["members_data"], primary_email, reference)
        supabase.table("payments").update({"emails_sent": True}).eq("registration_id", registration_id).execute()
        logger.info(f"[OK] Emails sent: {log_ctx}")
    except Exception:
        logger.exception(f"[FAIL] Emails: {log_ctx} - payment saved, emails need manual retry")
        try:
            supabase.table("payments").update({"emails_sent": False}).eq("registration_id", registration_id).execute()
        except Exception:
            logger.exception(f"[FAIL] Could not update emails_sent flag: {log_ctx}")
