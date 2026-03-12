import logging

from app.core.exceptions import DuplicateMemberError, QuotaExceededError, RegistrationInsertError
from app.core.supabase import supabase
from app.models.registration import RegistrationInput
from app.services.email_service import send_combined_qr_email, send_travel_email, send_social_email
from app.services.qr_service import generate_qr_image

logger = logging.getLogger(__name__)


def check_country_quota(country: str, new_member_count: int):
    """Raise QuotaExceededError if adding members would exceed the country's limit."""
    quota_result = supabase.table("country_quotas").select("max_members").eq("country_code", country).execute()
    if not quota_result.data:
        return

    max_allowed = quota_result.data[0]["max_members"]
    result = (
        supabase.table("registrations")
        .select("member_count, payments!inner(status)")
        .eq("country", country)
        .eq("payments.status", "paid")
        .execute()
    )
    current_count = sum(row["member_count"] for row in result.data) if result.data else 0

    if current_count + new_member_count > max_allowed:
        raise QuotaExceededError(country)


def check_duplicate_member(email: str):
    """Raise DuplicateMemberError if this email already has a paid registration."""
    members = supabase.table("members").select("registration_id").eq("email", email).execute()
    if not members.data:
        return

    reg_ids = [m["registration_id"] for m in members.data]
    payments = (
        supabase.table("payments")
        .select("id")
        .in_("registration_id", reg_ids)
        .eq("status", "paid")
        .limit(1)
        .execute()
    )
    if payments.data:
        raise DuplicateMemberError(email)


def create_registration(data: RegistrationInput) -> dict:
    """Insert registration + members into DB. Returns data for QR/email processing."""
    if data.members[0].email:
        check_duplicate_member(data.members[0].email)

    try:
        reg_result = supabase.table("registrations").insert({
            "country": data.country,
            "karyakarta": data.karyakarta,
            "member_count": len(data.members),
            "terms_accepted": data.terms_accepted,
        }).execute()
    except Exception:
        logger.exception("Failed to insert registration row")
        raise RegistrationInsertError()

    registration_id = reg_result.data[0]["id"]
    seq = reg_result.data[0]["seq"]
    reference = f"HP-2026-{seq:05d}"

    supabase.table("registrations").update({"reference": reference}).eq("id", registration_id).execute()
    logger.info(f"Registration created: {reference} ({data.country}, {len(data.members)} members)")

    members_data = []
    for index, member in enumerate(data.members, start=1):
        ticket_number = f"{reference}-M{index}"
        member_data = {
            "registration_id": registration_id,
            "ticket_number": ticket_number,
            "first_name": member.first_name,
            "middle_name": member.middle_name,
            "last_name": member.last_name,
            "gender": member.gender.value,
            "dob": str(member.dob),
            "email": member.email,
            "phone": member.phone,
            "checked_in": False,
        }
        try:
            supabase.table("members").insert(member_data).execute()
            members_data.append(member_data)
        except Exception:
            logger.exception(f"Failed to insert member {index} for {reference}, rolling back")
            supabase.table("registrations").delete().eq("id", registration_id).execute()
            raise RegistrationInsertError(reference)

    logger.info(f"Inserted {len(members_data)} members for {reference}")
    return {
        "registration_id": registration_id,
        "reference": reference,
        "member_count": len(data.members),
        "members_data": members_data,
    }


def process_qr_and_emails(registration_id: str, members_data: list, primary_email: str, reference: str = ""):
    """Generate QR codes and send all emails (registration, travel, social)."""
    all_members_qr = []
    unique_emails = set()

    for member_data in members_data:
        ticket_number = member_data["ticket_number"]
        qr_bytes = None
        try:
            qr_bytes = generate_qr_image(ticket_number)
        except Exception:
            logger.exception(f"QR generation failed for {ticket_number}")

        member_name = f"{member_data['first_name']} {member_data['last_name']}"
        member_email = member_data.get("email")

        all_members_qr.append({
            "member_name": member_name,
            "ticket_number": ticket_number,
            "qr_bytes": qr_bytes,
            "email": member_email,
        })
        unique_emails.add(member_email or primary_email)

    # Registration email with QR codes to primary contact
    try:
        send_combined_qr_email(primary_email, all_members_qr, reference=reference)
    except Exception:
        logger.exception(f"Registration email failed for primary contact ({reference})")

    # Individual QR email to other members who have their own email
    for item in all_members_qr:
        if item["email"] and item["email"] != primary_email:
            try:
                send_combined_qr_email(item["email"], [item], reference=reference)
            except Exception:
                logger.exception(f"Registration email failed for member ({reference})")

    # Travel guide + social links — once per unique email
    for email_address in unique_emails:
        try:
            send_travel_email(email_address)
        except Exception:
            logger.exception(f"Travel email failed ({reference})")

    for email_address in unique_emails:
        try:
            send_social_email(email_address)
        except Exception:
            logger.exception(f"Social email failed ({reference})")
