import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, DateTime, func, JSON, String
from sqlmodel import SQLModel, Field
from sqlalchemy import Text
from app.constants.constants import Settings


class Base(SQLModel):
    __table_args__ = {"schema": Settings().db_schema}


class Users(Base, table=True):
    """Store user information and integration settings."""

    __tablename__ = "users"

    # Telegram Info (from message.from and message.chat)
    chat_id: str = Field(primary_key=True, description="Telegram chat/user ID")
    username: Optional[str] = Field(default=None, description="Telegram username")
    first_name: Optional[str] = Field(
        default=None, description="User's first name from Telegram"
    )
    language_code: Optional[str] = Field(
        default=None, description="User's language preference"
    )
    is_bot: bool = Field(default=False, description="Whether the user is a bot")

    # Notion Integration
    notion_api_key: Optional[str] = Field(
        default=None, description="Notion API integration token"
    )
    notion_workspace_name: Optional[str] = Field(
        default=None, description="Name of the Notion workspace"
    )
    notion_enabled: bool = Field(
        default=False, description="Whether Notion integration is enabled"
    )

    # Store list of notion database ids the user wants to monitor
    # Stored as JSON array of strings
    notion_db_pages: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="List of Notion database IDs/URLs",
    )

    # Store mappings per database: list of objects {"db_id": str, "name_prop": str, "time_prop": str}
    notion_db_mappings: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Saved property mappings for each Notion DB",
    )

    # How often to check notion pages (hours). Allowed values: 12 or 24. Default 12
    notion_check_frequence: int = Field(
        default=12, description="Notion refresh frequency in hours"
    )

    # User Preferences & State
    timezone: Optional[str] = Field(
        default="UTC", description="User's timezone for scheduling"
    )
    notifications_enabled: bool = Field(
        default=True, description="Whether notifications are enabled"
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )
    last_active_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )


class Reminders(Base, table=True):
    __tablename__ = "reminders"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True, index=True
    )

    created_at: Optional[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )

    updated_at: Optional[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

    active: bool = Field(default=True, nullable=False)

    reminder_name: str = Field(sa_column=Column(Text))
    reminder_content: str = Field(nullable=False)

    # Source of the reminder: 'user' (manually created) or 'notion' (imported from Notion)
    source: str = Field(
        default="user", description="Source of the reminder: user or notion"
    )

    # Notion page/database id (optional)
    notion_page_id: Optional[str] = Field(
        default=None,
        description="Notion page or database id that created this reminder",
    )

    # Repeat interval (in minutes). None means one-time reminder.
    # default to None (one-time) to avoid accidental recurring behavior
    interval_minutes: Optional[int] = Field(
        default=None, nullable=True, description="Repeat interval in minutes"
    )

    # Next time this reminder should trigger
    next_trigger_at: Optional[datetime] = Field(
        default=None, description="Next reminder trigger time"
    )

    # Last time this reminder was triggered
    last_triggered_at: Optional[datetime] = Field(
        default=None, description="Last reminder trigger time"
    )

    # Chat id where the reminder should be sent. Optional to preserve existing rows.
    chat_id: Optional[str] = Field(
        default=None, description="Telegram chat id to send the reminder to"
    )
