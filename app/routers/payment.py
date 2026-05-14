import logging

from fastapi import APIRouter, BackgroundTasks, Request

from app.core.config import settings
from app.core.exceptions import PaymentConfigError, WebhookVerificationError
from app.models.payment import CreatePaymentRequest, CreatePaymentResponse, PaymentMethod, PaymentStatusResponse
from app.services import payment_intent_service
from app.services.payment_service import complete_payment
from app.services.registration_service import allocate_reference, check_country_quota
from app.services.paypal_service import (
    create_paypal_order,
    extract_capture_intent_id,
    extract_capture_transaction_id,
    extract_supplementary_order_id,
    verify_paypal_webhook,
)
from app.services.stripe_service import (
    create_stripe_session,
    extract_intent_id as stripe_extract_intent_id,
    extract_transaction_id as stripe_extract_transaction_id,
    get_payment_status,
    verify_stripe_event,
)

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

    allocation = allocate_reference(data)
    reference = allocation["reference"]
    amount = len(data.members) * settings.payment_amount_per_member

    intent_id = payment_intent_service.create(
        reference=reference,
        provider=data.payment_method.value,
        payload=data,
        amount=amount,
    )

    if data.payment_method == PaymentMethod.stripe:
        payment_url = create_stripe_session(intent_id, amount, reference, len(data.members))
    else:
        payment_url, _ = create_paypal_order(intent_id, amount, reference)

    return CreatePaymentResponse(payment_url=payment_url, reference=reference)


@router.get("/payment/status/{session_id}", response_model=PaymentStatusResponse)
def payment_status(session_id: str):
    return PaymentStatusResponse(**get_payment_status(session_id))


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_stripe_event(payload, sig_header)
    except Exception:
        logger.warning("Stripe webhook signature verification failed")
        raise WebhookVerificationError()

    event_type = event["type"]
    logger.info(f"Stripe webhook received: {event_type}")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        intent_id = stripe_extract_intent_id(session)
        transaction_id = stripe_extract_transaction_id(session)
        if intent_id is None:
            logger.warning(f"Stripe webhook missing intent_id (session={session.get('id')})")
        else:
            background_tasks.add_task(
                complete_payment,
                intent_id=intent_id,
                transaction_id=transaction_id,
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
        intent_id = extract_capture_intent_id(event)
        transaction_id = extract_capture_transaction_id(event)
        order_id = extract_supplementary_order_id(event)
        if intent_id is None or transaction_id is None:
            logger.warning(f"PayPal webhook missing identifiers: intent={intent_id} txn={transaction_id} order={order_id}")
        else:
            background_tasks.add_task(
                complete_payment,
                intent_id=intent_id,
                transaction_id=transaction_id,
                provider="paypal",
                provider_order_id=order_id,
            )

    return {"status": "ok"}
