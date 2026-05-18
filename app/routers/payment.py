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
        return PaymentStatusResponse(status="not_found")
    return PaymentStatusResponse(**result)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_stripe_event(payload, sig_header)
    except (stripe.SignatureVerificationError, ValueError):
        logger.warning("Stripe webhook signature verification failed")
        raise WebhookVerificationError()

    logger.info(f"Stripe webhook received: {event['type']}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session.get("payment_status") != "paid":
            return {"status": "ok"}
        intent_id = session.get("client_reference_id")
        if not intent_id:
            logger.warning(f"Stripe webhook missing intent_id (session={session.get('id')})")
        else:
            background_tasks.add_task(
                payment_service.complete_payment,
                intent_id=intent_id,
                transaction_id=session.get("payment_intent") or session["id"],
                provider="stripe",
                provider_order_id=session.get("id"),
            )

    return {"status": "ok"}


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    event = verify_paypal_webhook(headers, raw_body)

    event_type = event.get("event_type", "")
    logger.info(f"PayPal webhook received: {event_type}")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource", {})
        intent_id = resource.get("custom_id")
        transaction_id = resource.get("id")
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        if intent_id and transaction_id:
            background_tasks.add_task(
                payment_service.complete_payment,
                intent_id=intent_id,
                transaction_id=transaction_id,
                provider="paypal",
                provider_order_id=order_id,
            )
        else:
            logger.warning(f"PayPal webhook missing identifiers: intent={intent_id} txn={transaction_id}")

    return {"status": "ok"}
