# app/db/config_db.py
from sqlalchemy import text
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
    Initialize database schema and all SQLModel tables.
    """
    # Get our target schema
    schema = Settings().db_schema

    # Create a raw connection to create the schema
    with engine.begin() as conn:
        # Check if schema exists
        result = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = :schema"
            ),
            {"schema": schema}
        )
        schema_exists = result.scalar() is not None

        # Create schema if it doesn't exist
        if not schema_exists:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            conn.commit()

    # Now create all tables in the schema
    SQLModel.metadata.create_all(engine)

def get_session():
    """
    FastAPI dependency for a per-request session.
    """
    with Session(engine) as session:
        yield session
