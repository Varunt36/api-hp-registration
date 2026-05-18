import logging
from datetime import date

from app.core.exceptions import QuotaExceededError, RegistrationInsertError
from app.core.supabase import supabase
from app.models.registration import Gender, MemberInput, RegistrationInput
from app.services.email_service import send_combined_qr_email
from app.services.qr_service import generate_qr_image

logger = logging.getLogger(__name__)


def check_country_quota(country: str, new_member_count: int) -> None:
    """Raise QuotaExceededError if adding members would exceed the country's limit."""
    quota = supabase.table("country_quotas").select("max_members").eq("country_code", country).execute()
    if not quota.data:
        return
    max_allowed = quota.data[0]["max_members"]

    paid = (
        supabase.table("registrations")
        .select("member_count, payments!inner(status)")
        .eq("country", country)
        .eq("payments.status", "paid")
        .execute()
    )
    current = sum(r["member_count"] for r in (paid.data or []))
    if current + new_member_count > max_allowed:
        raise QuotaExceededError(country)


def delete_registration(registration_id: str) -> None:
    """Best-effort rollback. A failure here leaves an orphan row but won't mask the original error."""
    try:
        supabase.table("registrations").delete().eq("id", registration_id).execute()
    except Exception:
        logger.exception(f"Rollback delete failed for registration {registration_id}")


def allocate_reference(data: RegistrationInput) -> dict:
    """Insert a registration row and stamp its HP-2026-NNNNN reference."""
    try:
        result = supabase.table("registrations").insert({
            "country": data.country,
            "karyakarta": data.karyakarta,
            "member_count": len(data.members),
            "terms_accepted": data.terms_accepted,
        }).execute()
    except Exception:
        logger.exception("Failed to allocate registration")
        raise RegistrationInsertError()

    registration_id = result.data[0]["id"]
    reference = f"HP-2026-{result.data[0]['seq']:05d}"
    supabase.table("registrations").update({"reference": reference}).eq("id", registration_id).execute()
    logger.info(f"Allocated {reference} ({data.country}, {len(data.members)} members)")
    return {"registration_id": registration_id, "reference": reference}


def insert_registration_members(registration_id: str, reference: str, data: RegistrationInput) -> dict:
    members_data = []
    for index, m in enumerate(data.members, start=1):
        row = {
            "registration_id": registration_id,
            "ticket_number": f"{reference}-M{index}",
            "first_name": m.first_name,
            "last_name": m.last_name,
            "gender": m.gender.value,
            "dob": str(m.dob),
            "email": m.email,
            "phone": m.phone,
            "checked_in": False,
        }
        try:
            supabase.table("members").insert(row).execute()
        except Exception:
            logger.exception(f"Member insert failed for {reference}, rolling back")
            delete_registration(registration_id)
            raise RegistrationInsertError(reference)
        members_data.append(row)

    logger.info(f"Inserted {len(members_data)} members for {reference}")
    return {
        "registration_id": registration_id,
        "reference": reference,
        "member_count": len(data.members),
        "members_data": members_data,
    }


def process_qr_and_emails(registration_id: str, members_data: list, primary_email: str, reference: str = "") -> int:
    """Send registration emails. Returns the number of recipients reached."""
    all_qrs = []
    for m in members_data:
        ticket = m["ticket_number"]
        try:
            qr_bytes = generate_qr_image(ticket)
        except Exception:
            logger.exception(f"QR generation failed for {ticket}")
            qr_bytes = None
        all_qrs.append({
            "member_name": f"{m['first_name']} {m['last_name']}",
            "ticket_number": ticket,
            "qr_bytes": qr_bytes,
            "email": m.get("email"),
        })

    recipients = [(primary_email, all_qrs)] + [
        (q["email"], [q]) for q in all_qrs if q["email"] and q["email"] != primary_email
    ]
    sent = 0
    for to, qrs in recipients:
        try:
            send_combined_qr_email(to, qrs, reference=reference)
            sent += 1
        except Exception:
            logger.exception(f"Email send failed for {reference}")
    return sent


def create_admin_registration(full_name: str, email: str, dob: date, gender: Gender, country: str) -> dict:
    """Admin-only path: insert one registration row + one member, no payment, no QR, no email.

    Quota note: admin rows don't have a payment, so they don't count toward future quota checks
    (which filter for paid rows). Admins can push past the cap — acceptable for comp/walk-in use.
    """
    parts = full_name.strip().split(maxsplit=1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else "-"

    check_country_quota(country, new_member_count=1)

    reg_input = RegistrationInput(
        country=country,
        karyakarta="Admin",
        terms_accepted=True,
        members=[MemberInput(first_name=first_name, last_name=last_name, gender=gender, dob=dob, email=email)],
    )
    allocation = allocate_reference(reg_input)
    insert_result = insert_registration_members(allocation["registration_id"], allocation["reference"], reg_input)

    logger.info(f"Admin registration created: {allocation['reference']}")
    return {
        "reference": allocation["reference"],
        "ticket_number": insert_result["members_data"][0]["ticket_number"],
    }
