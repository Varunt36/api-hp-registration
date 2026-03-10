from typing import Tuple
import io
import logging
import qrcode
from app.core.supabase import supabase

logger = logging.getLogger(__name__)


def generate_qr_image(ticket_number: str) -> Tuple[bytes, str]:
    """Generate QR code PNG, upload to Supabase Storage, return (bytes, public_url)."""
    qr = qrcode.make(ticket_number)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    qr_bytes = buffer.read()

    # Upload to Supabase Storage
    file_path = f"{ticket_number}.png"
    supabase.storage.from_("qr-codes").upload(
        file_path,
        qr_bytes,
        {"content-type": "image/png"},
    )

    public_url = supabase.storage.from_("qr-codes").get_public_url(file_path)
    logger.info(f"QR uploaded for {ticket_number}")
    return qr_bytes, public_url
