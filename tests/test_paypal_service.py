"""Unit tests for paypal_service.

We mock the SDK at the client-factory boundary so the tests run offline.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import (
    PaymentProviderRejected,
    PaymentProviderUnreachable,
)


@patch("app.services.paypal_service._client")
def test_create_paypal_order_builds_correct_request_and_returns_approve_url(mock_client):
    """Asserts the OrderRequest carries intent_id in custom_id and returns the approve link."""
    fake_orders = MagicMock()
    mock_client.return_value.orders = fake_orders
    fake_response = MagicMock()
    fake_link = MagicMock()
    fake_link.rel = "payer-action"
    fake_link.href = "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123"
    fake_response.body.id = "ORDER123"
    fake_response.body.links = [fake_link]
    fake_orders.orders_create.return_value = fake_response

    from app.services.paypal_service import create_paypal_order
    url, order_id = create_paypal_order(
        intent_id="11111111-1111-1111-1111-111111111111",
        amount=500.00,
        reference="HP-2026-00042",
    )

    assert url == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123"
    assert order_id == "ORDER123"

    # Inspect the request body passed to the SDK
    call_kwargs = fake_orders.orders_create.call_args[0][0]
    body = call_kwargs["body"]
    pu = body.purchase_units[0]
    assert pu.custom_id == "11111111-1111-1111-1111-111111111111"
    assert pu.invoice_id == "HP-2026-00042"
    assert pu.amount.currency_code == "EUR"
    assert pu.amount.value == "500.00"


@patch("app.services.paypal_service._client")
def test_create_paypal_order_network_failure_raises_unreachable(mock_client):
    import httpx
    fake_orders = MagicMock()
    mock_client.return_value.orders = fake_orders
    fake_orders.orders_create.side_effect = httpx.ConnectTimeout("connect timeout")

    from app.services.paypal_service import create_paypal_order
    with pytest.raises(PaymentProviderUnreachable):
        create_paypal_order(intent_id="x", amount=250.00, reference="HP-2026-00001")


@patch("app.services.paypal_service._client")
def test_create_paypal_order_5xx_raises_unreachable(mock_client):
    import httpx
    fake_orders = MagicMock()
    mock_client.return_value.orders = fake_orders
    fake_response = MagicMock()
    fake_response.status_code = 503
    fake_response.text = "Service Unavailable"
    fake_orders.orders_create.side_effect = httpx.HTTPStatusError(
        "5xx", request=MagicMock(), response=fake_response,
    )

    from app.services.paypal_service import create_paypal_order
    with pytest.raises(PaymentProviderUnreachable):
        create_paypal_order(intent_id="x", amount=250.00, reference="HP-2026-00001")


@patch("app.services.paypal_service._client")
def test_create_paypal_order_4xx_raises_rejected(mock_client):
    import httpx
    fake_orders = MagicMock()
    mock_client.return_value.orders = fake_orders
    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.text = "Invalid amount"
    fake_orders.orders_create.side_effect = httpx.HTTPStatusError(
        "4xx", request=MagicMock(), response=fake_response,
    )

    from app.services.paypal_service import create_paypal_order
    with pytest.raises(PaymentProviderRejected):
        create_paypal_order(intent_id="x", amount=250.00, reference="HP-2026-00001")


@patch("app.services.paypal_service._client")
def test_create_paypal_order_missing_approve_link_raises_rejected(mock_client):
    """Defensive: if PayPal succeeds-with-no-link, surface as a permanent error so we don't loop."""
    fake_orders = MagicMock()
    mock_client.return_value.orders = fake_orders
    fake_response = MagicMock()
    fake_response.body.id = "ORDER123"
    fake_response.body.links = []  # no payer-action link
    fake_orders.orders_create.return_value = fake_response

    from app.services.paypal_service import create_paypal_order
    with pytest.raises(PaymentProviderRejected):
        create_paypal_order(intent_id="x", amount=250.00, reference="HP-2026-00001")


@patch("app.services.paypal_service.httpx.post")
def test_access_token_is_cached_until_expiry(mock_post):
    from app.services import paypal_service
    # Reset the module-level cache state so this test is hermetic
    paypal_service._token_cache = {"token": None, "expires_at": 0}

    fake = MagicMock()
    fake.json.return_value = {"access_token": "A1", "expires_in": 3600}
    fake.raise_for_status = MagicMock()
    mock_post.return_value = fake

    t1 = paypal_service._get_access_token()
    t2 = paypal_service._get_access_token()
    assert t1 == "A1"
    assert t2 == "A1"
    # Should have been fetched only once because of the cache
    assert mock_post.call_count == 1


