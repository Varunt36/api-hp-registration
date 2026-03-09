import base64
import resend
from app.core.config import settings
from app.services.qr_service import generate_qr_bytes

resend.api_key = settings.resend_api_key


def send_registration_emails(member: dict, ticket_number: str, primary_email: str):
    """Send all 3 registration emails for a member.

    If the member has their own email, emails go to them directly.
    If not, their QR code is sent to the primary_email (first member's email).
    """
    qr_bytes = generate_qr_bytes(ticket_number)
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")

    member_name = f"{member['first_name']} {member['last_name']}"
    to_email = member.get("email") or primary_email
    is_proxy = not member.get("email")

    # Email 1: Registration confirmation with QR code
    subject = f"Registration Confirmed - {ticket_number}"
    if is_proxy:
        subject = f"Registration Confirmed for {member_name} - {ticket_number}"

    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": subject,
        "html": f"""
            <h2>Welcome {member_name}!</h2>
            <p>Your registration is confirmed.</p>
            <p><strong>Ticket Number:</strong> {ticket_number}</p>
            <p>Please show this QR code at the event for check-in:</p>
            <img src="cid:qrcode" alt="QR Code" width="200" height="200" />
        """,
        "attachments": [
            {
                "filename": f"qrcode-{ticket_number}.png",
                "content": qr_base64,
                "content_id": "qrcode",
            }
        ],
    })

    # Email 2: Travel guide (uses Resend template managed by admin)
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": "Travel Guide - YDS Germany 2026",
        "html": f"""
            <h2>Travel Guide</h2>
            <p>Dear {member_name},</p>
            <p>Please find the travel guide details below.</p>
            <!-- Admin will update this template in Resend dashboard -->
        """,
    })

    # Email 3: WhatsApp & Instagram QR codes (uses Resend template managed by admin)
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": "Stay Connected - WhatsApp & Instagram",
        "html": f"""
            <h2>Stay Connected</h2>
            <p>Dear {member_name},</p>
            <p>Join our WhatsApp group and follow us on Instagram!</p>
            <!-- Admin will update this template in Resend dashboard -->
        """,
    })
