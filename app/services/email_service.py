from typing import List, Dict
import base64
import html
import logging
import os
import resend
from app.core.config import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.resend_api_key


def _mask_email(email: str) -> str:
    """Mask email for logging: john@example.com → j***@example.com (GDPR compliance)."""
    local, domain = email.split("@")
    return f"{local[0]}***@{domain}"

# ── Template loading ──────────────────────────────────────────
# Templates are loaded once at module level (not on every email send).
# They live in app/templates/ as plain HTML with {{PLACEHOLDER}} markers.
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _load_template(filename: str) -> str:
    filepath = os.path.join(_TEMPLATE_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


_REGISTRATION_TEMPLATE = _load_template("registration_email.html")
_MEMBER_CARD_TEMPLATE = _load_template("member_card.html")


def _build_member_card(member_name: str, ticket_number: str, qr_html: str) -> str:
    """Build a single member card HTML from the template."""
    card = _MEMBER_CARD_TEMPLATE
    card = card.replace("{{MEMBER_NAME}}", member_name)
    card = card.replace("{{TICKET_NUMBER}}", ticket_number)
    card = card.replace("{{QR_IMAGE}}", qr_html)
    return card


def send_combined_qr_email(
    to_email: str,
    members_qr: List[Dict],
    reference: str = "",
):
    """Send a single styled email containing QR codes for one or more members.

    Used in two ways:
      1. Primary member: receives ALL members' QR codes in one email
      2. Other members: receive only their own QR code (list of 1)

    Each QR image is embedded inline using CID (Content-ID) references,
    so the image displays directly in the email body (not just as attachment).

    Args:
        to_email: recipient email address
        members_qr: list of dicts, each with:
            - member_name: display name (will be HTML-escaped)
            - ticket_number: e.g. "HP-2026-00042-M1"
            - qr_bytes: PNG bytes (or None if QR generation failed)
        reference: registration reference e.g. "HP-2026-00042"
    """
    member_cards = []
    attachments = []

    for item in members_qr:
        # HTML-escape names to prevent XSS injection in email
        member_name = html.escape(item["member_name"])
        ticket_number = html.escape(item["ticket_number"])
        qr_bytes = item["qr_bytes"]

        if qr_bytes:
            qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
            # CID (Content-ID) links the attachment to the inline <img> tag.
            # Each member needs a unique CID so multiple QR images display correctly.
            cid = f"qr-{ticket_number}"
            qr_html = (
                f'<img src="cid:{cid}" alt="QR Code for {ticket_number}" '
                f'width="200" height="200" style="display: block; margin: 0 auto;" />'
            )
            attachments.append({
                "filename": f"qrcode-{ticket_number}.png",
                "content": qr_base64,
                "content_id": cid,
            })
        else:
            # QR generation failed — show fallback text instead of broken image
            qr_html = (
                '<p style="margin: 0; color: #999; font-size: 13px; font-style: italic;">'
                'QR code will be sent in a follow-up email.</p>'
            )

        member_cards.append(_build_member_card(member_name, ticket_number, qr_html))

    members_section_html = "\n".join(member_cards)

    # Build heading: "Your Ticket" (1 member) or "Your Tickets (3 Members)" (multiple)
    if len(members_qr) == 1:
        members_heading = "Your Ticket"
    else:
        members_heading = f"Your Tickets ({len(members_qr)} Members)"

    # Build the full email HTML from template
    email_html = _REGISTRATION_TEMPLATE
    email_html = email_html.replace("{{BANNER_URL}}", settings.email_banner_url)
    email_html = email_html.replace("{{LOGO_URL}}", settings.email_logo_url)
    email_html = email_html.replace("{{REFERENCE}}", html.escape(reference))
    email_html = email_html.replace("{{MEMBERS_HEADING}}", members_heading)
    email_html = email_html.replace("{{MEMBERS_SECTION}}", members_section_html)

    # Subject: "YDS Germany 2026 Registration Confirmation - Member Name"
    # For multi-member, use first member's name (primary registrant)
    first_member_name = html.escape(members_qr[0]["member_name"])
    if len(members_qr) == 1:
        subject = f"YDS Germany 2026 Registration Confirmation - {first_member_name}"
    else:
        subject = f"YDS Germany 2026 Registration Confirmation - {first_member_name} (+{len(members_qr) - 1})"

    email_data = {
        "from": settings.resend_from_email,
        "to": [to_email],

        "subject": subject,
        "html": email_html,
    }

    if attachments:
        email_data["attachments"] = attachments

    resend.Emails.send(email_data)
    logger.info(f"Sent registration email ({len(members_qr)} members) to {_mask_email(to_email)}")


def send_info_emails(to_email: str):
    """Send Travel Guide + Social media emails. Called once per unique email address.

    These emails have the same content for everyone (not member-specific),
    so they are deduplicated — each unique email gets them exactly once.
    Template content is placeholder; admin updates it in Resend dashboard.
    """

    # Email 2 of 3: Travel guide
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": [to_email],

        "subject": "Travel Guide - YDS Germany 2026",
        "html": """
            <h2>Travel Guide</h2>
            <p>Please find the travel guide details below.</p>
            <!-- Admin will update this template in Resend dashboard -->
        """,
    })

    # Email 3 of 3: Social media group links (WhatsApp, Instagram, YouTube, Telegram)
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": [to_email],

        "subject": "Stay Connected - WhatsApp, Instagram & Telegram",
        "html": """
            <h2>Stay Connected</h2>
            <p>Join our WhatsApp & Telegram group and follow us on Instagram & Youtube!</p>
            <!-- Admin will update this template with group links/QR codes in Resend dashboard -->
        """,
    })

    logger.info(f"Sent info emails (Travel + Social) to {_mask_email(to_email)}")
