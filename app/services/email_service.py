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


def _load(filename: str) -> str:
    with open(os.path.join(_TEMPLATE_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


_REGISTRATION_TEMPLATE = _load("registration_email.html")
_MEMBER_CARD_TEMPLATE = _load("member_card.html")


def _clean(text: str) -> str:
    """Strip newlines/nulls to prevent header injection and stray whitespace."""
    return text.replace("\r", "").replace("\n", "").replace("\0", "").strip()


def _mask_email(email: str) -> str:
    local, domain = email.split("@")
    return f"{local[0]}***@{domain}"


def send_combined_qr_email(to_email: str, members_qr: List[Dict], reference: str = ""):
    """Send the single registration confirmation: entry passes + travel + community."""
    to_email = _clean(to_email)
    safe_reference = html.escape(_clean(reference))

    cards = []
    attachments = []

    for item in members_qr:
        name = html.escape(_clean(item["member_name"]))
        ticket = _clean(item["ticket_number"])

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
            .replace("{{REFERENCE}}", safe_reference)
            .replace("{{QR_IMAGE}}", qr_html)
        )

    body = (
        _REGISTRATION_TEMPLATE
        .replace("{{MEMBERS_SECTION}}", "\n".join(cards))
        .replace("{{TRAVEL_URL}}", html.escape(settings.frontend_url.rstrip("/") + "/explore"))
        .replace("{{WHATSAPP_URL}}", html.escape(settings.whatsapp_group_url))
        .replace("{{TELEGRAM_URL}}", html.escape(settings.telegram_group_url))
    )

    first_name = html.escape(members_qr[0]["member_name"])
    suffix = "" if len(members_qr) == 1 else f" (+{len(members_qr) - 1})"
    subject = f"HariPrabodham Germany 2026 Registration Confirmation - {first_name}{suffix}"

    payload = {"from": settings.resend_from_email, "to": [to_email], "subject": subject, "html": body}
    if attachments:
        payload["attachments"] = attachments

    resend.Emails.send(payload)
    logger.info(f"Sent registration email ({len(members_qr)} members) to {_mask_email(to_email)}")
