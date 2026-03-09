from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@yourdomain.com"
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


settings = Settings()
