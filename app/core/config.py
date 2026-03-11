from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@contact.onetouchpro.app"
    frontend_url: str = "http://localhost:5173"
    debug: bool = True  # Set False in production to disable docs + enable HSTS
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

    class Config:
        env_file = ".env"


settings = Settings()
