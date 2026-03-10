from typing import Optional, List, Dict
import base64
import html
import logging
import resend
from app.core.config import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.resend_api_key


def send_combined_qr_email(to_email: str, members_qr: List[Dict]):
    """Send a single email with QR codes for all members grouped to this email.

    members_qr: list of dicts with keys: member_name, ticket_number, qr_bytes
    """
    member_sections = []
    attachments = []

    for item in members_qr:
        member_name = html.escape(item["member_name"])
        ticket_number = item["ticket_number"]
        qr_bytes = item["qr_bytes"]

        if qr_bytes:
            qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
            cid = f"qr-{ticket_number}"
            qr_html = f'<img src="cid:{cid}" alt="QR Code" width="200" height="200" />'
            attachments.append({
                "filename": f"qrcode-{ticket_number}.png",
                "content": qr_base64,
                "content_id": cid,
            })
        else:
            qr_html = "<p><em>QR code will be sent in a follow-up email.</em></p>"

        member_sections.append(f"""
            <div style="margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 15px;">
                <h3>{member_name}</h3>
                <p><strong>Ticket:</strong> {ticket_number}</p>
                {qr_html}
            </div>
        """)

    members_html = "".join(member_sections)

    if len(members_qr) == 1:
        subject = f"Registration Confirmed - {members_qr[0]['ticket_number']}"
    else:
        subject = f"Registration Confirmed - {len(members_qr)} Members"

    email_data = {
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": subject,
        "html": f"""
            <h2>Registration Confirmed!</h2>
            <p>Please show the QR code(s) at the event for check-in:</p>
            {members_html}
        """,
    }

    if attachments:
        email_data["attachments"] = attachments

    resend.Emails.send(email_data)
    logger.info(f"Sent combined QR email ({len(members_qr)} members) to {to_email}")


def send_info_emails(to_email: str):
    """Send Travel Guide + WhatsApp/Instagram emails. Called once per unique email."""

    # Travel guide
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": "Travel Guide - YDS Germany 2026",
        "html": """
            <h2>Travel Guide</h2>
            <p>Please find the travel guide details below.</p>
            <!-- Admin will update this template in Resend dashboard -->
        """,
    })

    # WhatsApp, Instagram & Telegram
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": to_email,
        "subject": "Stay Connected - WhatsApp, Instagram & Telegram",
        "html": """
            <h2>Stay Connected</h2>
            <p>Join our WhatsApp & Telegram group and follow us on Instagram & Youtube!</p>
            <!-- Admin will update this template with group links/QR codes in Resend dashboard -->
        """,
    })

    logger.info(f"Sent info emails (Travel + Social) to {to_email}")
