from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@contact.onetouchpro.app"
    frontend_url: str = "http://localhost:5173"
    debug: bool = False  # Set True in .env for local development (enables /docs + /redoc)
    # Email template images — host these in Supabase Storage (public bucket) or any CDN
    email_banner_url: str = ""   # Hero banner image URL
    email_logo_url: str = ""     # Organization logo image URL
    # Social group invite links (private — only sent to registered members via email)
    whatsapp_group_url: str = ""
    whatsapp_qr_url: str = ""     # Hosted QR code image URL for WhatsApp group
    telegram_group_url: str = ""
    telegram_qr_url: str = ""     # Hosted QR code image URL for Telegram group
    instagram_url: str = ""
    youtube_url: str = ""
    # Payment — Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Payment — PayPal
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_mode: str = "sandbox"  # "sandbox" or "live"
    # Pricing
    payment_amount_per_member: float = 250.00  # EUR per member

    class Config:
        env_file = ".env"


settings = Settings()
