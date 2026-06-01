import os

# Force safe, well-formed dummy credentials for the whole test session BEFORE the
# app (and its Supabase/Resend clients) is imported. These override any real values
# from a local .env so tests never touch real services. The Supabase client validates
# the key as a JWT-shaped string at construction time, hence the three dotted parts.
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "test.test.test"
os.environ["RESEND_API_KEY"] = "re_test_dummy_key"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
