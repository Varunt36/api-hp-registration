import base64
import html
import logging
import os
from typing import Dict, List

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.resend_api_key

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _load(filename: str) -> str:
    with open(os.path.join(_TEMPLATE_DIR, filename), encoding="utf-8") as f:
        return f.read()


_REGISTRATION_TEMPLATE = _load("registration_email.html")
_MEMBER_CARD_TEMPLATE = _load("member_card.html")


def _load_bytes(filename: str) -> bytes:
    with open(os.path.join(_TEMPLATE_DIR, filename), "rb") as f:
        return f.read()


_INSTAGRAM_ICON_BYTES = _load_bytes("instagram-icon.png")
_YOUTUBE_ICON_BYTES = _load_bytes("youtube-icon.png")

_HOTEL_URL = "https://hpam.hariprabodham.de/hotel-offer"
_EXPLORE_URL = "https://hpam.hariprabodham.de/explore"
_YOUTUBE_URL = "https://www.youtube.com/@harisumiranDE"


def _safe(text: str) -> str:
    """Strip CR/LF/NUL (header-injection defense) and HTML-escape."""
    return html.escape(text.replace("\r", "").replace("\n", "").replace("\0", "").strip())


def _mask_email(email: str) -> str:
    local, domain = email.split("@")
    return f"{local[0]}***@{domain}"


def send_combined_qr_email(to_email: str, members_qr: List[Dict], reference: str = "") -> None:
    to = to_email.replace("\r", "").replace("\n", "").strip()
    safe_ref = _safe(reference)
    cards, attachments = [], []

    for item in members_qr:
        name = _safe(item["member_name"])
        ticket = item["ticket_number"].strip()

        if item["qr_bytes"]:
            cid = f"qr-{ticket}"
            qr_html = (
                f'<img src="cid:{cid}" alt="Entry Pass QR Code" width="150" height="150" '
                f'style="display:block; margin:0 auto 16px auto; border-radius:6px;" />'
            )
            attachments.append({
                "filename": f"qrcode-{ticket}.png",
                "content": base64.b64encode(item["qr_bytes"]).decode("utf-8"),
                "content_id": cid,
            })
        else:
            qr_html = (
                '<p style="margin:0 0 16px; color:#9c8eb0; font-size:12px; '
                'font-style:italic;">QR code will be sent in a follow-up email.</p>'
            )

        cards.append(
            _MEMBER_CARD_TEMPLATE
            .replace("{{MEMBER_NAME}}", name)
            .replace("{{REFERENCE}}", safe_ref)
            .replace("{{QR_IMAGE}}", qr_html)
        )

    body = (
        _REGISTRATION_TEMPLATE
        .replace("{{MEMBERS_SECTION}}", "\n".join(cards))
        .replace("{{HOTEL_URL}}", html.escape(_HOTEL_URL))
        .replace("{{TRAVEL_URL}}", html.escape(_EXPLORE_URL))
        .replace("{{WHATSAPP_URL}}", html.escape(settings.whatsapp_group_url))
        .replace("{{TELEGRAM_URL}}", html.escape(settings.telegram_group_url))
        .replace("{{INSTAGRAM_URL}}", html.escape(settings.instagram_url))
        .replace("{{YOUTUBE_URL}}", html.escape(_YOUTUBE_URL))
        .replace("{{INSTAGRAM_ICON_URL}}", "cid:instagram-icon")
        .replace("{{YOUTUBE_ICON_URL}}", "cid:youtube-icon")
    )

    attachments.extend([
        {
            "filename": "instagram-icon.png",
            "content": base64.b64encode(_INSTAGRAM_ICON_BYTES).decode("utf-8"),
            "content_id": "instagram-icon",
        },
        {
            "filename": "youtube-icon.png",
            "content": base64.b64encode(_YOUTUBE_ICON_BYTES).decode("utf-8"),
            "content_id": "youtube-icon",
        },
    ])

    first = html.escape(members_qr[0]["member_name"])
    suffix = "" if len(members_qr) == 1 else f" (+{len(members_qr) - 1})"
    subject = f"HariPrabodham Germany 2026 Registration Confirmation - {first}{suffix}"

    payload = {"from": settings.resend_from_email, "to": [to], "subject": subject, "html": body, "attachments": attachments}

    resend.Emails.send(payload)
    logger.info(f"Sent registration email ({len(members_qr)} members) to {_mask_email(to)}")
