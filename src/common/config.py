"""Configuration management via environment variables."""
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    """Application configuration from environment variables."""

    # Database
    database_bucket: str
    database_key: str

    # Telegram (optional for admin handler)
    telegram_bot_token: str | None
    webhook_secret: str | None

    # Anthropic
    anthropic_api_key: str
    anthropic_base_url: str | None
    anthropic_model: str

    # Admin (optional for telegram handler)
    admin_password: str | None

    # Optional: Summarizer Lambda function name (for invoking from telegram_handler)
    summarizer_function_name: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            database_bucket=os.environ["DATABASE_BUCKET"],
            database_key=os.environ.get("DATABASE_KEY", "chatbot.db"),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            webhook_secret=os.environ.get("WEBHOOK_SECRET"),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            admin_password=os.environ.get("ADMIN_PASSWORD"),
            summarizer_function_name=os.environ.get("SUMMARIZER_FUNCTION_NAME"),
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Get cached configuration instance."""
    return Config.from_env()
