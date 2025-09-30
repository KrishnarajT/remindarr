# models.py

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, func
from sqlmodel import SQLModel, Field

from app.constants.constants import Settings


class Base(SQLModel):
    __table_args__ = {"schema": Settings().db_schema}


class Reminders(Base, table=True):
    __tablename__ = "reminders"

    # frontend uses string id — use UUID4 string here
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, index=True)

    # These are optional in Python model because the DB will fill them
    created_at: Optional[datetime] = Field(default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False, ), )

    updated_at: Optional[datetime] = Field(default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, ), )

    # active flag for soft delete
    active: bool = Field(default=True, nullable=False)

    # reminder_name
    reminder_name: str = Field(nullable=False, max_length=255)

    # reminder content (the message to give to the user when reminding)
    reminder_content: str = Field(nullable=False)


