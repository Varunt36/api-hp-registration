"""Tests for the /create-payment API endpoint."""

from datetime import date
from unittest.mock import patch, MagicMock

from app.models.registration import Gender
from app.services.registration_service import create_admin_registration
from tests.conftest import VALID_PAYLOAD, VALID_PAYLOAD_MULTI, setup_db_for_success


def _admin_user(role="admin", email="admin@example.com", user_id="admin-uuid"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.app_metadata = {"role": role} if role else {}
    return MagicMock(user=user)


def _auth_headers(token="valid.jwt.token"):
    return {"Authorization": f"Bearer {token}"}


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

        with patch("app.routers.payment.allocate_reference",
                   return_value={"registration_id": "test-id", "reference": "HP-2026-00001"}), \
             patch("app.routers.payment.payment_intent_service.create",
                   return_value="11111111-1111-1111-1111-111111111111"), \
             patch("app.routers.payment.create_stripe_session",
                   return_value="https://checkout.stripe.com/test"):
            response = client.post("/create-payment", json=_payment_payload())

        assert response.status_code == 200
        assert response.json()["payment_url"] == "https://checkout.stripe.com/test"
        assert response.json()["reference"] == "HP-2026-00001"

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


VALID_ADMIN_PAYLOAD = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "dob": "1990-05-15",
    "gender": "female",
    "country": "DE",
}


class TestAdminRegistrationEndpoint:
    def test_successful_admin_registration(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        with patch(
            "app.routers.admin.create_admin_registration",
            return_value={"reference": "HP-2026-00001", "ticket_number": "HP-2026-00001-M1"},
        ):
            response = client.post(
                "/admin/registration",
                json=VALID_ADMIN_PAYLOAD,
                headers=_auth_headers(),
            )

        assert response.status_code == 200
        assert response.json() == {"reference": "HP-2026-00001", "ticket_number": "HP-2026-00001-M1"}

    def test_missing_authorization_returns_401(self, client):
        response = client.post("/admin/registration", json=VALID_ADMIN_PAYLOAD)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"

    def test_malformed_authorization_returns_401(self, client):
        response = client.post(
            "/admin/registration",
            json=VALID_ADMIN_PAYLOAD,
            headers={"Authorization": "NotBearer abc"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"

    def test_invalid_jwt_returns_401(self, client, mock_db):
        mock_db.auth.get_user.side_effect = Exception("invalid token")
        response = client.post(
            "/admin/registration",
            json=VALID_ADMIN_PAYLOAD,
            headers=_auth_headers("bad.jwt"),
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"

    def test_non_admin_user_returns_403(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user(role=None)
        response = client.post(
            "/admin/registration",
            json=VALID_ADMIN_PAYLOAD,
            headers=_auth_headers(),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ADMIN_FORBIDDEN"

    def test_user_metadata_role_is_ignored(self, client, mock_db):
        """Authorization MUST come from app_metadata; user_metadata is user-editable."""
        user = MagicMock()
        user.id = "uid"
        user.email = "u@example.com"
        user.app_metadata = {}
        user.user_metadata = {"role": "admin"}
        mock_db.auth.get_user.return_value = MagicMock(user=user)

        response = client.post(
            "/admin/registration",
            json=VALID_ADMIN_PAYLOAD,
            headers=_auth_headers(),
        )
        assert response.status_code == 403

    def test_missing_full_name_returns_422(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {k: v for k, v in VALID_ADMIN_PAYLOAD.items() if k != "full_name"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_invalid_email_returns_422(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {**VALID_ADMIN_PAYLOAD, "email": "not-an-email"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_future_dob_returns_422(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {**VALID_ADMIN_PAYLOAD, "dob": "2099-01-01"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_unsafe_chars_in_full_name_rejected(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {**VALID_ADMIN_PAYLOAD, "full_name": "<script>Jane</script>"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_invalid_country_returns_422(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {**VALID_ADMIN_PAYLOAD, "country": "ZZ"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_invalid_gender_returns_422(self, client, mock_db):
        mock_db.auth.get_user.return_value = _admin_user()
        payload = {**VALID_ADMIN_PAYLOAD, "gender": "other"}
        response = client.post("/admin/registration", json=payload, headers=_auth_headers())
        assert response.status_code == 422


class TestAdminRegistrationService:
    def test_splits_full_name_and_inserts(self, mock_db):
        tables = setup_db_for_success(mock_db)

        result = create_admin_registration(
            "Jane Marie Doe", "jane@example.com", date(1990, 5, 15), Gender.female, "DE",
        )

        assert result["reference"] == "HP-2026-00001"
        assert result["ticket_number"] == "HP-2026-00001-M1"

        member_insert = tables["members"].insert.call_args[0][0]
        assert member_insert["first_name"] == "Jane"
        assert member_insert["last_name"] == "Marie Doe"
        assert member_insert["email"] == "jane@example.com"
        assert member_insert["gender"] == "female"

        reg_insert = tables["reg"].insert.call_args[0][0]
        assert reg_insert["country"] == "DE"
        assert reg_insert["karyakarta"] == "Admin"

    def test_single_word_full_name_uses_dash_last_name(self, mock_db):
        tables = setup_db_for_success(mock_db)

        create_admin_registration(
            "Madonna", "m@example.com", date(1958, 8, 16), Gender.female, "US",
        )

        member_insert = tables["members"].insert.call_args[0][0]
        assert member_insert["first_name"] == "Madonna"
        assert member_insert["last_name"] == "-"

    def test_quota_check_runs_before_insert(self, mock_db):
        """Admin path must enforce country quota."""
        tables = setup_db_for_success(mock_db)
        # Simulate a quota that's already full for DE.
        tables["quotas"].select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"max_members": 0}]
        )
        tables["reg"].select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        from app.core.exceptions import QuotaExceededError
        import pytest
        with pytest.raises(QuotaExceededError):
            create_admin_registration(
                "Jane Doe", "jane@example.com", date(1990, 5, 15), Gender.female, "DE",
            )
        # Insert never reached.
        tables["reg"].insert.assert_not_called()
