import logging
from datetime import date

import stripe
from fastapi import APIRouter, BackgroundTasks, Request

from app.core.config import settings
from app.core.exceptions import PaymentConfigError, WebhookVerificationError
from app.models.payment import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentStatusResponse,
)
from app.models.registration import MemberInput
from app.services import payment_service
from app.services.registration_service import check_country_quota
from app.services.stripe_service import create_stripe_session, verify_stripe_event

logger = logging.getLogger(__name__)
router = APIRouter()

EVENT_DATE = date(2026, 8, 15)
FREE_AGE_UNDER = 5


def _age_at(dob: date, event: date) -> int:
    years = event.year - dob.year
    if (event.month, event.day) < (dob.month, dob.day):
        years -= 1
    return years


def _compute_amount(members: list[MemberInput]) -> float:
    paid = sum(
        1 for m in members
        if _age_at(m.dob, EVENT_DATE) >= FREE_AGE_UNDER
    )
    return round(paid * settings.price_per_person_eur, 2)


@router.post("/create-payment", response_model=CreatePaymentResponse)
def create_payment(data: CreatePaymentRequest):
    check_country_quota(data.country, len(data.members))

    if not settings.stripe_secret_key:
        raise PaymentConfigError()

    amount = _compute_amount(data.members)
    if amount <= 0:
        raise PaymentConfigError("No payable members in this registration.")

    intent_id = payment_service.create_intent(
        provider=data.payment_method,
        payload=data,
        amount=amount,
    )

    payment_url = create_stripe_session(intent_id, amount, len(data.members))

    return CreatePaymentResponse(payment_url=payment_url, reference=intent_id)


@router.get("/payment/status/{intent_id}", response_model=PaymentStatusResponse)
def payment_status(intent_id: str):
    result = payment_service.lookup_intent_status(intent_id)
    if result is None:
        return PaymentStatusResponse(status="not_found", failure_reason="Payment session not found.")
    return PaymentStatusResponse(**result)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    logger.info(f"[WEBHOOK 1/5] Stripe POST received: body={len(payload)} bytes, sig_present={bool(sig_header)}")

    try:
        event = verify_stripe_event(payload, sig_header)
    except stripe.SignatureVerificationError as e:
        secret_present = bool(settings.stripe_webhook_secret)
        logger.error(f"[WEBHOOK 2/5] Stripe signature verification FAILED: {e} (secret loaded={secret_present})")
        raise WebhookVerificationError()
    except ValueError as e:
        logger.error(f"[WEBHOOK 2/5] Stripe payload not valid JSON: {e}")
        raise WebhookVerificationError()

    logger.info(f"[WEBHOOK 2/5] Stripe signature verified: type={event['type']} id={event.get('id')}")

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        payment_status = session.get("payment_status")
        intent_id = session.get("client_reference_id")
        logger.info(f"[WEBHOOK 3/5] checkout.session.completed: payment_status={payment_status} intent_id={intent_id}")

        if payment_status != "paid":
            logger.info(f"[WEBHOOK 4/5] payment_status is not 'paid' ({payment_status}) — skipping")
            return {"status": "ok"}
        if not intent_id:
            logger.warning(f"[WEBHOOK 4/5] missing client_reference_id (session={session.get('id')}) — cannot complete")
            return {"status": "ok"}

        txn = session.get("payment_intent") or session["id"]
        logger.info(f"[WEBHOOK 4/5] scheduling complete_payment: intent={intent_id} txn={txn}")
        background_tasks.add_task(
            payment_service.complete_payment,
            intent_id=intent_id,
            transaction_id=txn,
            provider="stripe",
            provider_order_id=session.get("id"),
        )
        logger.info(f"[WEBHOOK 5/5] background task scheduled — returning 200 to Stripe")

    elif event_type == "checkout.session.async_payment_succeeded":
        # Fires hours/days after checkout for async methods (SEPA, Klarna, iDEAL, Bancontact, BLIK).
        # complete_payment is idempotent — safe even if checkout.session.completed already fired.
        session = event["data"]["object"]
        intent_id = session.get("client_reference_id")
        logger.info(f"[WEBHOOK 3/5] checkout.session.async_payment_succeeded: intent_id={intent_id}")
        if not intent_id:
            logger.warning(f"[WEBHOOK 4/5] missing client_reference_id (session={session.get('id')}) — cannot complete")
            return {"status": "ok"}
        txn = session.get("payment_intent") or session["id"]
        logger.info(f"[WEBHOOK 4/5] scheduling complete_payment: intent={intent_id} txn={txn}")
        background_tasks.add_task(
            payment_service.complete_payment,
            intent_id=intent_id,
            transaction_id=txn,
            provider="stripe",
            provider_order_id=session.get("id"),
        )
        logger.info(f"[WEBHOOK 5/5] background task scheduled — returning 200 to Stripe")

    elif event_type == "checkout.session.expired":
        session = event["data"]["object"]
        intent_id = session.get("client_reference_id")
        logger.info(f"[WEBHOOK 3/5] checkout.session.expired: intent_id={intent_id}")
        if intent_id:
            payment_service.mark_intent_failed(intent_id, "Your payment session expired. Please start a new registration to try again.")

    elif event_type == "checkout.session.async_payment_failed":
        session = event["data"]["object"]
        intent_id = session.get("client_reference_id")
        logger.info(f"[WEBHOOK 3/5] checkout.session.async_payment_failed: intent_id={intent_id}")
        if intent_id:
            payment_service.mark_intent_failed(intent_id, "Your payment could not be completed (the bank or wallet rejected it). Please try again with a different method.")

    else:
        logger.info(f"[WEBHOOK 3/5] event type {event_type} not handled — returning 200")

    return {"status": "ok"}
