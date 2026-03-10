import logging
from collections import defaultdict
from app.core.supabase import supabase
from app.models.registration import RegistrationInput
from app.services.email_service import send_combined_qr_email, send_info_emails
from app.services.qr_service import generate_qr_image

logger = logging.getLogger(__name__)


def check_country_quota(country: str, new_member_count: int):
    """Check if adding new members would exceed the country's quota."""
    quota_result = supabase.table("country_quotas").select("max_members").eq("country_code", country).execute()

    if not quota_result.data:
        return  # no quota = unlimited

    max_allowed = quota_result.data[0]["max_members"]

    # count members from paid registrations for this country
    result = supabase.rpc("get_paid_member_count", {"p_country": country}).execute()
    current_count = result.data if result.data else 0

    remaining = max_allowed - current_count
    if new_member_count > remaining:
        raise ValueError(
            f"Registration limit reached for country {country}. Only {remaining} spots remain."
        )


def create_registration(data: RegistrationInput) -> dict:
    """Create registration + members in DB. Returns data for background QR/email processing."""
    check_country_quota(data.country, len(data.members))

    #1: Let DB auto-generate seq via BIGSERIAL (no race condition)
    reg_result = supabase.table("registrations").insert({
        "country": data.country,
        "karyakarta": data.karyakarta,
        "member_count": len(data.members),
        "terms_accepted": data.terms_accepted,  # Fix #6: from FE payload
    }).execute()

    registration_id = reg_result.data[0]["id"]
    seq = reg_result.data[0]["seq"]
    reference = f"HP-2026-{seq:05d}"

    # Update with generated reference
    supabase.table("registrations").update({"reference": reference}).eq("id", registration_id).execute()

    logger.info(f"Registration created: {reference} for country {data.country}")

    # Insert members
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
            #8: rollback — delete registration (CASCADE deletes inserted members)
            logger.exception(f"Failed to insert member {index} for {reference}, rolling back")
            supabase.table("registrations").delete().eq("id", registration_id).execute()
            raise ValueError("Registration failed. Please try again.")

    logger.info(f"Inserted {len(members_data)} members for {reference}")

    return {
        "registration_id": registration_id,
        "reference": reference,
        "member_count": len(data.members),
        "members_data": members_data,
    }


def process_qr_and_emails(registration_id: str, members_data: list, primary_email: str):
    """Background task: generate QR codes, upload to storage, update DB, send emails.

    Email logic:
      - Primary email (main member) gets ALL members' QR codes in one email.
      - Other members with their own email get only their own QR code.
      - Travel Guide + Social emails sent once per unique email.

    Example (3 members: M1=john@, M2=no email, M3=bob@):
      john@ receives: 1 email with M1+M2+M3 QR codes, Travel Guide, Social = 3 emails
      bob@  receives: 1 email with M3 QR code, Travel Guide, Social        = 3 emails
      Total: 6 emails
    """
    # Step 1: Generate QR for all members
    all_members_qr = []
    unique_emails = set()

    for member_data in members_data:
        ticket_number = member_data["ticket_number"]

        qr_bytes = None
        try:
            qr_bytes, qr_url = generate_qr_image(ticket_number)
            supabase.table("members").update({"qr_url": qr_url}).eq("ticket_number", ticket_number).execute()
        except Exception:
            logger.exception(f"QR generation/upload failed for {ticket_number}")

        member_name = f"{member_data['first_name']} {member_data['last_name']}"
        member_email = member_data.get("email")

        all_members_qr.append({
            "member_name": member_name,
            "ticket_number": ticket_number,
            "qr_bytes": qr_bytes,
            "email": member_email,
        })

        unique_emails.add(member_email or primary_email)

    # Step 2: Primary email gets ALL members' QR codes in one email
    try:
        send_combined_qr_email(primary_email, all_members_qr)
    except Exception:
        logger.exception(f"Combined QR email failed for {primary_email}")

    # Step 3: Other members with their own email get only their own QR code
    for item in all_members_qr:
        if item["email"] and item["email"] != primary_email:
            try:
                send_combined_qr_email(item["email"], [item])
            except Exception:
                logger.exception(f"QR email failed for {item['email']}")

    # Step 4: Send info emails once per unique email
    for email_address in unique_emails:
        try:
            send_info_emails(email_address)
        except Exception:
            logger.exception(f"Info emails failed for {email_address}")
