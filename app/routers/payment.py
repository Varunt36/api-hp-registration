import logging

import stripe
from fastapi import APIRouter, BackgroundTasks, Request

from app.core.config import settings
from app.core.exceptions import PaymentConfigError, WebhookVerificationError
from app.models.payment import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentMethod,
    PaymentStatusResponse,
)
from app.services import payment_service
from app.services.paypal_service import create_paypal_order, verify_paypal_webhook
from app.services.registration_service import check_country_quota
from app.services.stripe_service import create_stripe_session, verify_stripe_event

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create-payment", response_model=CreatePaymentResponse)
def create_payment(data: CreatePaymentRequest):
    check_country_quota(data.country, len(data.members))

    if data.payment_method == PaymentMethod.stripe and not settings.stripe_secret_key:
        raise PaymentConfigError()
    if data.payment_method == PaymentMethod.paypal and not (
        settings.paypal_client_id and settings.paypal_client_secret
    ):
        raise PaymentConfigError()

    amount = len(data.members) * settings.payment_amount_per_member
    intent_id = payment_service.create_intent(
        provider=data.payment_method.value,
        payload=data,
        amount=amount,
    )

    if data.payment_method == PaymentMethod.stripe:
        payment_url = create_stripe_session(intent_id, amount, len(data.members))
    else:
        payment_url, _ = create_paypal_order(intent_id, amount)

    return CreatePaymentResponse(payment_url=payment_url, intent_id=intent_id)


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


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    logger.info(f"[WEBHOOK 1/5] PayPal POST received: body={len(raw_body)} bytes")
    event = verify_paypal_webhook(headers, raw_body)

    event_type = event.get("event_type", "")
    logger.info(f"[WEBHOOK 2/5] PayPal signature verified: event_type={event_type}")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource", {})
        intent_id = resource.get("custom_id")
        transaction_id = resource.get("id")
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        logger.info(f"[WEBHOOK 3/5] PAYMENT.CAPTURE.COMPLETED: intent={intent_id} txn={transaction_id} order={order_id}")
        if intent_id and transaction_id:
            background_tasks.add_task(
                payment_service.complete_payment,
                intent_id=intent_id,
                transaction_id=transaction_id,
                provider="paypal",
                provider_order_id=order_id,
            )
            logger.info(f"[WEBHOOK 5/5] background task scheduled — returning 200 to PayPal")
        else:
            logger.warning(f"[WEBHOOK 4/5] missing identifiers: intent={intent_id} txn={transaction_id} — cannot complete")

    elif event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED", "CHECKOUT.ORDER.VOIDED"):
        resource = event.get("resource", {})
        intent_id = resource.get("custom_id") or (
            (resource.get("purchase_units") or [{}])[0].get("custom_id")
        )
        status_details = resource.get("status_details") or {}
        reason = status_details.get("reason") or "Your PayPal payment was not completed."
        logger.info(f"[WEBHOOK 3/5] {event_type}: intent={intent_id} reason={reason}")
        if intent_id:
            payment_service.mark_intent_failed(intent_id, f"PayPal declined the payment: {reason}. Please try again or use a different payment method.")

    else:
        logger.info(f"[WEBHOOK 3/5] event type {event_type} not handled — returning 200")

    return {"status": "ok"}
