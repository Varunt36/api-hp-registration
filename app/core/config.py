from pydantic_settings import BaseSettings

BLUE_MIRAGE_FONT_URL = "https://klfmhhsamhraxohdynyz.supabase.co/storage/v1/object/sign/Fonts/blue_mirage-webfont.woff2?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV8xNDA3ZDEwNy1mNzI3LTQ0ZjktYTU5OC02ODg5NmQxYTNiNDUiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJGb250cy9ibHVlX21pcmFnZS13ZWJmb250LndvZmYyIiwiaWF0IjoxNzc5OTAxMDA1LCJleHAiOjE4NDI5NzMwMDV9.3NvzbJpA3zSZqRxUud433MZTKrE-jNW3lzrOiTiGdfg"

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

    form_url: str = "https://forms.gle/4KEsyEbCRvZnM3Wx5"
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_template_name: str = "registration_form_link"
    wa_template_lang: str = "en"

    price_per_person_eur: float = 290.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
