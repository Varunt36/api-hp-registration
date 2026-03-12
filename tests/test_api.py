"""Tests for the /register API endpoint."""

from unittest.mock import patch
from tests.conftest import VALID_PAYLOAD, VALID_PAYLOAD_MULTI, setup_db_for_success


class TestRegisterEndpoint:
    def test_successful_registration(self, client, mock_db):
        setup_db_for_success(mock_db)

        response = client.post("/register", json=VALID_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["reference"] == "HP-2026-00001"
        assert data["member_count"] == 1

    def test_successful_multi_member(self, client, mock_db):
        setup_db_for_success(mock_db)

        response = client.post("/register", json=VALID_PAYLOAD_MULTI)

        assert response.status_code == 200
        data = response.json()
        assert data["member_count"] == 2

    def test_invalid_country_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "country": "ZZ"}
        response = client.post("/register", json=payload)
        assert response.status_code == 422

    def test_missing_fields_returns_422(self, client):
        response = client.post("/register", json={"country": "DE"})
        assert response.status_code == 422

    def test_terms_not_accepted_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "terms_accepted": False}
        response = client.post("/register", json=payload)
        assert response.status_code == 422

    def test_first_member_no_email_returns_422(self, client):
        payload = {
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
        }
        response = client.post("/register", json=payload)
        assert response.status_code == 422

    def test_quota_exceeded_returns_400(self, client, mock_db):
        """Fix #5: ValueError returns 400 with clear message."""
        with patch(
            "app.routers.registration.create_registration",
            side_effect=ValueError("Registration limit reached for country DE. Only 0 spots remain."),
        ):
            response = client.post("/register", json=VALID_PAYLOAD)

        assert response.status_code == 400
        assert "limit reached" in response.json()["detail"]

    def test_unexpected_error_returns_500_generic(self, client, mock_db):
        """Fix #5: unexpected errors return generic message, not internals."""
        with patch(
            "app.routers.registration.create_registration",
            side_effect=RuntimeError("Supabase connection pool exhausted at 0x7f..."),
        ):
            response = client.post("/register", json=VALID_PAYLOAD)

        assert response.status_code == 500
        # Must NOT leak internal error details
        assert "pool" not in response.json()["detail"]
        assert response.json()["detail"] == "Registration failed. Please try again."

    def test_rate_limiting(self, client, mock_db):
        """Fix #4: rate limiter blocks after 5 requests/minute."""
        setup_db_for_success(mock_db)

        for i in range(5):
            resp = client.post("/register", json=VALID_PAYLOAD)
            assert resp.status_code == 200, f"Request {i+1} should succeed"

        # 6th request should be rate limited
        resp = client.post("/register", json=VALID_PAYLOAD)
        assert resp.status_code == 429
        assert "Too many requests" in resp.json()["detail"]

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
