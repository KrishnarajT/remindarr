import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram settings
    bot_token: str
    chat_id: str

    # Database settings
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: str

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
