import io
import logging
import qrcode

logger = logging.getLogger(__name__)


def generate_qr_image(ticket_number: str) -> bytes:
    """Generate a QR code PNG in memory.

    The QR code encodes the ticket number (e.g. "HP-2026-00042-M1").
    At check-in, scanning this QR returns the ticket number to look up the member.

    Returns:
        Raw PNG bytes (embedded inline in the registration email via CID).
    """
    qr = qrcode.make(ticket_number)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    qr_bytes = buffer.read()

    logger.info(f"QR generated for {ticket_number}")
    return qr_bytes
