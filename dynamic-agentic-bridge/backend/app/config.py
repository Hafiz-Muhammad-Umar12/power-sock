"""
Application configuration loaded from environment variables via pydantic-settings.
Never hardcode secrets — use .env or environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/dynamic_bridge"

    # Anthropic API
    anthropic_api_key: str = ""

    # Supabase (optional)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # Credential encryption
    credential_encryption_key: str = ""

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Playwright
    playwright_headless: bool = True


settings = Settings()
