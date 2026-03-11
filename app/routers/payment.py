import json
import logging

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.models.payment import CreatePaymentRequest, CreatePaymentResponse, PaymentMethod
from app.services.registration_service import create_registration
from app.services.payment_service import (
    create_pending_payment,
    create_stripe_session,
    create_paypal_order,
    verify_stripe_event,
    verify_paypal_webhook,
    capture_paypal_order,
    complete_payment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create-payment", response_model=CreatePaymentResponse)
def create_payment(data: CreatePaymentRequest):
    """Create registration + pending payment + redirect URL.

    Flow:
      1. Validate & save registration + members to DB
      2. Create pending payment record
      3. Create Stripe/PayPal checkout session
      4. Return payment URL for frontend redirect
    """
    try:
        # 1. Save registration + members (reuses existing logic, no QR/emails yet)
        result = create_registration(data)
        registration_id = result["registration_id"]
        reference = result["reference"]
        member_count = result["member_count"]

        # 2. Calculate total amount
        amount = member_count * settings.payment_amount_per_member

        # 3. Store pending payment
        create_pending_payment(registration_id, amount, data.payment_method.value)

        # 4. Create checkout session with the payment provider
        if data.payment_method == PaymentMethod.stripe:
            payment_url = create_stripe_session(registration_id, reference, amount)
        else:
            payment_url = create_paypal_order(registration_id, reference, amount)

        return CreatePaymentResponse(reference=reference, payment_url=payment_url)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Payment creation failed")
        raise HTTPException(status_code=500, detail="Payment creation failed. Please try again.")


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe calls this directly after payment. Verifies signature, completes registration."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_stripe_event(payload, sig_header)
    except Exception:
        logger.exception("Stripe webhook verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        registration_id = session["metadata"]["registration_id"]
        transaction_id = session.get("payment_intent", session["id"])

        try:
            complete_payment(registration_id, transaction_id)
        except Exception:
            logger.exception(f"Payment completion failed for {registration_id}")

    return {"status": "ok"}


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    """PayPal calls this directly after payment. Verifies signature, captures + completes."""
    body = await request.body()
    headers = dict(request.headers)

    if not verify_paypal_webhook(headers, body):
        logger.warning("PayPal webhook verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = json.loads(body)
    event_type = event.get("event_type", "")

    if event_type == "CHECKOUT.ORDER.APPROVED":
        order_id = event["resource"]["id"]
        try:
            # Capture the approved order, then complete registration
            capture_result = capture_paypal_order(order_id)
            purchase_unit = capture_result["purchase_units"][0]
            registration_id = purchase_unit["reference_id"]
            transaction_id = purchase_unit["payments"]["captures"][0]["id"]

            complete_payment(registration_id, transaction_id)
        except Exception:
            logger.exception("PayPal capture/completion failed")

    return {"status": "ok"}
