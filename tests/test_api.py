"""Tests for the /create-payment API endpoint."""

from unittest.mock import patch, MagicMock
from tests.conftest import VALID_PAYLOAD, VALID_PAYLOAD_MULTI


def _payment_payload(base=None):
    """Add payment_method to a registration payload."""
    payload = dict(base or VALID_PAYLOAD)
    payload["payment_method"] = "stripe"
    return payload


class TestCreatePaymentEndpoint:
    def test_successful_payment_creation(self, client, mock_db):
        quotas_table = MagicMock()
        members_table = MagicMock()
        mock_db.table.side_effect = lambda name: {
            "country_quotas": quotas_table,
            "members": members_table,
        }.get(name, MagicMock())

        quotas_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        members_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        with patch("app.routers.payment.create_stripe_session", return_value="https://checkout.stripe.com/test"):
            response = client.post("/create-payment", json=_payment_payload())

        assert response.status_code == 200
        assert response.json()["payment_url"] == "https://checkout.stripe.com/test"

    def test_invalid_country_returns_422(self, client):
        payload = _payment_payload({**VALID_PAYLOAD, "country": "ZZ"})
        response = client.post("/create-payment", json=payload)
        assert response.status_code == 422

    def test_missing_fields_returns_422(self, client):
        response = client.post("/create-payment", json={"country": "DE", "payment_method": "stripe"})
        assert response.status_code == 422

    def test_terms_not_accepted_returns_422(self, client):
        payload = _payment_payload({**VALID_PAYLOAD, "terms_accepted": False})
        response = client.post("/create-payment", json=payload)
        assert response.status_code == 422

    def test_first_member_no_email_returns_422(self, client):
        payload = _payment_payload({
            "country": "DE",
            "karyakarta": "John Doe",
            "terms_accepted": True,
            "members": [
                {
                    "first_name": "John",
                    "last_name": "Doe",
                    "gender": "male",
                    "dob": "1990-05-15",
                }
            ],
        })
        response = client.post("/create-payment", json=payload)
        assert response.status_code == 422

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
