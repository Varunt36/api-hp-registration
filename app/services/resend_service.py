import logging
import re

from app.core.exceptions import MultipleRegistrationsError, RegistrationNotFoundError
from app.core.supabase import supabase
from app.services.email_service import send_combined_qr_email
from app.services.qr_service import generate_qr_image

logger = logging.getLogger(__name__)

# Ticket numbers look like "<reference>-M<index>", e.g. HP-2026-00042-M1.
_TICKET_INDEX_RE = re.compile(r"-M(\d+)$")


def _ticket_index(ticket_number: str) -> int:
    """Numeric index from a ticket number; large fallback keeps malformed tickets last."""
    m = _TICKET_INDEX_RE.search(ticket_number or "")
    return int(m.group(1)) if m else 1_000_000


def _lead_name(members: list[dict]) -> str:
    lead = members[0]
    return f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()


def resend_confirmation(entered_email: str, reference: str | None = None) -> dict:
    """Re-send the original confirmation email to a single registered, paid address.

    Returns {"sent": <int>, "reference": <str>}. Raises:
      - RegistrationNotFoundError (404): unknown email / not paid / reference mismatch
      - MultipleRegistrationsError (409): email maps to several registrations, no reference
    """
    normalized = entered_email.strip().lower()

    # 1) Find members with this email (case-insensitive). Filter in Python so the
    #    comparison matches the spec exactly regardless of DB collation.
    member_rows = (
        supabase.table("members").select("*").ilike("email", normalized).execute().data
        or []
    )
    matched = [m for m in member_rows if (m.get("email") or "").strip().lower() == normalized]
    if not matched:
        raise RegistrationNotFoundError()

    reg_ids = {m["registration_id"] for m in matched}

    # 2) Resolve the registration.
    registrations = (
        supabase.table("registrations").select("*").execute().data or []
    )
    regs_by_id = {r["id"]: r for r in registrations if r["id"] in reg_ids}

    if reference:
        target_reg = next(
            (r for r in regs_by_id.values() if r.get("reference") == reference), None
        )
        # The entered email must actually belong to this registration.
        if target_reg is None or not any(
            m["registration_id"] == target_reg["id"] for m in matched
        ):
            raise RegistrationNotFoundError()
    elif len(reg_ids) == 1:
        target_reg = regs_by_id[next(iter(reg_ids))]
    else:
        candidates = []
        for rid in reg_ids:
            reg = regs_by_id.get(rid)
            if not reg:
                continue
            reg_members = _ordered_members(
                [m for m in matched if m["registration_id"] == rid]
            )
            candidates.append({
                "reference": reg.get("reference"),
                "lead_name": _lead_name(reg_members) if reg_members else "",
                "member_count": reg.get("member_count"),
                "country": reg.get("country"),
            })
        raise MultipleRegistrationsError(candidates)

    registration_id = target_reg["id"]
    out_reference = target_reg.get("reference") or ""

    # 3) Confirm the registration is paid.
    payment_rows = (
        supabase.table("payments")
        .select("status")
        .eq("registration_id", registration_id)
        .execute()
        .data
        or []
    )
    if not any(p.get("status") == "paid" for p in payment_rows):
        raise RegistrationNotFoundError()

    # 4) Load ALL members of the registration, ordered by ticket index ascending.
    all_member_rows = (
        supabase.table("members")
        .select("*")
        .eq("registration_id", registration_id)
        .execute()
        .data
        or []
    )
    members = _ordered_members(all_member_rows)
    if not members:
        raise RegistrationNotFoundError()

    # 5) Regenerate QR bytes per member (same failure handling as process_qr_and_emails).
    all_qrs = []
    for m in members:
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

    # 6) Rebuild the original recipient tuples, then filter to the entered email only.
    primary_email = members[0].get("email")
    recipients = [(primary_email, all_qrs)] + [
        (q["email"], [q]) for q in all_qrs if q["email"] and q["email"] != primary_email
    ]
    targets = [
        (to, qrs)
        for (to, qrs) in recipients
        if to and to.strip().lower() == normalized
    ]

    # 7) Send to each target; count successes.
    sent = 0
    for to, qrs in targets:
        try:
            send_combined_qr_email(to, qrs, reference=out_reference)
            sent += 1
        except Exception:
            logger.exception(f"Resend failed for {out_reference}")

    logger.info(f"Resend confirmation: {sent} email(s) for {out_reference}")
    return {"sent": sent, "reference": out_reference}


def _ordered_members(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda m: _ticket_index(m.get("ticket_number", "")))
