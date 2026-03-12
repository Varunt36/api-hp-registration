import os
from unittest.mock import MagicMock, patch

# 1. Set test environment BEFORE any app imports
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "test-service-key"
os.environ["RESEND_API_KEY"] = "re_test_key"
os.environ["RESEND_FROM_EMAIL"] = "test@example.com"
os.environ["FRONTEND_URL"] = "http://localhost:5173"

# 2. Mock supabase client creation BEFORE app modules import it
_mock_supabase = MagicMock()
patch("supabase.create_client", return_value=_mock_supabase).start()

# 3. Mock resend email sending to prevent real API calls
patch("resend.Emails.send", return_value={"id": "mock-email-id"}).start()

# 4. Now safe to import app
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.rate_limiter import _request_log


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all mock and rate limiter state before each test."""
    _mock_supabase.reset_mock()
    _request_log.clear()
    yield


@pytest.fixture
def mock_db():
    """Provide the mock supabase client."""
    return _mock_supabase


@pytest.fixture
def client():
    """Provide a test HTTP client."""
    return TestClient(app)


# --- Helpers ---

VALID_PAYLOAD = {
    "country": "DE",
    "karyakarta": "John Doe",
    "terms_accepted": True,
    "members": [
        {
            "first_name": "John",
            "last_name": "Doe",
            "gender": "male",
            "dob": "1990-05-15",
            "email": "john@example.com",
            "phone": "+491234567890",
        }
    ],
}

VALID_PAYLOAD_MULTI = {
    "country": "DE",
    "karyakarta": "John Doe",
    "terms_accepted": True,
    "members": [
        {
            "first_name": "John",
            "last_name": "Doe",
            "gender": "male",
            "dob": "1990-05-15",
            "email": "john@example.com",
        },
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "gender": "female",
            "dob": "1992-08-20",
        },
    ],
}


def setup_db_for_success(mock_db):
    """Configure mock DB for a successful registration flow."""
    reg_table = MagicMock()
    members_table = MagicMock()
    quotas_table = MagicMock()

    def table_router(name):
        return {
            "registrations": reg_table,
            "members": members_table,
            "country_quotas": quotas_table,
        }.get(name, MagicMock())

    mock_db.table.side_effect = table_router

    # No quota set
    quotas_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    # Registration insert returns id + seq
    reg_table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-reg-uuid", "seq": 1}]
    )

    # Update reference
    reg_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # Member insert
    members_table.insert.return_value.execute.return_value = MagicMock()

    # Member update (qr_url)
    members_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # Delete (for rollback)
    reg_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()

    # Storage upload + public URL
    mock_db.storage.from_.return_value.upload.return_value = None
    mock_db.storage.from_.return_value.get_public_url.return_value = "https://storage.test/qr.png"

    return {"reg": reg_table, "members": members_table, "quotas": quotas_table}
