from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@contact.onetouchpro.app"
    frontend_url: str = "http://localhost:5173"
    # Email template images — host these in Supabase Storage (public bucket) or any CDN
    email_banner_url: str = ""   # Hero banner image URL
    email_logo_url: str = ""     # Organization logo image URL

    class Config:
        env_file = ".env"


settings = Settings()
