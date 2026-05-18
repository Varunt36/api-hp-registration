from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    resend_api_key: str
    resend_from_email: str = "noreply@contact.onetouchpro.app"
    frontend_url: str = "http://localhost:5173"
    debug: bool = False

    whatsapp_group_url: str = ""
    telegram_group_url: str = ""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_mode: str = "sandbox"  # "sandbox" | "live"

    payment_amount_per_member: float = 290.00

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
