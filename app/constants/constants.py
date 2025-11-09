from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    db_user: str
    db_password: str
    db_name: str
    db_host: str
    db_port: int
    db_schema: str = "public"

    bot_token: str
    chat_id: str

    model_config = SettingsConfigDict()
    
settings = Settings()