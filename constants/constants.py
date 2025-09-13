import os

from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "mydb")
DB_SCHEMA = os.getenv("DB_SCHEMA", "public")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "N7eqrd4HSPU18")

DATABASE_URL = (f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

GOLDAPI_API_KEY = os.getenv("GOLDAPI_API_KEY")
GOLDAPI_API_KEY_2 = os.getenv("GOLDAPI_API_KEY_2")
GOLDAPI_API_KEY_3 = os.getenv("GOLDAPI_API_KEY_3")
GOLDAPI_API_KEY_4 = os.getenv("GOLDAPI_API_KEY_4")
