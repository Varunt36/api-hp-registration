"""Tests for service-layer logic."""

import html
from unittest.mock import MagicMock, patch
from app.models.registration import RegistrationInput
from tests.conftest import VALID_PAYLOAD, setup_db_for_success


class TestAllocateReference:
    def test_allocates_registration_and_returns_reference(self, mock_db):
        tables = setup_db_for_success(mock_db)
        data = RegistrationInput(**VALID_PAYLOAD)

        from app.services.registration_service import allocate_reference
        result = allocate_reference(data)

        assert result["reference"] == "HP-2026-00001"
        assert result["registration_id"] == "test-reg-uuid"

        insert_call = tables["reg"].insert.call_args[0][0]
        assert "seq" not in insert_call
        assert insert_call["country"] == "DE"
        assert insert_call["terms_accepted"] is True


class TestInsertRegistrationMembers:
    def test_inserts_members(self, mock_db):
        setup_db_for_success(mock_db)
        data = RegistrationInput(**VALID_PAYLOAD)

        from app.services.registration_service import insert_registration_members
        result = insert_registration_members("test-reg-uuid", "HP-2026-00001", data)

        assert result["reference"] == "HP-2026-00001"
        assert result["member_count"] == 1
        assert result["registration_id"] == "test-reg-uuid"

    def test_member_data_mapping(self, mock_db):
        setup_db_for_success(mock_db)
        data = RegistrationInput(**VALID_PAYLOAD)

        from app.services.registration_service import insert_registration_members
        result = insert_registration_members("test-reg-uuid", "HP-2026-00001", data)

        member = result["members_data"][0]
        assert member["ticket_number"] == "HP-2026-00001-M1"
        assert member["first_name"] == "John"
        assert member["last_name"] == "Doe"
        assert member["gender"] == "male"
        assert member["dob"] == "1990-05-15"
        assert member["email"] == "john@example.com"
        assert member["phone"] == "+491234567890"
        assert member["checked_in"] is False

    def test_rollback_on_member_insert_failure(self, mock_db):
        tables = setup_db_for_success(mock_db)
        tables["members"].insert.return_value.execute.side_effect = Exception("DB error")

        data = RegistrationInput(**VALID_PAYLOAD)

        from app.core.exceptions import RegistrationInsertError
        from app.services.registration_service import insert_registration_members
        import pytest
        with pytest.raises(RegistrationInsertError, match="Registration failed"):
            insert_registration_members("test-reg-uuid", "HP-2026-00001", data)

        tables["reg"].delete.return_value.eq.assert_called_with("id", "test-reg-uuid")

    def test_country_quota_exceeded(self, mock_db):
        tables = setup_db_for_success(mock_db)
        # Quota: max 5 members for DE
        tables["quotas"].select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"max_members": 5}]
        )
        # Current paid count: 5 members already registered (quota full)
        # The quota check now uses a direct query: registrations.select(...).eq(...).eq(...)
        reg_chain = tables["reg"].select.return_value.eq.return_value.eq.return_value
        reg_chain.execute.return_value = MagicMock(
            data=[{"member_count": 5}]
        )

        data = RegistrationInput(**VALID_PAYLOAD)

        from app.core.exceptions import QuotaExceededError
        from app.services.registration_service import check_country_quota
        import pytest
        with pytest.raises(QuotaExceededError, match="all spots for"):
            check_country_quota(data.country, len(data.members))


