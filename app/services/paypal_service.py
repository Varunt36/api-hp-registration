"""PayPal Orders v2 adapter. Intent UUID is carried via purchase_units[].custom_id."""
from __future__ import annotations

import json
import logging

import httpx

from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.paypal_experience_landing_page import PaypalExperienceLandingPage
from paypalserversdk.models.paypal_experience_user_action import PaypalExperienceUserAction
from paypalserversdk.models.paypal_wallet import PaypalWallet
from paypalserversdk.models.paypal_wallet_experience_context import PaypalWalletExperienceContext
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest

from app.core.config import settings
from app.core.exceptions import (
    PaymentProviderRejected,
    PaymentProviderUnreachable,
    WebhookVerificationError,
)

logger = logging.getLogger(__name__)

_WEBHOOK_MAX_BYTES = 1024 * 1024


def _client() -> PaypalServersdkClient:
    return PaypalServersdkClient(
        environment=Environment.PRODUCTION if settings.paypal_mode == "live" else Environment.SANDBOX,
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.paypal_client_id,
            o_auth_client_secret=settings.paypal_client_secret,
        ),
    )


def _api_base() -> str:
    return "https://api-m.paypal.com" if settings.paypal_mode == "live" else "https://api-m.sandbox.paypal.com"


def _get_access_token() -> str:
    r = httpx.post(
        f"{_api_base()}/v1/oauth2/token",
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        data={"grant_type": "client_credentials"},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_paypal_order(intent_id: str, amount: float) -> tuple[str, str]:
    """Create a PayPal v2 Order. Returns (approval_url, paypal_order_id)."""
    body = OrderRequest(
        intent=CheckoutPaymentIntent.CAPTURE,
        purchase_units=[PurchaseUnitRequest(
            custom_id=intent_id,
            amount=AmountWithBreakdown(currency_code="EUR", value=f"{amount:.2f}"),
            description="HP 2026 Registration",
        )],
        payment_source=PaymentSource(
            paypal=PaypalWallet(
                experience_context=PaypalWalletExperienceContext(
                    return_url=f"{settings.frontend_url}/payment/success?intent_id={intent_id}",
                    cancel_url=f"{settings.frontend_url}/payment/cancel",
                    landing_page=PaypalExperienceLandingPage.LOGIN,
                    user_action=PaypalExperienceUserAction.PAY_NOW,
                    brand_name="HP 2026 Registration",
                    locale="en-US",
                ),
            ),
        ),
    )

    try:
        response = _client().orders.orders_create({"body": body, "prefer": "return=representation"})
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 0
        logger.warning(f"PayPal {status} during create-order: intent={intent_id}")
        raise (PaymentProviderUnreachable if status >= 500 else PaymentProviderRejected)("paypal", f"http_{status}")
    except Exception as e:
        logger.exception(f"PayPal create-order failed: intent={intent_id}")
        raise PaymentProviderUnreachable("paypal", type(e).__name__)

    order = response.body
    approve_url = next((link.href for link in order.links if link.rel == "payer-action"), None)
    if not approve_url:
        logger.error(f"PayPal order missing payer-action link: intent={intent_id}")
        raise PaymentProviderRejected("paypal", "no_payer_action_link")

    logger.info(f"PayPal order created: intent={intent_id} order={order.id} EUR{amount:.2f}")
    return approve_url, order.id


def verify_paypal_webhook(headers: dict, raw_body: bytes) -> dict:
    """Verify a PayPal webhook signature via postback. Returns the parsed event.

    Raw body must be unchanged — re-serializing changes the CRC32 and breaks verification.
    """
    if len(raw_body) > _WEBHOOK_MAX_BYTES:
        logger.warning(f"PayPal webhook body too large: {len(raw_body)} bytes")
        raise WebhookVerificationError()

    try:
        verification_request = {
            "auth_algo":         headers["paypal-auth-algo"],
            "cert_url":          headers["paypal-cert-url"],
            "transmission_id":   headers["paypal-transmission-id"],
            "transmission_sig":  headers["paypal-transmission-sig"],
            "transmission_time": headers["paypal-transmission-time"],
            "webhook_id":        settings.paypal_webhook_id,
            "webhook_event":     json.loads(raw_body),
        }
    except (KeyError, ValueError):
        logger.warning("PayPal webhook missing headers or non-JSON body")
        raise WebhookVerificationError()

    try:
        token = _get_access_token()
        response = httpx.post(
            f"{_api_base()}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}"},
            json=verification_request,
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning(f"PayPal verify unreachable: {type(e).__name__}")
        raise PaymentProviderUnreachable("paypal", "verify")

    if response.status_code >= 500:
        raise PaymentProviderUnreachable("paypal", f"verify_{response.status_code}")
    if response.status_code >= 400 or response.json().get("verification_status") != "SUCCESS":
        logger.warning(f"PayPal webhook verification failed: status={response.status_code}")
        raise WebhookVerificationError()

    return json.loads(raw_body)
