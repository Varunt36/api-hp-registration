from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@contact.onetouchpro.app"
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"
    debug: bool = False

    whatsapp_group_url: str = "https://chat.whatsapp.com/your-invite-code"
    telegram_group_url: str = "https://t.me/+IT1zhtSm-HA3Y2Yy"
    instagram_url: str = "https://www.instagram.com/hariprabodhamgermany?igsh=NDFrcTBydXdlc3lt&utm_source=qr"
    youtube_url: str = "https://www.youtube.com/@harisumiranDE"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    price_per_person_eur: float = 290.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
