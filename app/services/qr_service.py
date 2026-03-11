from typing import Tuple
import io
import logging
import qrcode
from app.core.supabase import supabase

logger = logging.getLogger(__name__)


def generate_qr_image(ticket_number: str) -> Tuple[bytes, str]:
    """Generate a QR code PNG and upload it to Supabase Storage.

    The QR code encodes the ticket number (e.g. "HP-2026-00042-M1").
    At check-in, scanning this QR returns the ticket number to look up the member.

    Returns:
        Tuple of (qr_bytes, public_url):
        - qr_bytes: raw PNG bytes (used as inline email attachment)
        - public_url: Supabase Storage public URL (saved in members.qr_url for later access)
    """
    qr = qrcode.make(ticket_number)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    qr_bytes = buffer.read()

    # Upload to Supabase Storage bucket "qr-codes"
    # File path = ticket number (unique per member), e.g. "HP-2026-00042-M1.png"
    file_path = f"{ticket_number}.png"
    supabase.storage.from_("qr-codes").upload(
        file_path,
        qr_bytes,
        {"content-type": "image/png"},
    )

    public_url = supabase.storage.from_("qr-codes").get_public_url(file_path)
    logger.info(f"QR uploaded for {ticket_number}")
    return qr_bytes, public_url
