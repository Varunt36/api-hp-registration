import io
import base64
import qrcode


def generate_qr_base64(data: str) -> str:
    """Generate a QR code and return it as a base64-encoded PNG string."""
    qr = qrcode.make(data)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def generate_qr_bytes(data: str) -> bytes:
    """Generate a QR code and return raw PNG bytes (for email attachment)."""
    qr = qrcode.make(data)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()
