"""Tests for Pydantic model validation (Fix #3: input validation)."""

import pytest
from pydantic import ValidationError
from app.models.registration import MemberInput, RegistrationInput


# --- MemberInput tests ---


class TestMemberValidation:
    def test_valid_member(self):
        member = MemberInput(
            first_name="John",
            last_name="Doe",
            gender="male",
            dob="1990-05-15",
            email="john@example.com",
            phone="+491234567890",
        )
        assert member.first_name == "John"
        assert member.gender.value == "male"

    def test_valid_member_minimal(self):
        """Member without optional fields."""
        member = MemberInput(
            first_name="Jane",
            last_name="Doe",
            gender="female",
            dob="1992-08-20",
        )
        assert member.email is None
        assert member.phone is None

    def test_invalid_gender_rejected(self):
        with pytest.raises(ValidationError, match="gender"):
            MemberInput(
                first_name="John",
                last_name="Doe",
                gender="other",
                dob="1990-05-15",
            )

    def test_invalid_email_format_rejected(self):
        with pytest.raises(ValidationError, match="email"):
            MemberInput(
                first_name="John",
                last_name="Doe",
                gender="male",
                dob="1990-05-15",
                email="not-an-email",
            )

    def test_future_dob_rejected(self):
        with pytest.raises(ValidationError, match="future"):
            MemberInput(
                first_name="John",
                last_name="Doe",
                gender="male",
                dob="2099-01-01",
            )

    def test_ancient_dob_rejected(self):
        with pytest.raises(ValidationError, match="not valid"):
            MemberInput(
                first_name="John",
                last_name="Doe",
                gender="male",
                dob="1899-01-01",
            )

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError, match="1-100"):
            MemberInput(
                first_name="A" * 101,
                last_name="Doe",
                gender="male",
                dob="1990-05-15",
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError, match="1-100"):
            MemberInput(
                first_name="   ",
                last_name="Doe",
                gender="male",
                dob="1990-05-15",
            )

    def test_phone_too_long_rejected(self):
        with pytest.raises(ValidationError, match="Phone"):
            MemberInput(
                first_name="John",
                last_name="Doe",
                gender="male",
                dob="1990-05-15",
                phone="+" + "1" * 25,
            )

    def test_name_gets_trimmed(self):
        member = MemberInput(
            first_name="  John  ",
            last_name="  Doe  ",
            gender="male",
            dob="1990-05-15",
        )
        assert member.first_name == "John"
        assert member.last_name == "Doe"


# --- RegistrationInput tests ---


class TestRegistrationValidation:
    def _base_payload(self, **overrides):
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
                    "email": "john@example.com",
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_valid_registration(self):
        reg = RegistrationInput(**self._base_payload())
        assert reg.country == "DE"
        assert len(reg.members) == 1

    def test_invalid_country_rejected(self):
        with pytest.raises(ValidationError, match="Country must be one of"):
            RegistrationInput(**self._base_payload(country="ZZ"))

    def test_country_gets_uppercased(self):
        reg = RegistrationInput(**self._base_payload(country="de"))
        assert reg.country == "DE"

    def test_terms_false_rejected(self):
        with pytest.raises(ValidationError, match="Terms must be accepted"):
            RegistrationInput(**self._base_payload(terms_accepted=False))

    def test_no_members_rejected(self):
        with pytest.raises(ValidationError, match="At least one member"):
            RegistrationInput(**self._base_payload(members=[]))

    def test_too_many_members_rejected(self):
        member = {
            "first_name": "Test",
            "last_name": "User",
            "gender": "male",
            "dob": "1990-01-01",
            "email": "test@example.com",
        }
        members = [member] * 5  # MAX is 4
        with pytest.raises(ValidationError, match="Maximum 4"):
            RegistrationInput(**self._base_payload(members=members))

    def test_first_member_without_email_rejected(self):
        member_no_email = {
            "first_name": "John",
            "last_name": "Doe",
            "gender": "male",
            "dob": "1990-05-15",
        }
        with pytest.raises(ValidationError, match="First member must have an email"):
            RegistrationInput(**self._base_payload(members=[member_no_email]))

    def test_karyakarta_too_long_rejected(self):
        with pytest.raises(ValidationError, match="1-200"):
            RegistrationInput(**self._base_payload(karyakarta="A" * 201))

    def test_all_allowed_countries(self):
        for code in ["DE", "AT", "CH", "GB", "US", "IN", "NZ"]:
            reg = RegistrationInput(**self._base_payload(country=code))
            assert reg.country == code
