"""Tests for POST /resend-confirmation (admin-only resend of the confirmation email).

All external calls are mocked: no real Supabase queries, no real Resend emails,
no QR network/file access beyond the deterministic in-process generator.
"""
import pytest

from app.routers import resend as resend_router
from app.services import resend_service


# --------------------------------------------------------------------------
# Fake Supabase query builder
# --------------------------------------------------------------------------
class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Honors eq/ilike/in_ filters so the tests actually exercise the
    server-side scoping (paid check, reference ownership, registration grouping)
    rather than passing regardless of whether those filters are applied."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def ilike(self, col, val):
        needle = str(val).strip().lower()
        self._rows = [r for r in self._rows if str(r.get(col) or "").strip().lower() == needle]
        return self

    def in_(self, col, vals):
        allowed = set(vals)
        self._rows = [r for r in self._rows if r.get(col) in allowed]
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return _Result(self._rows)


class FakeSupabase:
    """A stand-in for app.core.supabase.supabase.

    `tables` maps a table name to the list of rows .execute() should return.
    """

    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


class _FakeUser:
    def __init__(self, email="admin@example.com"):
        self.user = {"email": email}


class _FakeAuth:
    """Mimics supabase.auth.get_user(token): raises on a bad token."""

    def __init__(self, valid_token="good-token"):
        self._valid = valid_token

    def get_user(self, token):
        if token != self._valid:
            raise Exception("invalid JWT")
        return _FakeUser()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer good-token"}


