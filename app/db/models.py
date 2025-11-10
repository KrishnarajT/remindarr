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

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, index=True)

    created_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )

    updated_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

    active: bool = Field(default=True, nullable=False)

    reminder_name: str = Field(nullable=False, max_length=255)
    reminder_content: str = Field(nullable=False)

    # Repeat interval (in minutes)
    # default to 24 hours expressed in minutes
    interval_minutes: int = Field(default=0, nullable=False, description="Repeat interval in minutes")

    # Next time this reminder should trigger
    next_trigger_at: Optional[datetime] = Field(default=None, description="Next reminder trigger time")

    # Last time this reminder was triggered
    last_triggered_at: Optional[datetime] = Field(default=None, description="Last reminder trigger time")

    # Chat id where the reminder should be sent. Optional to preserve existing rows.
    chat_id: Optional[str] = Field(default=None, description="Telegram chat id to send the reminder to")
