import io
import logging
import qrcode

logger = logging.getLogger(__name__)


def generate_qr_image(ticket_number: str) -> bytes:
    """Generate a QR code PNG in memory. Returns raw PNG bytes."""
    qr = qrcode.make(ticket_number)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()