@patch("app.services.paypal_service._get_access_token", return_value="TKN")
@patch("app.services.paypal_service.httpx.post")
def test_verify_paypal_webhook_success(mock_post, mock_token):
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"verification_status": "SUCCESS"}
    fake.raise_for_status = MagicMock()
    mock_post.return_value = fake

    from app.services.paypal_service import verify_paypal_webhook
    raw = b'{"event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"CAP-1","custom_id":"intent-1"}}'
    headers = {
        "paypal-auth-algo":         "SHA256withRSA",
        "paypal-cert-url":          "https://api.paypal.com/v1/notifications/certs/CERT",
        "paypal-transmission-id":   "TX1",
        "paypal-transmission-sig":  "SIG",
        "paypal-transmission-time": "2026-05-14T10:00:00Z",
    }
    event = verify_paypal_webhook(headers, raw)
    assert event["event_type"] == "PAYMENT.CAPTURE.COMPLETED"
    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["webhook_event"]["resource"]["id"] == "CAP-1"


@patch("app.services.paypal_service._get_access_token", return_value="TKN")
@patch("app.services.paypal_service.httpx.post")
def test_verify_paypal_webhook_failure_raises(mock_post, mock_token):
    from app.core.exceptions import WebhookVerificationError
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"verification_status": "FAILURE"}
    fake.raise_for_status = MagicMock()
    mock_post.return_value = fake

    from app.services.paypal_service import verify_paypal_webhook
    with pytest.raises(WebhookVerificationError):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a", "paypal-cert-url": "b",
             "paypal-transmission-id": "c", "paypal-transmission-sig": "d",
             "paypal-transmission-time": "e"},
            b"{}",
        )


def test_verify_paypal_webhook_rejects_oversized_body():
    from app.core.exceptions import WebhookVerificationError
    from app.services.paypal_service import verify_paypal_webhook
    huge = b"{" + (b" " * (1024 * 1024 + 1)) + b"}"
    with pytest.raises(WebhookVerificationError):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a", "paypal-cert-url": "b",
             "paypal-transmission-id": "c", "paypal-transmission-sig": "d",
             "paypal-transmission-time": "e"},
            huge,
        )


@patch("app.services.paypal_service._get_access_token", return_value="TKN")
@patch("app.services.paypal_service.httpx.post")
def test_verify_paypal_webhook_network_failure_raises_unreachable(mock_post, mock_token):
    """Transient network failure must NOT report signature failure (PayPal would stop retrying)."""
    import httpx
    from app.core.exceptions import PaymentProviderUnreachable
    mock_post.side_effect = httpx.ConnectTimeout("connect timeout")

    from app.services.paypal_service import verify_paypal_webhook
    with pytest.raises(PaymentProviderUnreachable):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a", "paypal-cert-url": "b",
             "paypal-transmission-id": "c", "paypal-transmission-sig": "d",
             "paypal-transmission-time": "e"},
            b"{}",
        )


@patch("app.services.paypal_service._get_access_token", return_value="TKN")
@patch("app.services.paypal_service.httpx.post")
def test_verify_paypal_webhook_5xx_from_verify_endpoint_raises_unreachable(mock_post, mock_token):
    from app.core.exceptions import PaymentProviderUnreachable
    fake = MagicMock()
    fake.status_code = 502
    fake.text = "Bad Gateway"
    mock_post.return_value = fake

    from app.services.paypal_service import verify_paypal_webhook
    with pytest.raises(PaymentProviderUnreachable):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a", "paypal-cert-url": "b",
             "paypal-transmission-id": "c", "paypal-transmission-sig": "d",
             "paypal-transmission-time": "e"},
            b"{}",
        )


def test_verify_paypal_webhook_missing_header_raises_verification_error():
    from app.core.exceptions import WebhookVerificationError
    from app.services.paypal_service import verify_paypal_webhook
    with pytest.raises(WebhookVerificationError):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a"},
            b"{}",
        )


def test_verify_paypal_webhook_non_json_body_raises_verification_error():
    from app.core.exceptions import WebhookVerificationError
    from app.services.paypal_service import verify_paypal_webhook
    with pytest.raises(WebhookVerificationError):
        verify_paypal_webhook(
            {"paypal-auth-algo": "a", "paypal-cert-url": "b",
             "paypal-transmission-id": "c", "paypal-transmission-sig": "d",
             "paypal-transmission-time": "e"},
            b"this is not json {{{",
        )
