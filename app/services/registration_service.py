from app.core.supabase import supabase
from app.models.registration import RegistrationInput
from app.services.email_service import send_registration_emails


def get_next_seq() -> int:
    """Get the next sequence number for registration reference."""
    result = supabase.table("registrations").select("seq").order("seq", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]["seq"] + 1
    return 1


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
    """Create a registration with all members, generate QR codes, and send emails."""
    # Check country quota before proceeding
    check_country_quota(data.country, len(data.members))

    seq = get_next_seq()
    reference = f"HP-2026-{seq:05d}"

    # Insert registration
    reg_result = supabase.table("registrations").insert({
        "seq": seq,
        "reference": reference,
        "country": data.country,
        "karyakarta": data.karyakarta,
        "member_count": len(data.members),
        "terms_accepted": True,
    }).execute()

    registration_id = reg_result.data[0]["id"]

    primary_email = data.members[0].email

    # Insert members and send emails
    for index, member in enumerate(data.members, start=1):
        ticket_number = f"{reference}-M{index}"

        member_data = {
            "registration_id": registration_id,
            "ticket_number": ticket_number,
            "first_name": member.first_name,
            "middle_name": member.middle_name,
            "last_name": member.last_name,
            "gender": member.gender,
            "dob": str(member.dob),
            "email": member.email,
            "phone": member.phone,
            "checked_in": False,
        }

        supabase.table("members").insert(member_data).execute()

        # Send 3 emails (to member's email, or primary email if none)
        send_registration_emails(member_data, ticket_number, primary_email)

    return {"reference": reference, "member_count": len(data.members)}
