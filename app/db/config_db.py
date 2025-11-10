# app/db/config_db.py
from sqlmodel import SQLModel, create_engine, Session
from app.constants.constants import Settings

# Build the database URL
db_url = (
    f"postgresql+psycopg2://"
    f"{Settings().db_user}:{Settings().db_password}@"
    f"{Settings().db_host}:{Settings().db_port}/{Settings().db_name}"
)

# Create SQLModel engine (sync)
engine = create_engine(db_url, echo=True, future=True)

def init_db() -> None:
    """
    Initialize all SQLModel tables.
    NOTE: Ensure that DB user already has access to the schema.
    """
    SQLModel.metadata.create_all(engine)

def get_session():
    """
    FastAPI dependency for a per-request session.
    """
    with Session(engine) as session:
        yield session