class TestProcessQrAndEmails:
    """Primary email gets ALL QR codes. Other members with own email get only their own.

    Only one email is sent per recipient — the combined registration confirmation
    that includes QR codes, travel guide, and community links.
    """

    def test_3_members_2_unique_emails(self, mock_db):
        """M1(john@), M2(no email), M3(bob@)
        john@ gets: 1 combined email with M1+M2+M3 QR codes
        bob@  gets: 1 email with M3 QR code
        """
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
            {"ticket_number": "HP-2026-00001-M2", "first_name": "Jane", "last_name": "Doe", "email": None},
            {"ticket_number": "HP-2026-00001-M3", "first_name": "Bob", "last_name": "Smith", "email": "bob@example.com"},
        ]

        with patch("app.services.registration_service.generate_qr_image") as mock_qr, \
             patch("app.services.registration_service.send_combined_qr_email") as mock_qr_email:
            mock_qr.return_value = (b"fake-png", "https://storage.test/qr.png")

            from app.services.registration_service import process_qr_and_emails
            process_qr_and_emails("test-uuid", members_data, "john@example.com")

            # QR emails: 2 calls (primary + bob)
            assert mock_qr_email.call_count == 2

            # john@ (primary) gets ALL 3 members' QR codes
            john_call = mock_qr_email.call_args_list[0]
            assert john_call.args[0] == "john@example.com"
            assert len(john_call.args[1]) == 3
            tickets = [m["ticket_number"] for m in john_call.args[1]]
            assert "HP-2026-00001-M1" in tickets
            assert "HP-2026-00001-M2" in tickets
            assert "HP-2026-00001-M3" in tickets

            # bob@ gets only his own QR code
            bob_call = mock_qr_email.call_args_list[1]
            assert bob_call.args[0] == "bob@example.com"
            assert len(bob_call.args[1]) == 1
            assert bob_call.args[1][0]["ticket_number"] == "HP-2026-00001-M3"

    def test_3_members_all_no_email_except_primary(self, mock_db):
        """M1(john@), M2(no email), M3(no email)
        john@ gets: 1 email with M1+M2+M3 QR codes
        """
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
            {"ticket_number": "HP-2026-00001-M2", "first_name": "Jane", "last_name": "Doe", "email": None},
            {"ticket_number": "HP-2026-00001-M3", "first_name": "Kid", "last_name": "Doe", "email": None},
        ]

        with patch("app.services.registration_service.generate_qr_image") as mock_qr, \
             patch("app.services.registration_service.send_combined_qr_email") as mock_qr_email:
            mock_qr.return_value = (b"fake-png", "https://storage.test/qr.png")

            from app.services.registration_service import process_qr_and_emails
            process_qr_and_emails("test-uuid", members_data, "john@example.com")

            # Only 1 combined QR email with all 3 members
            assert mock_qr_email.call_count == 1
            assert mock_qr_email.call_args.args[0] == "john@example.com"
            assert len(mock_qr_email.call_args.args[1]) == 3

    def test_3_members_all_different_emails(self, mock_db):
        """M1(john@), M2(jane@), M3(bob@)
        john@ gets: ALL 3 QR codes
        jane@ gets: her QR code
        bob@  gets: his QR code
        """
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
            {"ticket_number": "HP-2026-00001-M2", "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
            {"ticket_number": "HP-2026-00001-M3", "first_name": "Bob", "last_name": "Smith", "email": "bob@example.com"},
        ]

        with patch("app.services.registration_service.generate_qr_image") as mock_qr, \
             patch("app.services.registration_service.send_combined_qr_email") as mock_qr_email:
            mock_qr.return_value = (b"fake-png", "https://storage.test/qr.png")

            from app.services.registration_service import process_qr_and_emails
            process_qr_and_emails("test-uuid", members_data, "john@example.com")

            # 3 QR email calls: primary (all 3) + jane (her own) + bob (his own)
            assert mock_qr_email.call_count == 3

            # primary gets all 3
            primary_call = mock_qr_email.call_args_list[0]
            assert primary_call.args[0] == "john@example.com"
            assert len(primary_call.args[1]) == 3

            # jane gets only hers
            jane_call = mock_qr_email.call_args_list[1]
            assert jane_call.args[0] == "jane@example.com"
            assert len(jane_call.args[1]) == 1
            assert jane_call.args[1][0]["ticket_number"] == "HP-2026-00001-M2"

            # bob gets only his
            bob_call = mock_qr_email.call_args_list[2]
            assert bob_call.args[0] == "bob@example.com"
            assert len(bob_call.args[1]) == 1
            assert bob_call.args[1][0]["ticket_number"] == "HP-2026-00001-M3"

    def test_single_member(self, mock_db):
        """1 member → 1 QR email total."""
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
        ]

        with patch("app.services.registration_service.generate_qr_image") as mock_qr, \
             patch("app.services.registration_service.send_combined_qr_email") as mock_qr_email:
            mock_qr.return_value = (b"fake-png", "https://storage.test/qr.png")

            from app.services.registration_service import process_qr_and_emails
            process_qr_and_emails("test-uuid", members_data, "john@example.com")

            assert mock_qr_email.call_count == 1
            assert len(mock_qr_email.call_args.args[1]) == 1

    def test_qr_failure_does_not_block_emails(self, mock_db):
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
        ]

        with patch("app.services.registration_service.generate_qr_image", side_effect=Exception("Storage down")), \
             patch("app.services.registration_service.send_combined_qr_email") as mock_qr_email:

            from app.services.registration_service import process_qr_and_emails
            process_qr_and_emails("test-uuid", members_data, "john@example.com")

            mock_qr_email.assert_called_once()
            assert mock_qr_email.call_args.args[1][0]["qr_bytes"] is None

    def test_email_failure_does_not_crash(self, mock_db):
        setup_db_for_success(mock_db)

        members_data = [
            {"ticket_number": "HP-2026-00001-M1", "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
        ]

        with patch("app.services.registration_service.generate_qr_image") as mock_qr, \
             patch("app.services.registration_service.send_combined_qr_email", side_effect=Exception("Resend down")):
            mock_qr.return_value = (b"fake-png", "https://storage.test/qr.png")

            from app.services.registration_service import process_qr_and_emails
            # Should not raise
            process_qr_and_emails("test-uuid", members_data, "john@example.com")


class TestCombinedQrEmail:
    def test_single_member_email(self):
        members_qr = [
            {"member_name": "John Doe", "ticket_number": "HP-2026-00001-M1", "qr_bytes": b"fake-png"},
        ]

        with patch("resend.Emails.send") as mock_send:
            from app.services.email_service import send_combined_qr_email
            send_combined_qr_email("john@example.com", members_qr, reference="HP-2026-00001")

            email = mock_send.call_args[0][0]
            assert email["to"] == ["john@example.com"]
            assert "John Doe" in email["subject"]
            assert "HariPrabodham Germany 2026" in email["subject"]
            assert len(email["attachments"]) == 1
            # Template should include the reference number
            assert "HP-2026-00001" in email["html"]

    def test_multi_member_combined_email(self):
        members_qr = [
            {"member_name": "John Doe", "ticket_number": "HP-2026-00001-M1", "qr_bytes": b"fake-1"},
            {"member_name": "Jane Doe", "ticket_number": "HP-2026-00001-M2", "qr_bytes": b"fake-2"},
            {"member_name": "Bob Smith", "ticket_number": "HP-2026-00001-M3", "qr_bytes": b"fake-3"},
        ]

        with patch("resend.Emails.send") as mock_send:
            from app.services.email_service import send_combined_qr_email
            send_combined_qr_email("john@example.com", members_qr, reference="HP-2026-00001")

            assert mock_send.call_count == 1
            email = mock_send.call_args[0][0]

            # Multi-member subject includes first member name + count
            assert "John Doe" in email["subject"]
            assert "+2" in email["subject"]
            assert "John Doe" in email["html"]
            assert "Jane Doe" in email["html"]
            assert "Bob Smith" in email["html"]

            assert len(email["attachments"]) == 3
            cids = {a["content_id"] for a in email["attachments"]}
            assert cids == {"qr-HP-2026-00001-M1", "qr-HP-2026-00001-M2", "qr-HP-2026-00001-M3"}

    def test_mixed_qr_bytes_some_missing(self):
        members_qr = [
            {"member_name": "John Doe", "ticket_number": "HP-2026-00001-M1", "qr_bytes": b"fake-png"},
            {"member_name": "Jane Doe", "ticket_number": "HP-2026-00001-M2", "qr_bytes": None},
        ]

        with patch("resend.Emails.send") as mock_send:
            from app.services.email_service import send_combined_qr_email
            send_combined_qr_email("john@example.com", members_qr)

            email = mock_send.call_args[0][0]
            assert len(email["attachments"]) == 1
            assert "follow-up email" in email["html"]

    def test_html_escape_prevents_xss(self):
        members_qr = [
            {"member_name": "<script>alert('xss')</script>", "ticket_number": "HP-2026-00001-M1", "qr_bytes": b"fake"},
        ]

        with patch("resend.Emails.send") as mock_send:
            from app.services.email_service import send_combined_qr_email
            send_combined_qr_email("test@example.com", members_qr)

            email_html = mock_send.call_args[0][0]["html"]
            assert "<script>" not in email_html


class TestCombinedEmailIncludesTravelAndCommunity:
    """The single combined email embeds travel CTA and community URLs."""

    def test_includes_travel_url_and_community_buttons(self):
        members_qr = [
            {"member_name": "John Doe", "ticket_number": "HP-2026-00001-M1", "qr_bytes": b"fake"},
        ]

        with patch("resend.Emails.send") as mock_send, \
             patch("app.services.email_service.settings") as mock_settings:
            mock_settings.resend_api_key = "x"
            mock_settings.resend_from_email = "test@example.com"
            mock_settings.frontend_url = "https://app.example.com"
            mock_settings.whatsapp_group_url = "https://chat.whatsapp.com/test"
            mock_settings.telegram_group_url = "https://t.me/test"

            from app.services.email_service import send_combined_qr_email
            send_combined_qr_email("john@example.com", members_qr, reference="HP-2026-00001")

            email_html = mock_send.call_args[0][0]["html"]
            assert "https://app.example.com/explore" in email_html
            assert "chat.whatsapp.com/test" in email_html
            assert "t.me/test" in email_html
            assert "Stay Connected" in email_html
            assert "Plan Your Trip" in email_html


class TestCompletePayment:
    def _setup(self, mock_db):
        """Build a mock-db harness that supports the full happy path of complete_payment."""
        from app.services.payment_service import complete_payment
        tables = setup_db_for_success(mock_db)
        intents = MagicMock()
        payments = MagicMock()
        original_router = mock_db.table.side_effect
        def router(name):
            if name == "payment_intents": return intents
            if name == "payments":        return payments
            return original_router(name)
        mock_db.table.side_effect = router

        # No prior payment for this transaction
        payments.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        # Intent found, pending
        intents.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "intent-1",
                "reference": "HP-2026-00001",
                "provider": "stripe",
                "payload": {
                    "country": "DE",
                    "karyakarta": "Lead",
                    "terms_accepted": True,
                    "members": [{
                        "first_name": "A", "last_name": "B",
                        "gender": "male", "dob": "1990-01-01",
                        "email": "a@b.com", "phone": None,
                    }],
                },
                "amount": 250.00, "currency": "EUR", "status": "pending",
            }]
        )
        # mark_consumed wins
        intents.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "intent-1"}]
        )
        # Insert payment row
        payments.insert.return_value.execute.return_value = MagicMock()
        # Update emails_sent flag
        payments.update.return_value.eq.return_value.execute.return_value = MagicMock()
        # Registration lookup by reference
        tables["reg"].select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "test-reg-uuid"}]
        )
        return complete_payment, tables, intents, payments

    def test_happy_path_inserts_payment_with_provider(self, mock_db):
        complete_payment, tables, intents, payments = self._setup(mock_db)

        complete_payment(
            intent_id="intent-1",
            transaction_id="txn-abc",
            provider="paypal",
            provider_order_id="po-123",
        )

        payment_row = payments.insert.call_args[0][0]
        assert payment_row["payment_method"] == "paypal"
        assert payment_row["transaction_id"] == "txn-abc"
        assert payment_row["provider_order_id"] == "po-123"
        assert payment_row["status"] == "paid"

    def test_duplicate_transaction_is_skipped(self, mock_db):
        complete_payment, tables, intents, payments = self._setup(mock_db)
        payments.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "already-there"}]
        )

        complete_payment(intent_id="intent-1", transaction_id="txn-abc", provider="paypal")

        payments.insert.assert_not_called()

    def test_intent_already_consumed_is_skipped(self, mock_db):
        complete_payment, tables, intents, payments = self._setup(mock_db)
        # mark_consumed returns no rows (someone else won the race)
        intents.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        complete_payment(intent_id="intent-1", transaction_id="txn-abc", provider="paypal")

        payments.insert.assert_not_called()
