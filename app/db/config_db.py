# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from app.constants.constants import Settings

# Build DB URL from environment
db_url = (
    f"postgresql+psycopg2://"
    f"{Settings().db_user}:{Settings().db_password}@"
    f"{Settings().db_host}:{Settings().db_port}/{Settings().db_name}"
)

# Create the engine (synchronous)
engine = create_engine(db_url, echo=True, future=True)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db() -> None:
    """
    Initialize the database (run once on startup):
    - Creates schema if missing
    - Creates all tables
    """
    with engine.begin() as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {Settings().db_schema}")
        SQLModel.metadata.create_all(bind=conn)

def get_session():
    """
    FastAPI dependency — yields a database session per request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
