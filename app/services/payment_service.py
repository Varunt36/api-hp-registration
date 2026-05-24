"""Payment intent store + post-payment orchestration.

The intent UUID is the only thing handed to the provider, so PII stays off the
provider. The reference number is allocated inside complete_payment, after the
webhook has confirmed payment.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

from app.core.exceptions import QuotaExceededError, RegistrationInsertError
from app.core.supabase import supabase
from app.models.registration import RegistrationInput
from app.services.registration_service import (
    allocate_reference,
    check_country_quota,
    delete_registration,
    insert_registration_members,
    process_qr_and_emails,
)

logger = logging.getLogger(__name__)

Provider = Literal["stripe", "paypal"]
_INTENT_TTL = timedelta(hours=1)

def create_intent(*, provider: Provider, payload: RegistrationInput, amount: float, currency: str = "EUR") -> str:
    expires_at = (datetime.now(timezone.utc) + _INTENT_TTL).isoformat()
    result = supabase.table("payment_intents").insert({
        "provider": provider,
        "payload": payload.model_dump(mode="json"),
        "amount": amount,
        "currency": currency,
        "status": "pending",
        "expires_at": expires_at,
    }).execute()
    if not result.data:
        raise RuntimeError("Failed to create payment_intent")
    intent_id = result.data[0]["id"]
    logger.info(f"intent created: id={intent_id} provider={provider}")
    return intent_id


def get_pending_intent(intent_id: str) -> Optional[dict]:
    result = (
        supabase.table("payment_intents")
        .select("id, provider, payload, amount, currency, status")
        .eq("id", intent_id).eq("status", "pending").execute()
    )
    return result.data[0] if result.data else None


def mark_intent_consumed(intent_id: str, reference: str) -> bool:
    """Atomic pending -> consumed. Returns True iff this call won the race."""
    result = (
        supabase.table("payment_intents")
        .update({"status": "consumed", "reference": reference})
        .eq("id", intent_id).eq("status", "pending").execute()
    )
    won = bool(result.data)
    logger.info(f"intent {'consumed' if won else 'race lost'}: id={intent_id}")
    return won


def revert_intent_to_pending(intent_id: str) -> None:
    """Best-effort undo of a consumed claim so a webhook retry can re-process."""
    try:
        supabase.table("payment_intents").update(
            {"status": "pending", "reference": None}
        ).eq("id", intent_id).execute()
    except Exception:
        logger.exception(f"Failed to revert intent {intent_id}")


def lookup_intent_status(intent_id: str) -> Optional[dict]:
    """Return {status, reference, failure_reason}. Pending intents past expiry are reported as 'expired'."""
    result = (
        supabase.table("payment_intents")
        .select("status, reference, expires_at, failure_reason").eq("id", intent_id).execute()
    )
    if not result.data:
        return None
    row = result.data[0]
    if row["status"] == "pending":
        expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            return {"status": "expired", "reference": None, "failure_reason": "Payment session expired before completion."}
    return {
        "status": row["status"],
        "reference": row.get("reference"),
        "failure_reason": row.get("failure_reason"),
    }


def mark_intent_failed(intent_id: str, reason: str) -> None:
    """Record why a payment_intent ended in failure so the FE can show the user."""
    try:
        supabase.table("payment_intents").update(
            {"status": "failed", "failure_reason": reason}
        ).eq("id", intent_id).execute()
    except Exception:
        logger.exception(f"Failed to mark intent {intent_id} as failed")


# --- Orchestration --------------------------------------------------------

def complete_payment(intent_id: str, transaction_id: str, provider: str, provider_order_id: str | None = None) -> None:
    """Finalize a registration after a successful payment webhook. Idempotent."""
    ctx = f"provider={provider} txn={transaction_id} intent={intent_id}"

    if supabase.table("payments").select("id").eq("transaction_id", transaction_id).execute().data:
        logger.info(f"[SKIP] already processed: {ctx}")
        return

    intent = get_pending_intent(intent_id)
    if not intent:
        logger.warning(f"[FAIL] intent not pending: {ctx}")
        return

    data = RegistrationInput(**intent["payload"])
    ctx = f"{ctx} country={data.country} members={len(data.members)}"

    try:
        check_country_quota(data.country, len(data.members))
    except QuotaExceededError as e:
        logger.warning(f"[FAIL] quota exceeded at capture time: {ctx} - MANUAL REFUND")
        mark_intent_failed(intent_id, e.message)
        return

    allocation = allocate_reference(data)
    registration_id, reference = allocation["registration_id"], allocation["reference"]
    ctx = f"{ctx} ref={reference}"

    if not mark_intent_consumed(intent_id, reference):
        logger.info(f"[SKIP] intent consumed concurrently, rolling back: {ctx}")
        delete_registration(registration_id)
        return

    try:
        result = insert_registration_members(registration_id, reference, data)
    except RegistrationInsertError:
        logger.exception(f"[FAIL] member insert, reverting intent: {ctx}")
        revert_intent_to_pending(intent_id)
        mark_intent_failed(intent_id, "We could not save your registration after payment. Our team has been notified — please contact support with your payment reference.")
        return

    amount = float(intent["amount"])
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
        logger.exception(f"[FAIL] payment row insert, rolling back: {ctx}")
        delete_registration(registration_id)
        mark_intent_failed(intent_id, "Your payment succeeded but we could not save the confirmation. Our team has been notified — please contact support.")
        return

    logger.info(f"[OK] payment completed: {ctx} EUR{amount:.2f}")

    try:
        sent = process_qr_and_emails(registration_id, result["members_data"], data.members[0].email, reference)
        if sent > 0:
            supabase.table("payments").update({"emails_sent": True}).eq("registration_id", registration_id).execute()
    except Exception:
        logger.exception(f"[FAIL] emails: {ctx} - payment saved, retry manually")