@pytest.fixture
def patch_auth(monkeypatch):
    """Make the auth dependency accept 'good-token' and reject everything else."""
    monkeypatch.setattr(resend_router.supabase, "auth", _FakeAuth(), raising=False)
    return resend_router.supabase


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture every send_combined_qr_email call instead of hitting Resend."""
    calls = []

    def _capture(to_email, members_qr, reference=""):
        calls.append({"to": to_email, "members_qr": members_qr, "reference": reference})

    monkeypatch.setattr(resend_service, "send_combined_qr_email", _capture)
    return calls


def _patch_db(monkeypatch, tables):
    monkeypatch.setattr(resend_service, "supabase", FakeSupabase(tables))


# Canned rows -------------------------------------------------------------
LEAD = {
    "id": "m1", "registration_id": "r1", "ticket_number": "HP-2026-00042-M1",
    "first_name": "Asha", "last_name": "Patel", "gender": "female",
    "dob": "1990-01-01", "email": "lead@example.com", "phone": None, "checked_in": False,
}
SECOND = {
    "id": "m2", "registration_id": "r1", "ticket_number": "HP-2026-00042-M2",
    "first_name": "Ravi", "last_name": "Patel", "gender": "male",
    "dob": "1992-01-01", "email": "second@example.com", "phone": None, "checked_in": False,
}
REG = {
    "id": "r1", "seq": 42, "reference": "HP-2026-00042", "country": "DE",
    "karyakarta": "Karyakarta One", "member_count": 2, "terms_accepted": True,
}


# --------------------------------------------------------------------------
# 401 — auth
# --------------------------------------------------------------------------
def test_no_token_returns_401(client):
    resp = client.post("/resend-confirmation", json={"email": "lead@example.com"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_invalid_token_returns_401(client, patch_auth):
    resp = client.post(
        "/resend-confirmation",
        json={"email": "lead@example.com"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# --------------------------------------------------------------------------
# 404 — unknown email
# --------------------------------------------------------------------------
def test_unknown_email_returns_404(client, patch_auth, auth_headers, monkeypatch, sent_emails):
    _patch_db(monkeypatch, {"members": []})
    resp = client.post(
        "/resend-confirmation", json={"email": "nobody@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "REGISTRATION_NOT_FOUND"
    assert sent_emails == []


# --------------------------------------------------------------------------
# 404 — email only on a non-paid registration
# --------------------------------------------------------------------------
def test_unpaid_registration_returns_404(client, patch_auth, auth_headers, monkeypatch, sent_emails):
    _patch_db(monkeypatch, {
        "members": [LEAD, SECOND],
        "registrations": [REG],
        "payments": [{"registration_id": "r1", "status": "pending"}],
    })
    resp = client.post(
        "/resend-confirmation", json={"email": "lead@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "REGISTRATION_NOT_FOUND"
    assert sent_emails == []


# --------------------------------------------------------------------------
# 200 — lead member: combined all-members email
# --------------------------------------------------------------------------
def test_lead_member_gets_combined_email(client, patch_auth, auth_headers, monkeypatch, sent_emails):
    _patch_db(monkeypatch, {
        "members": [LEAD, SECOND],
        "registrations": [REG],
        "payments": [{"registration_id": "r1", "status": "paid"}],
    })
    resp = client.post(
        "/resend-confirmation", json={"email": "Lead@Example.com"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"sent": 1, "reference": "HP-2026-00042"}

    assert len(sent_emails) == 1
    call = sent_emails[0]
    assert call["to"] == "lead@example.com"
    assert call["reference"] == "HP-2026-00042"
    # Lead gets the combined list = all members, ordered M1, M2.
    tickets = [q["ticket_number"] for q in call["members_qr"]]
    assert tickets == ["HP-2026-00042-M1", "HP-2026-00042-M2"]
    assert all(q["qr_bytes"] for q in call["members_qr"])
    assert call["members_qr"][0]["member_name"] == "Asha Patel"


# --------------------------------------------------------------------------
# 200 — secondary member: only their own card
# --------------------------------------------------------------------------
def test_secondary_member_gets_only_their_card(client, patch_auth, auth_headers, monkeypatch, sent_emails):
    _patch_db(monkeypatch, {
        "members": [LEAD, SECOND],
        "registrations": [REG],
        "payments": [{"registration_id": "r1", "status": "paid"}],
    })
    resp = client.post(
        "/resend-confirmation", json={"email": "second@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"sent": 1, "reference": "HP-2026-00042"}

    assert len(sent_emails) == 1
    call = sent_emails[0]
    assert call["to"] == "second@example.com"
    tickets = [q["ticket_number"] for q in call["members_qr"]]
    assert tickets == ["HP-2026-00042-M2"]
    assert call["members_qr"][0]["member_name"] == "Ravi Patel"


# --------------------------------------------------------------------------
# 409 — email on multiple registrations, no reference
# --------------------------------------------------------------------------
def test_multiple_registrations_returns_409_with_candidates(
    client, patch_auth, auth_headers, monkeypatch, sent_emails
):
    lead_a = {**LEAD, "registration_id": "r1", "ticket_number": "HP-2026-00042-M1"}
    lead_b = {**LEAD, "id": "mX", "registration_id": "r2", "ticket_number": "HP-2026-00099-M1"}
    reg_b = {**REG, "id": "r2", "seq": 99, "reference": "HP-2026-00099",
             "country": "AT", "member_count": 1, "karyakarta": "Karyakarta Two"}

    # members ilike returns rows from both registrations
    members_rows = [lead_a, lead_b]

    # registrations lookup must resolve both r1 and r2; FakeQuery ignores eq filters
    # so return both and let the service group by registration_id.
    def fake_table(name):
        mapping = {
            "members": members_rows,
            "registrations": [REG, reg_b],
            "payments": [
                {"registration_id": "r1", "status": "paid"},
                {"registration_id": "r2", "status": "paid"},
            ],
        }
        return _FakeQuery(mapping.get(name, []))

    fake = FakeSupabase({})
    fake.table = fake_table
    monkeypatch.setattr(resend_service, "supabase", fake)

    resp = client.post(
        "/resend-confirmation", json={"email": "lead@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "MULTIPLE_REGISTRATIONS"
    candidates = body["candidates"]
    refs = sorted(c["reference"] for c in candidates)
    assert refs == ["HP-2026-00042", "HP-2026-00099"]
    for c in candidates:
        assert set(c.keys()) == {"reference", "lead_name", "member_count", "country"}
    assert sent_emails == []


# --------------------------------------------------------------------------
# 200 — disambiguation via reference picks the right registration
# --------------------------------------------------------------------------
def test_reference_disambiguates(client, patch_auth, auth_headers, monkeypatch, sent_emails):
    lead_a = {**LEAD, "registration_id": "r1", "ticket_number": "HP-2026-00042-M1"}
    lead_b = {**LEAD, "id": "mX", "registration_id": "r2", "ticket_number": "HP-2026-00099-M1"}
    reg_b = {**REG, "id": "r2", "seq": 99, "reference": "HP-2026-00099",
             "country": "AT", "member_count": 1}

    def fake_table(name):
        mapping = {
            "members": [lead_a, lead_b],
            "registrations": [REG, reg_b],
            "payments": [
                {"registration_id": "r1", "status": "paid"},
                {"registration_id": "r2", "status": "paid"},
            ],
        }
        return _FakeQuery(mapping.get(name, []))

    fake = FakeSupabase({})
    fake.table = fake_table
    monkeypatch.setattr(resend_service, "supabase", fake)

    resp = client.post(
        "/resend-confirmation",
        json={"email": "lead@example.com", "reference": "HP-2026-00099"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["reference"] == "HP-2026-00099"


# --------------------------------------------------------------------------
# 409 — candidate lead_name must be the registration's TRUE lead (M1), not the
# email-matched member (regression test: the entered email is a secondary member).
# --------------------------------------------------------------------------
def test_409_candidate_lead_name_is_true_lead(
    client, patch_auth, auth_headers, monkeypatch, sent_emails
):
    # "shared@example.com" is the M2 (secondary) member in BOTH registrations.
    m1_r1 = {**LEAD, "id": "a1", "registration_id": "r1", "ticket_number": "HP-2026-00042-M1",
             "first_name": "Asha", "last_name": "Patel", "email": "asha@example.com"}
    m2_r1 = {**LEAD, "id": "a2", "registration_id": "r1", "ticket_number": "HP-2026-00042-M2",
             "first_name": "Ravi", "last_name": "Patel", "email": "shared@example.com"}
    m1_r2 = {**LEAD, "id": "b1", "registration_id": "r2", "ticket_number": "HP-2026-00099-M1",
             "first_name": "Meera", "last_name": "Shah", "email": "meera@example.com"}
    m2_r2 = {**LEAD, "id": "b2", "registration_id": "r2", "ticket_number": "HP-2026-00099-M2",
             "first_name": "Bhavna", "last_name": "Shah", "email": "shared@example.com"}
    reg_b = {**REG, "id": "r2", "seq": 99, "reference": "HP-2026-00099", "country": "AT"}

    _patch_db(monkeypatch, {
        "members": [m1_r1, m2_r1, m1_r2, m2_r2],
        "registrations": [REG, reg_b],
        "payments": [
            {"registration_id": "r1", "status": "paid"},
            {"registration_id": "r2", "status": "paid"},
        ],
    })

    resp = client.post(
        "/resend-confirmation", json={"email": "shared@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 409
    candidates = resp.json()["error"]["candidates"]
    leads = {c["reference"]: c["lead_name"] for c in candidates}
    assert leads == {"HP-2026-00042": "Asha Patel", "HP-2026-00099": "Meera Shah"}
    assert sent_emails == []
