import logging

from fastapi import APIRouter, BackgroundTasks, Request

from app.core.config import settings
from app.core.exceptions import PaymentConfigError, WebhookVerificationError
from app.models.payment import CreatePaymentRequest, CreatePaymentResponse
from app.services.registration_service import check_country_quota, check_duplicate_member
from app.services.payment_service import create_stripe_session, verify_stripe_event, complete_payment

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create-payment", response_model=CreatePaymentResponse)
def create_payment(data: CreatePaymentRequest):
    check_country_quota(data.country, len(data.members))

    if data.members[0].email:
        check_duplicate_member(data.members[0].email)

    if not settings.stripe_secret_key:
        raise PaymentConfigError()

    amount = len(data.members) * settings.payment_amount_per_member
    payment_url = create_stripe_session(data, amount)

    return CreatePaymentResponse(payment_url=payment_url)


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
        background_tasks.add_task(complete_payment, session)

    return {"status": "ok"}
