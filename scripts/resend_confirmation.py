"""Manually re-send a registration confirmation email.

Use when a registration exists in the DB but the confirmation email was never
sent (e.g. the payment-row insert failed for a €0 / 100%-coupon order, so
complete_payment returned before reaching the email step).

It looks up the registration by its HP-2026-NNNNN reference, prints the members
it would email, and only sends after you type "yes" at the prompt.

Run from the project root (so `app` is importable), with the same env/.env the
API uses:

    python -m scripts.resend_confirmation HP-2026-00147

If you omit the reference it will ask for one.
"""
from __future__ import annotations

import sys

from app.core.supabase import supabase
from app.services.registration_service import process_qr_and_emails


def _fetch_registration(reference: str) -> dict | None:
    res = (
        supabase.table("registrations")
        .select("id, reference, country, member_count, created_at")
        .eq("reference", reference)
        .execute()
    )
    return res.data[0] if res.data else None


def _fetch_members(registration_id: str) -> list[dict]:
    res = (
        supabase.table("members")
        .select("ticket_number, first_name, last_name, email, phone")
        .eq("registration_id", registration_id)
        .order("ticket_number")
        .execute()
    )
    return res.data or []


def _payment_row(registration_id: str) -> dict | None:
    res = (
        supabase.table("payments")
        .select("status, amount, currency, transaction_id")
        .eq("registration_id", registration_id)
        .execute()
    )
    return res.data[0] if res.data else None


def main() -> int:
    reference = sys.argv[1].strip() if len(sys.argv) > 1 else input("Registration reference (e.g. HP-2026-00147): ").strip()
    if not reference:
        print("No reference provided. Aborting.")
        return 1

    reg = _fetch_registration(reference)
    if reg is None:
        print(f"❌ No registration found for '{reference}'. Nothing to do.")
        return 1

    members = _fetch_members(reg["id"])
    if not members:
        print(f"❌ Registration {reference} exists but has no members. Aborting (cannot email).")
        return 1

    payment = _payment_row(reg["id"])

    print()
    print(f"✅ Found registration {reference}")
    print(f"   country={reg['country']}  member_count={reg['member_count']}  created_at={reg['created_at']}")
    if payment is None:
        print("   payment row: NONE (no payment recorded for this registration)")
    else:
        print(f"   payment row: status={payment['status']} amount={payment['amount']} {payment['currency']} txn={payment['transaction_id']}")
    print()
    print(f"   Members ({len(members)}):")
    for i, m in enumerate(members, start=1):
        print(f"     {i}. {m['first_name']} {m['last_name']:<20} ticket={m['ticket_number']:<22} email={m.get('email')}")

    primary_email = members[0].get("email")
    if not primary_email:
        print("\n❌ First member has no email — cannot determine primary recipient. Aborting.")
        return 1

    print()
    print(f"   The confirmation (with QR codes) will be sent to the primary recipient: {primary_email}")
    print(f"   Plus any member whose email differs from the primary will also get their own QR.")
    print()

    answer = input('Send the confirmation email now? Type "yes" to proceed: ').strip().lower()
    if answer != "yes":
        print("Aborted — no email sent.")
        return 0

    sent = process_qr_and_emails(reg["id"], members, primary_email, reference)
    if sent > 0:
        print(f"\n✅ Done — emails sent to {sent} recipient(s) for {reference}.")
        if payment is not None:
            supabase.table("payments").update({"emails_sent": True}).eq("registration_id", reg["id"]).execute()
        return 0

    print(f"\n❌ process_qr_and_emails reported 0 sends for {reference}. Check the logs above for the Resend error.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
