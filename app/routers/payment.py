import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.core.config import settings
from app.models.payment import CreatePaymentRequest, CreatePaymentResponse
from app.services.registration_service import check_country_quota
from app.services.payment_service import (
    create_stripe_session,
    verify_stripe_event,
    complete_payment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create-payment", response_model=CreatePaymentResponse)
def create_payment(data: CreatePaymentRequest):
    """Validate registration data and create a Stripe Checkout session.

    NO database writes happen here. Registration data is stored in Stripe metadata.
    DB insert only happens in the webhook after payment succeeds.
    """
    try:
        # Pre-check quota (gives user early feedback; definitive check in webhook)
        check_country_quota(data.country, len(data.members))

        # Calculate amount
        amount = len(data.members) * settings.payment_amount_per_member

        # Create Stripe session with data in metadata (no DB insert)
        payment_url = create_stripe_session(data, amount)

        return CreatePaymentResponse(payment_url=payment_url)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Payment creation failed")
        raise HTTPException(status_code=500, detail="Payment creation failed. Please try again.")


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Stripe calls this after payment events. Verifies signature, then processes.

    On checkout.session.completed:
      - Reconstructs registration data from metadata
      - Inserts registration + members + payment into DB
      - Sends QR + emails
    All heavy work runs in background so webhook responds fast (< 5s).
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_stripe_event(payload, sig_header)
    except Exception:
        logger.exception("Stripe webhook verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    logger.info(f"Stripe webhook received: {event_type}")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        # Run DB insert + emails in background so Stripe gets 200 quickly
        background_tasks.add_task(complete_payment, session)

    # checkout.session.expired: nothing to clean up (no DB rows exist)

    return {"status": "ok"}
