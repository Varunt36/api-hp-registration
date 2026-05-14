"""PayPal Orders v2 adapter using paypal-server-sdk.

Hosted-redirect flow: we create an order with intent=CAPTURE, return the
PayPal-hosted approval URL to the FE, and rely on the PAYMENT.CAPTURE.COMPLETED
webhook to drive registration completion. The intent UUID is carried via
purchase_units[].custom_id (127-char limit, easily fits a UUID).
"""
from __future__ import annotations

import json
import logging
import time

import httpx

# === SDK imports — verified against installed paypal-server-sdk 0.6.1 ===
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


def _client() -> PaypalServersdkClient:
    return PaypalServersdkClient(
        environment=(
            Environment.PRODUCTION if settings.paypal_mode == "live" else Environment.SANDBOX
        ),
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.paypal_client_id,
            o_auth_client_secret=settings.paypal_client_secret,
        ),
    )


_PAYPAL_API = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live":    "https://api-m.paypal.com",
}

_token_cache: dict = {"token": None, "expires_at": 0.0}
_TOKEN_SAFETY_SEC = 60  # refresh a minute before real expiry


def _api_base() -> str:
    return _PAYPAL_API["live" if settings.paypal_mode == "live" else "sandbox"]


def _get_access_token() -> str:
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"] - _TOKEN_SAFETY_SEC:
        return _token_cache["token"]

    response = httpx.post(
        f"{_api_base()}/v1/oauth2/token",
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        data={"grant_type": "client_credentials"},
        timeout=10.0,
    )
    response.raise_for_status()
    body = response.json()
    _token_cache["token"] = body["access_token"]
    _token_cache["expires_at"] = now + float(body.get("expires_in", 3600))
    return _token_cache["token"]


def create_paypal_order(intent_id: str, amount: float, reference: str) -> tuple[str, str]:
    """Create a PayPal v2 Order. Returns (approval_url, paypal_order_id).

    Errors:
        PaymentProviderUnreachable: PayPal couldn't be reached (DNS, TCP, timeout, 5xx).
        PaymentProviderRejected:    PayPal rejected the request (4xx, malformed body,
                                    bad credentials). Almost always a config bug on our side.
    """
    body = OrderRequest(
        intent=CheckoutPaymentIntent.CAPTURE,
        purchase_units=[PurchaseUnitRequest(
            reference_id=reference,
            custom_id=intent_id,
            invoice_id=reference,
            amount=AmountWithBreakdown(currency_code="EUR", value=f"{amount:.2f}"),
            description=f"HP 2026 Registration ({reference})",
        )],
        payment_source=PaymentSource(
            paypal=PaypalWallet(
                experience_context=PaypalWalletExperienceContext(
                    return_url=f"{settings.frontend_url}/payment/success?ref={reference}",
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
        response = _client().orders.orders_create({
            "body": body,
            "prefer": "return=representation",
        })
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 0
        if status >= 500:
            logger.warning(f"PayPal 5xx during create-order: ref={reference} status={status}")
            raise PaymentProviderUnreachable("paypal", f"http_{status}")
        body_text = e.response.text if e.response is not None else ""
        logger.exception(f"PayPal 4xx during create-order: ref={reference} status={status} body={body_text}")
        raise PaymentProviderRejected("paypal", f"http_{status}")
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        logger.warning(f"PayPal network failure during create-order: ref={reference} err={type(e).__name__}: {e}")
        raise PaymentProviderUnreachable("paypal", f"network_{type(e).__name__}")
    except Exception as e:
        logger.exception(f"PayPal order creation failed: ref={reference} err={type(e).__name__}: {e}")
        raise PaymentProviderUnreachable("paypal", f"unknown_{type(e).__name__}")

    order = response.body
    approve_url = next((link.href for link in order.links if link.rel == "payer-action"), None)
    if not approve_url:
        logger.error(f"PayPal order missing payer-action link: ref={reference} order={getattr(order, 'id', '?')}")
        raise PaymentProviderRejected("paypal", "no_payer_action_link")

    logger.info(f"PayPal order created: ref={reference} order={order.id} EUR{amount:.2f}")
    return approve_url, order.id


_WEBHOOK_MAX_BYTES = 1024 * 1024  # 1 MiB hard cap


def verify_paypal_webhook(headers: dict, raw_body: bytes) -> dict:
    """Verify a PayPal webhook signature via the postback API and return the parsed event.

    Raw body is passed through unchanged — parsing-then-re-serializing changes
    the CRC32 and breaks verification.

    Errors:
        WebhookVerificationError:    bad signature, malformed body, missing headers,
                                     oversized body, or postback returned FAILURE.
                                     The webhook route should answer 400.
        PaymentProviderUnreachable:  couldn't reach PayPal to verify (network, 5xx).
                                     The webhook route should answer 503 so PayPal retries.
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
    except (KeyError, ValueError) as e:
        logger.warning(f"PayPal webhook missing required headers or non-JSON body: {type(e).__name__}")
        raise WebhookVerificationError()

    try:
        token = _get_access_token()
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
        logger.warning(f"Couldn't fetch PayPal access token for webhook verify: {type(e).__name__}: {e}")
        raise PaymentProviderUnreachable("paypal", f"oauth_{type(e).__name__}")

    try:
        response = httpx.post(
            f"{_api_base()}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}"},
            json=verification_request,
            timeout=10.0,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        logger.warning(f"PayPal verify endpoint unreachable: {type(e).__name__}: {e}")
        raise PaymentProviderUnreachable("paypal", f"verify_{type(e).__name__}")

    if response.status_code >= 500:
        logger.warning(f"PayPal verify returned 5xx: status={response.status_code}")
        raise PaymentProviderUnreachable("paypal", f"verify_http_{response.status_code}")

    if response.status_code >= 400:
        logger.error(f"PayPal verify rejected our request: status={response.status_code} body={response.text}")
        raise WebhookVerificationError()

    if response.json().get("verification_status") != "SUCCESS":
        logger.warning("PayPal webhook signature verification returned FAILURE")
        raise WebhookVerificationError()

    return json.loads(raw_body)


def extract_capture_intent_id(event: dict) -> str | None:
    """Pull the intent UUID we stamped onto custom_id at order creation."""
    return event.get("resource", {}).get("custom_id")


def extract_capture_transaction_id(event: dict) -> str | None:
    """The capture id is what we record as transaction_id."""
    return event.get("resource", {}).get("id")


def extract_supplementary_order_id(event: dict) -> str | None:
    """The parent order id (for audit cross-reference)."""
    sup = event.get("resource", {}).get("supplementary_data", {}).get("related_ids", {})
    return sup.get("order_id")
