import base64
import html
import logging
import os
from typing import List, Dict

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.resend_api_key

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _load_template(filename: str) -> str:
    with open(os.path.join(_TEMPLATE_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


_REGISTRATION_TEMPLATE = _load_template("registration_email.html")
_MEMBER_CARD_TEMPLATE = _load_template("member_card.html")
_SOCIAL_TEMPLATE = _load_template("social_email.html")
_SOCIAL_CARD_TEMPLATE = _load_template("social_card.html")


def _mask_email(email: str) -> str:
    local, domain = email.split("@")
    return f"{local[0]}***@{domain}"


def _sanitize_email(email: str) -> str:
    if any(c in email for c in ("\r", "\n", "\0")):
        raise ValueError("Invalid email address")
    return email.strip()


def _sanitize_text(text: str) -> str:
    return text.replace("\r", "").replace("\n", "").replace("\0", "").strip()


def _build_member_card(member_name: str, ticket_number: str, qr_html: str) -> str:
    card = _MEMBER_CARD_TEMPLATE
    card = card.replace("{{MEMBER_NAME}}", member_name)
    card = card.replace("{{TICKET_NUMBER}}", ticket_number)
    card = card.replace("{{QR_IMAGE}}", qr_html)
    return card


def _build_social_card(
    platform_name: str,
    platform_color: str,
    platform_url: str,
    description: str,
    button_text: str,
    qr_image_url: str = "",
) -> str:
    qr_html = ""
    if qr_image_url:
        qr_html = (
            f'<img src="{html.escape(qr_image_url)}" alt="{html.escape(platform_name)} QR" '
            f'width="180" height="180" style="display: block; margin: 0 auto;" />'
        )

    card = _SOCIAL_CARD_TEMPLATE
    card = card.replace("{{PLATFORM_NAME}}", html.escape(platform_name))
    card = card.replace("{{PLATFORM_COLOR}}", platform_color)
    card = card.replace("{{PLATFORM_URL}}", html.escape(platform_url))
    card = card.replace("{{PLATFORM_DESCRIPTION}}", html.escape(description))
    card = card.replace("{{BUTTON_TEXT}}", html.escape(button_text))
    card = card.replace("{{QR_IMAGE}}", qr_html)
    return card


_SOCIAL_PLATFORMS = [
    {"name": "WhatsApp", "color": "#25D366", "url_key": "whatsapp_group_url", "qr_key": "whatsapp_qr_url",
     "description": "Join our WhatsApp group for event updates and coordination", "button": "Join WhatsApp Group"},
    {"name": "Telegram", "color": "#0088CC", "url_key": "telegram_group_url", "qr_key": "telegram_qr_url",
     "description": "Join our Telegram channel for announcements", "button": "Join Telegram Channel"},
    {"name": "Instagram", "color": "#E4405F", "url_key": "instagram_url", "qr_key": "",
     "description": "Follow us for photos, reels, and event highlights", "button": "Follow on Instagram"},
    {"name": "YouTube", "color": "#FF0000", "url_key": "youtube_url", "qr_key": "",
     "description": "Subscribe for live streams and event videos", "button": "Subscribe on YouTube"},
]


def send_combined_qr_email(to_email: str, members_qr: List[Dict], reference: str = ""):
    """Send registration confirmation with QR codes for one or more members."""
    to_email = _sanitize_email(to_email)
    reference = _sanitize_text(reference)

    member_cards = []
    attachments = []

    for item in members_qr:
        member_name = html.escape(_sanitize_text(item["member_name"]))
        ticket_number = html.escape(_sanitize_text(item["ticket_number"]))
        qr_bytes = item["qr_bytes"]

        if qr_bytes:
            qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
            cid = f"qr-{ticket_number}"
            qr_html = (
                f'<img src="cid:{cid}" alt="QR Code for {ticket_number}" '
                f'width="200" height="200" style="display: block; margin: 0 auto;" />'
            )
            attachments.append({"filename": f"qrcode-{ticket_number}.png", "content": qr_base64, "content_id": cid})
        else:
            qr_html = '<p style="margin: 0; color: #999; font-size: 13px; font-style: italic;">QR code will be sent in a follow-up email.</p>'

        member_cards.append(_build_member_card(member_name, ticket_number, qr_html))

    members_heading = "Your Ticket" if len(members_qr) == 1 else f"Your Tickets ({len(members_qr)} Members)"

    email_html = _REGISTRATION_TEMPLATE
    email_html = email_html.replace("{{BANNER_URL}}", settings.email_banner_url)
    email_html = email_html.replace("{{LOGO_URL}}", settings.email_logo_url)
    email_html = email_html.replace("{{REFERENCE}}", html.escape(reference))
    email_html = email_html.replace("{{MEMBERS_HEADING}}", members_heading)
    email_html = email_html.replace("{{MEMBERS_SECTION}}", "\n".join(member_cards))

    first_member_name = html.escape(members_qr[0]["member_name"])
    if len(members_qr) == 1:
        subject = f"YDS Germany 2026 Registration Confirmation - {first_member_name}"
    else:
        subject = f"YDS Germany 2026 Registration Confirmation - {first_member_name} (+{len(members_qr) - 1})"

    email_data = {"from": settings.resend_from_email, "to": [to_email], "subject": subject, "html": email_html}
    if attachments:
        email_data["attachments"] = attachments

    resend.Emails.send(email_data)
    logger.info(f"Sent registration email ({len(members_qr)} members) to {_mask_email(to_email)}")


def send_travel_email(to_email: str):
    """Send Travel Guide email."""
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": [to_email],
        "subject": "Travel Guide - YDS Germany 2026",
        "html": "<h2>Travel Guide</h2><p>Please find the travel guide details below.</p>",
    })
    logger.info(f"Sent travel email to {_mask_email(to_email)}")


def send_social_email(to_email: str):
    """Send social group links (WhatsApp, Telegram, etc.) email."""
    social_sections = []

    for platform in _SOCIAL_PLATFORMS:
        url = getattr(settings, platform["url_key"], "")
        if not url:
            continue
        qr_url = getattr(settings, platform["qr_key"], "") if platform["qr_key"] else ""
        social_sections.append(_build_social_card(
            platform_name=platform["name"], platform_color=platform["color"],
            platform_url=url, description=platform["description"],
            button_text=platform["button"], qr_image_url=qr_url,
        ))

    if not social_sections:
        logger.warning("No social platforms configured — skipping social email")
        return

    email_html = _SOCIAL_TEMPLATE
    email_html = email_html.replace("{{LOGO_URL}}", settings.email_logo_url)

    slot_names = ["WHATSAPP_SECTION", "TELEGRAM_SECTION", "INSTAGRAM_SECTION", "YOUTUBE_SECTION"]
    for i, slot in enumerate(slot_names):
        email_html = email_html.replace(f"{{{{{slot}}}}}", social_sections[i] if i < len(social_sections) else "")

    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": [to_email],
        "subject": "Stay Connected - YDS Germany 2026",
        "html": email_html,
    })
    logger.info(f"Sent social email to {_mask_email(to_email)}")
