from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlmodel import select
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum
import re
import json
import requests

from app.db.config_db import get_session
from app.db.models import Reminders, Users
from app.services.telegram import send_message
from app.constants.constants import settings
from app.utils.logging_utils import logger
from app.utils.time_utils import parse_time_unit, calculate_next_trigger

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ============================================
# ENUMS & CONSTANTS
# ============================================


class FlowType(Enum):
    NONE = "none"
    REMINDER = "reminder"
    NOTION = "notion"
    SETTINGS = "settings"


class NotionStep(Enum):
    MENU = 0
    TOKEN = 1
    DB_ID = 2
    NAME_PROP = 3
    TIME_PROP = 4
    STATUS_PROP = 5
    IMPORT_CONFIRM = 6
    REMOVE_DB = 7


class ReminderStep(Enum):
    START = 0
    NAME = 1
    TYPE = 2
    UNIT = 3
    AMOUNT = 4
    CONTENT = 5


# ============================================
# STATE MANAGEMENT
# ============================================


class UserState:
    """Manages conversational state for a user."""

    def __init__(self):
        self.flow_type = FlowType.NONE
        self.step = 0
        self.data = {}

    def reset(self):
        self.flow_type = FlowType.NONE
        self.step = 0
        self.data = {}

    def set_flow(self, flow_type: FlowType, step: int = 0):
        self.flow_type = flow_type
        self.step = step
        self.data = {}


# In-memory state stores
user_states: Dict[int, UserState] = {}


def get_user_state(chat_id: int) -> UserState:
    """Get or create user state."""
    if chat_id not in user_states:
        user_states[chat_id] = UserState()
    return user_states[chat_id]


def clear_user_state(chat_id: int):
    """Clear user state."""
    if chat_id in user_states:
        del user_states[chat_id]


# ============================================
# USER MANAGEMENT
# ============================================


async def get_or_create_user(db: Session, telegram_data: dict) -> Users:
    """Get existing user or create new one from Telegram data."""
    message = telegram_data["message"]
    from_user = message["from"]
    chat = message["chat"]

    user = db.get(Users, str(chat["id"]))
    if not user:
        user = Users(
            chat_id=str(chat["id"]),
            username=from_user.get("username"),
            first_name=from_user.get("first_name"),
            language_code=from_user.get("language_code"),
            is_bot=from_user.get("is_bot", False),
        )
        db.add(user)
        logger.info(f"Created new user: {chat['id']}")
    else:
        # Update user info
        user.username = from_user.get("username", user.username)
        user.first_name = from_user.get("first_name", user.first_name)
        user.language_code = from_user.get("language_code", user.language_code)
        user.last_active_at = datetime.utcnow()
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


# ============================================
# NOTION API HELPERS
# ============================================


def validate_notion_token(token: str) -> tuple[bool, Optional[dict]]:
    """Validate Notion API token."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    try:
        resp = requests.get(
            "https://api.notion.com/v1/users/me", headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return True, resp.json()
        return False, None
    except Exception as e:
        logger.error(f"Notion token validation error: {e}")
        return False, None


def get_notion_database(token: str, db_id: str) -> tuple[bool, Optional[dict]]:
    """Fetch Notion database details."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    try:
        resp = requests.get(
            f"https://api.notion.com/v1/databases/{db_id}", headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return True, resp.json()
        logger.error(f"Failed to fetch Notion DB {db_id}: {resp.text}")
        return False, None
    except Exception as e:
        logger.error(f"Notion database fetch error: {e}")
        return False, None


def query_notion_database(
    token: str, db_id: str, status_prop: str = None, status_prop_type: str = None
) -> tuple[bool, list]:
    """Query Notion database pages with optional status filtering."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    body = {}
    # Filter for incomplete tasks if status property is provided
    if status_prop:
        if status_prop_type == "checkbox":
            # For checkbox: False = not done
            body["filter"] = {"property": status_prop, "checkbox": {"equals": False}}
        elif status_prop_type == "select" or status_prop_type == "status":
            # For select/status: exclude "Done" or "Completed"
            body["filter"] = {
                "and": [
                    {"property": status_prop, "select": {"does_not_equal": "Done"}},
                    {
                        "property": status_prop,
                        "select": {"does_not_equal": "Completed"},
                    },
                ]
            }

    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers,
            json=body,
            timeout=15,
        )
        if resp.status_code == 200:
            return True, resp.json().get("results", [])
        logger.error(f"Failed to query Notion DB {db_id}: {resp.text}")
        return False, []
    except Exception as e:
        logger.error(f"Notion database query error: {e}")
        return False, []


def extract_notion_property_value(prop_data: dict) -> Optional[str]:
    """Extract value from Notion property based on type."""
    if not prop_data:
        return None

    prop_type = prop_data.get("type")

    if prop_type == "title":
        arr = prop_data.get("title", [])
        return "".join([t.get("plain_text", "") for t in arr]).strip() or None

    elif prop_type == "rich_text":
        arr = prop_data.get("rich_text", [])
        return "".join([t.get("plain_text", "") for t in arr]).strip() or None

    elif prop_type == "date":
        dt = prop_data.get("date")
        return dt.get("start") if dt else None

    elif prop_type == "checkbox":
        return prop_data.get("checkbox")

    elif prop_type == "select":
        sel = prop_data.get("select")
        return sel.get("name") if sel else None

    return None


# ============================================
# MESSAGE HANDLERS
# ============================================


def send_start_message(chat_id: int, user: Users):
    """Send welcome message with user's name."""
    name = user.first_name or user.username or "there"
    message = f"""👋 Hello {name}! Welcome to Reminder Bot!

I can help you manage reminders and sync with Notion databases.

📋 *Available Commands:*

/start - Show this welcome message
/add - Create a new reminder
/list - View all your reminders
/notion - Set up Notion integration
/settings - Configure your preferences
/help - Get detailed help

Let me know how I can assist you today!"""

    send_message(settings.bot_token, chat_id, message)


def send_help_message(chat_id: int):
    """Send detailed help message."""
    message = """📚 *Reminder Bot Help*

*Creating Reminders:*
Use /add to create a new reminder. I'll guide you through:
• Naming your reminder
• Setting it as one-time or recurring
• Choosing the time interval (minutes/hours/days)
• Adding a custom message

*Notion Integration:*
Use /notion to connect your Notion databases:
• Add your Notion API token
• Link databases to monitor
• Map task properties (name, time, status)
• Import existing tasks as reminders
• Set refresh frequency (12 or 24 hours)

*Settings:*
Use /settings to configure:
• Enable/disable Notion sync
• Change refresh frequency
• View connected databases
• Manage integrations

*Tips:*
• Only incomplete Notion tasks are imported
• Recurring reminders repeat automatically
• Use clear, descriptive reminder names"""

    send_message(settings.bot_token, chat_id, message)


def send_settings_menu(chat_id: int, user: Users):
    """Send interactive settings menu."""
    notion_status = "✅ Enabled" if user.notion_enabled else "❌ Disabled"
    freq = getattr(user, "notion_check_frequence", 12)
    db_count = len(user.notion_db_pages or [])

    message = f"""⚙️ *Settings Menu*

*Notion Integration:* {notion_status}
*Refresh Frequency:* {freq} hours
*Connected Databases:* {db_count}

*Available Commands:*
• `toggle` - Enable/disable Notion sync
• `freq 12` or `freq 24` - Change refresh frequency
• `databases` - View connected databases
• `done` - Exit settings

Reply with a command to configure your settings."""

    send_message(settings.bot_token, chat_id, message)


def send_notion_menu(chat_id: int, user: Users):
    """Send Notion integration menu."""
    has_token = bool(user.notion_api_key)

    if not has_token:
        message = """🔗 *Notion Integration Setup*

To connect with Notion, I'll need an integration token.

📝 *How to get your token:*
1. Go to https://www.notion.so/my-integrations
2. Click "+ New integration"
3. Give it a name and submit
4. Copy the "Internal Integration Token"
5. Share databases with your integration

Send me the token (starts with 'secret_' or 'ntn_') to continue."""
    else:
        db_count = len(user.notion_db_pages or [])
        status = "✅ Enabled" if user.notion_enabled else "❌ Disabled"

        message = f"""🔗 *Notion Integration*

*Status:* {status}
*Connected Databases:* {db_count}

*Available Commands:*
• `add` - Add a new database
• `remove` - Remove a database
• `list` - View all databases
• `change token` - Update API token
• `done` - Exit setup

Reply with a command to manage your integration."""

    send_message(settings.bot_token, chat_id, message)


# ============================================
# NOTION FLOW HANDLERS
# ============================================


async def handle_notion_flow(
    chat_id: int, text: str, user: Users, state: UserState, db: Session
):
    """Handle Notion integration flow."""
    step = state.step
    chat_id_str = str(chat_id)  # Convert for database operations

    # STEP 0: Menu (user has token)
    if step == NotionStep.MENU.value:
        cmd = text.strip().lower()

        if cmd in ("add", "add db", "add database"):
            state.step = NotionStep.DB_ID.value
            send_message(
                settings.bot_token,
                chat_id,
                "📎 Send the Notion database ID or URL you want to monitor.\n\n"
                "You can find this in the database URL:\n"
                "`notion.so/workspace/DATABASE_ID?v=...`",
            )
            return

        elif cmd in ("remove", "remove db", "remove database"):
            pages = user.notion_db_pages or []
            if not pages:
                send_message(
                    settings.bot_token,
                    chat_id,
                    "You don't have any databases connected.",
                )
                clear_user_state(chat_id)
                return

            listing = "\n".join(
                [f"{i+1}. `{p[:8]}...{p[-8:]}`" for i, p in enumerate(pages)]
            )
            send_message(
                settings.bot_token,
                chat_id,
                f"*Connected Databases:*\n{listing}\n\nReply with the number to remove:",
            )
            state.step = NotionStep.REMOVE_DB.value
            return

        elif cmd in ("list", "databases", "show"):
            pages = user.notion_db_pages or []
            if not pages:
                send_message(settings.bot_token, chat_id, "No databases connected.")
                return

            listing = "\n".join([f"{i+1}. `{p}`" for i, p in enumerate(pages)])
            send_message(
                settings.bot_token, chat_id, f"*Connected Databases:*\n{listing}"
            )
            return

        elif cmd in ("change token", "change api", "update token"):
            state.step = NotionStep.TOKEN.value
            send_message(
                settings.bot_token,
                chat_id,
                "🔑 Send your new Notion integration token (starts with 'secret_' or 'ntn_'):",
            )
            return

        elif cmd == "done":
            clear_user_state(chat_id)
            send_message(settings.bot_token, chat_id, "✅ Notion setup complete!")
            return

        else:
            send_notion_menu(chat_id, user)
            return

    # STEP 1: Token submission
    elif step == NotionStep.TOKEN.value:
        if not text.startswith(("secret_", "ntn_")):
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Invalid token format. It should start with 'secret_' or 'ntn_'.\n\nPlease try again:",
            )
            return

        valid, user_info = validate_notion_token(text)
        if not valid:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Token validation failed. Please check and try again:",
            )
            return

        try:
            user.notion_api_key = text
            user.notion_enabled = True
            db.add(user)
            db.commit()
            db.refresh(user)  # Refresh to get updated data

            notion_name = user_info.get("name") or "your Notion account"
            send_message(
                settings.bot_token,
                chat_id,
                f"✅ Successfully connected to Notion as: *{notion_name}*\n\n"
                "Now you can add databases. Send a database ID/URL or 'done' to finish.",
            )
            state.step = NotionStep.DB_ID.value

        except Exception as e:
            logger.error(f"Failed to save Notion token for user {chat_id}: {e}")
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Failed to save settings. Please try again later.",
            )
            clear_user_state(chat_id)
        return

    # STEP 2: Database ID
    elif step == NotionStep.DB_ID.value:
        if text.strip().lower() == "done":
            send_message(settings.bot_token, chat_id, "✅ Database setup complete!")
            clear_user_state(chat_id)
            return

        # Extract database ID from URL or raw ID
        match = re.search(r"[0-9a-fA-F\-]{32,36}", text)
        db_id = (
            match.group(0).replace("-", "") if match else text.strip().replace("-", "")
        )

        success, db_info = get_notion_database(user.notion_api_key, db_id)
        if not success:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Couldn't access that database.\n\n"
                "Make sure:\n"
                "• The database ID is correct\n"
                "• Your integration has access to it\n\n"
                "Try again or send 'done' to finish:",
            )
            return

        properties = db_info.get("properties", {})
        prop_names = list(properties.keys())

        if not prop_names:
            send_message(
                settings.bot_token, chat_id, "❌ This database has no properties."
            )
            return

        state.data["current_db_id"] = db_id
        state.data["properties"] = prop_names
        state.data["property_types"] = {
            name: prop.get("type") for name, prop in properties.items()
        }
        state.step = NotionStep.NAME_PROP.value

        props_text = "\n".join([f"• {p}" for p in prop_names])
        send_message(
            settings.bot_token,
            chat_id,
            f"✅ Found database with {len(prop_names)} properties:\n\n{props_text}\n\n"
            "📝 Which property contains the *task name*? (Reply with exact name)",
        )
        return

    # STEP 3: Name property
    elif step == NotionStep.NAME_PROP.value:
        prop = text.strip()
        properties = state.data.get("properties", [])

        if prop not in properties:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ That property wasn't found. Please reply with an exact property name from the list.",
            )
            return

        state.data["name_prop"] = prop
        state.step = NotionStep.TIME_PROP.value

        send_message(
            settings.bot_token,
            chat_id,
            "⏰ Which property contains the *task due date/time*? (Must be a Date property)",
        )
        return

    # STEP 4: Time property
    elif step == NotionStep.TIME_PROP.value:
        prop = text.strip()
        properties = state.data.get("properties", [])

        if prop not in properties:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ That property wasn't found. Please reply with an exact property name.",
            )
            return

        state.data["time_prop"] = prop
        state.step = NotionStep.STATUS_PROP.value

        send_message(
            settings.bot_token,
            chat_id,
            "✅ Which property indicates if a task is *done*? (Checkbox or Status property)\n\n"
            "This helps me import only incomplete tasks.",
        )
        return

    # STEP 5: Status/Done property
    elif step == NotionStep.STATUS_PROP.value:
        prop = text.strip()
        properties = state.data.get("properties", [])

        if prop not in properties:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ That property wasn't found. Please reply with an exact property name.",
            )
            return

        state.data["status_prop"] = prop
        state.step = NotionStep.IMPORT_CONFIRM.value

        send_message(
            settings.bot_token,
            chat_id,
            "🎯 Mapping complete!\n\n"
            "Import incomplete tasks from this database now?\n\n"
            "Reply: `yes` or `no`",
        )
        return

    # STEP 6: Import confirmation
    elif step == NotionStep.IMPORT_CONFIRM.value:
        choice = text.strip().lower()

        if choice not in ("yes", "no"):
            send_message(settings.bot_token, chat_id, "Please reply 'yes' or 'no'.")
            return

        db_id = state.data.get("current_db_id")
        name_prop = state.data.get("name_prop")
        time_prop = state.data.get("time_prop")
        status_prop = state.data.get("status_prop")

        # Save database mapping
        try:
            pages = user.notion_db_pages or []
            if db_id not in pages:
                user.notion_db_pages = pages + [db_id]

            mappings = user.notion_db_mappings or []
            mapping = {
                "db_id": db_id,
                "name_prop": name_prop,
                "time_prop": time_prop,
                "status_prop": status_prop,
            }
            # Replace existing mapping for same db_id
            mappings = [m for m in mappings if m.get("db_id") != db_id] + [mapping]
            user.notion_db_mappings = mappings

            db.add(user)
            db.commit()
            db.refresh(user)  # Refresh to get updated data

        except Exception as e:
            logger.error(f"Failed to save Notion mapping for user {chat_id}: {e}")
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Failed to save mapping. Please try again.",
            )
            clear_user_state(chat_id)
            return

        if choice == "no":
            send_message(
                settings.bot_token,
                chat_id,
                "✅ Mapping saved without importing.\n\nAdd more databases or send 'done'.",
            )
            state.step = NotionStep.DB_ID.value
            return

        # Perform import
        send_message(settings.bot_token, chat_id, "⏳ Importing tasks...")

        success, pages = query_notion_database(user.notion_api_key, db_id, status_prop)
        if not success:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Failed to query database. Mapping saved but import failed.",
            )
            clear_user_state(chat_id)
            return

        imported = 0
        skipped = 0

        for page in pages:
            try:
                props = page.get("properties", {})

                # Extract task name
                name_val = extract_notion_property_value(props.get(name_prop))
                if not name_val:
                    skipped += 1
                    continue

                # Extract due date
                time_val = extract_notion_property_value(props.get(time_prop))

                # Check status (skip if done)
                status_val = extract_notion_property_value(props.get(status_prop))
                if status_val is True:  # Task is marked as done
                    skipped += 1
                    continue

                # Create reminder
                reminder = Reminders(
                    reminder_name=name_val,
                    reminder_content=name_val,
                    chat_id=chat_id_str,  # Use string version
                    source="notion" if time_val else "user",
                    notion_page_id=page.get("id"),
                )

                if time_val:
                    try:
                        parsed = datetime.fromisoformat(time_val.rstrip("Z"))
                        reminder.next_trigger_at = parsed
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse date {time_val}: {parse_err}")

                db.add(reminder)
                imported += 1

            except Exception as e:
                logger.error(f"Failed to import Notion page for user {chat_id}: {e}")
                skipped += 1

        db.commit()

        send_message(
            settings.bot_token,
            chat_id,
            f"✅ Import complete!\n\n"
            f"• Imported: {imported} tasks\n"
            f"• Skipped: {skipped} (completed or invalid)\n\n"
            "Add more databases or send 'done'.",
        )

        state.step = NotionStep.DB_ID.value
        return

    # STEP 7: Remove database
    elif step == NotionStep.REMOVE_DB.value:
        pages = user.notion_db_pages or []

        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(pages):
                raise ValueError("Invalid index")

            removed = pages.pop(idx)

            # Remove mapping
            mappings = user.notion_db_mappings or []
            mappings = [m for m in mappings if m.get("db_id") != removed]

            user.notion_db_pages = pages
            user.notion_db_mappings = mappings
            db.add(user)
            db.commit()
            db.refresh(user)  # Refresh to get updated data

            send_message(
                settings.bot_token,
                chat_id,
                f"✅ Removed database: `{removed[:8]}...{removed[-8:]}`",
            )

        except Exception as e:
            logger.warning(f"Invalid database removal selection: {e}")
            send_message(
                settings.bot_token, chat_id, "❌ Invalid selection. Please try again."
            )
            return

        clear_user_state(chat_id)
        return


# ============================================
# SETTINGS FLOW HANDLERS
# ============================================


async def handle_settings_flow(
    chat_id: int, text: str, user: Users, state: UserState, db: Session
):
    """Handle settings configuration flow."""
    cmd = text.strip().lower()

    if cmd in ("toggle", "enable", "disable"):
        user.notion_enabled = not bool(user.notion_enabled)
        db.add(user)
        db.commit()
        db.refresh(user)  # Refresh to get updated data

        status = "enabled" if user.notion_enabled else "disabled"
        send_message(settings.bot_token, chat_id, f"✅ Notion integration {status}.")
        send_settings_menu(chat_id, user)
        return

    elif cmd.startswith("freq"):
        parts = cmd.split()
        if len(parts) == 2 and parts[1] in ("12", "24"):
            user.notion_check_frequence = int(parts[1])
            db.add(user)
            db.commit()
            db.refresh(user)  # Refresh to get updated data
            send_message(
                settings.bot_token,
                chat_id,
                f"✅ Refresh frequency set to {parts[1]} hours.",
            )
            send_settings_menu(chat_id, user)
        else:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Invalid format. Use: `freq 12` or `freq 24`",
            )
        return

    elif cmd in ("databases", "db", "list"):
        pages = user.notion_db_pages or []
        if not pages:
            send_message(settings.bot_token, chat_id, "No databases connected.")
        else:
            listing = "\n".join([f"{i+1}. `{p}`" for i, p in enumerate(pages)])
            send_message(
                settings.bot_token, chat_id, f"*Connected Databases:*\n{listing}"
            )
        return

    elif cmd == "done":
        clear_user_state(chat_id)
        send_message(settings.bot_token, chat_id, "✅ Settings saved.")
        return

    else:
        send_settings_menu(chat_id, user)
        return


# ============================================
# REMINDER FLOW HANDLERS
# ============================================


async def handle_reminder_flow(chat_id: int, text: str, state: UserState, db: Session):
    """Handle reminder creation flow."""
    step = state.step
    chat_id_str = str(chat_id)  # Convert for database operations

    # STEP 1: Name
    if step == ReminderStep.NAME.value:
        state.data["name"] = text
        state.step = ReminderStep.TYPE.value
        send_message(
            settings.bot_token,
            chat_id,
            "🔄 Should this be a *one-time* reminder or *recurring*?\n\nReply: `once` or `recurring`",
        )
        return

    # STEP 2: Type
    elif step == ReminderStep.TYPE.value:
        reminder_type = text.strip().lower()

        if reminder_type in ("once", "one-time", "onetime", "one"):
            state.data["is_recurring"] = False
        elif reminder_type in ("recurring", "repeat", "repeating"):
            state.data["is_recurring"] = True
        else:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Please reply with 'once' or 'recurring'.",
            )
            return

        state.step = ReminderStep.UNIT.value
        send_message(
            settings.bot_token,
            chat_id,
            "⏰ When should I remind you?\n\nReply: `minutes`, `hours`, or `days`",
        )
        return

    # STEP 3: Time unit
    elif step == ReminderStep.UNIT.value:
        multiplier, unit = parse_time_unit(text)

        if not multiplier or not unit:
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Please reply with 'minutes', 'hours', or 'days'.",
            )
            return

        state.data["unit"] = unit
        state.data["multiplier"] = multiplier
        state.step = ReminderStep.AMOUNT.value

        send_message(
            settings.bot_token, chat_id, f"🔢 How many {unit}?\n\nReply with a number:"
        )
        return

    # STEP 4: Amount
    elif step == ReminderStep.AMOUNT.value:
        try:
            amount = int(text)
            if amount <= 0:
                raise ValueError("Amount must be positive")

            state.data["amount"] = amount
            state.step = ReminderStep.CONTENT.value

            send_message(
                settings.bot_token,
                chat_id,
                "💬 What message should I send when reminding you?",
            )

        except ValueError:
            send_message(
                settings.bot_token, chat_id, "❌ Please enter a valid positive number."
            )
        return

    # STEP 5: Save reminder
    elif step == ReminderStep.CONTENT.value:
        is_recurring = state.data["is_recurring"]

        interval_minutes, next_trigger_at = calculate_next_trigger(
            amount=state.data["amount"],
            multiplier=state.data["multiplier"],
            is_recurring=is_recurring,
        )

        try:
            reminder = Reminders(
                reminder_name=state.data["name"],
                reminder_content=text,
                interval_minutes=interval_minutes,
                next_trigger_at=next_trigger_at,
                chat_id=chat_id_str,  # Use string version
            )
            db.add(reminder)
            db.commit()

            type_str = "recurring" if is_recurring else "one-time"
            send_message(
                settings.bot_token,
                chat_id,
                f"✅ *{type_str.title()} Reminder Created!*\n\n"
                f"📝 Name: {reminder.reminder_name}\n"
                f"⏰ Time: {state.data['amount']} {state.data['unit']}\n"
                f"💬 Message: {reminder.reminder_content}\n"
                f"🔔 Next trigger: {next_trigger_at.strftime('%Y-%m-%d %H:%M')}",
            )

            clear_user_state(chat_id)

        except Exception as e:
            logger.error(f"Failed to create reminder for user {chat_id}: {e}")
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Failed to create reminder. Please try again later.",
            )
            clear_user_state(chat_id)
        return


# ============================================
# MAIN WEBHOOK HANDLER
# ============================================


@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_session)):
    """Main webhook handler for Telegram messages."""
    try:
        body = await request.body()
        if not body:
            logger.warning("Received empty webhook body")
            return JSONResponse(content={"status": "ignored", "reason": "empty body"})

        data = await request.json()
        logger.info(f"Incoming Telegram webhook: {json.dumps(data, indent=2)}")

        if "message" not in data:
            return JSONResponse(
                content={"status": "ignored", "reason": "no message field"}
            )

        # Create or update user record
        user = await get_or_create_user(db, data)
        chat_id = data["message"]["chat"]["id"]  # This is an int from Telegram
        text = data["message"].get("text", "").strip()

        # Convert chat_id to string for consistency with database
        chat_id_str = str(chat_id)

        if not text:
            return JSONResponse(content={"status": "ignored", "reason": "empty text"})

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return JSONResponse(
            content={"status": "error", "reason": "invalid JSON"}, status_code=400
        )
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return JSONResponse(
            content={"status": "error", "reason": str(e)}, status_code=500
        )

    # Get current user state
    state = get_user_state(chat_id)

    # ============================================
    # COMMAND ROUTING
    # ============================================

    # Handle /start command
    if text == "/start":
        clear_user_state(chat_id)
        send_start_message(chat_id, user)
        return {"status": "ok"}

    # Handle /help command
    if text == "/help":
        clear_user_state(chat_id)
        send_help_message(chat_id)
        return {"status": "ok"}

    # Handle /add command
    if text == "/add":
        state.set_flow(FlowType.REMINDER, ReminderStep.NAME.value)
        send_message(
            settings.bot_token,
            chat_id,
            "✨ Let's create a new reminder!\n\n📝 What should I name it?",
        )
        return {"status": "ok"}

    # Handle /list command
    if text == "/list":
        clear_user_state(chat_id)
        try:
            stmt = select(Reminders).where(Reminders.chat_id == chat_id_str)
            reminders = db.exec(stmt).all()

            if not reminders:
                send_message(
                    settings.bot_token,
                    chat_id,
                    "You don't have any reminders yet. Use /add to create one!",
                )
                return {"status": "ok"}

            message = "📋 *Your Reminders:*\n\n"
            for i, reminder in enumerate(reminders, 1):
                recurring = (
                    "🔄 Recurring" if reminder.interval_minutes else "⏰ One-time"
                )
                next_time = (
                    reminder.next_trigger_at.strftime("%Y-%m-%d %H:%M")
                    if reminder.next_trigger_at
                    else "Not scheduled"
                )
                source = f"({reminder.source})" if reminder.source else ""

                message += f"{i}. *{reminder.reminder_name}* {source}\n"
                message += f"   {recurring} • Next: {next_time}\n\n"

            send_message(settings.bot_token, chat_id, message)

        except Exception as e:
            logger.error(f"Failed to list reminders for user {chat_id}: {e}")
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Failed to fetch reminders. Please try again.",
            )

        return {"status": "ok"}

    # Handle /notion command
    if text == "/notion":
        has_token = bool(user.notion_api_key)

        if has_token:
            state.set_flow(FlowType.NOTION, NotionStep.MENU.value)
            send_notion_menu(chat_id, user)
        else:
            state.set_flow(FlowType.NOTION, NotionStep.TOKEN.value)
            send_notion_menu(chat_id, user)

        return {"status": "ok"}

    # Handle /settings command
    if text == "/settings":
        state.set_flow(FlowType.SETTINGS, 0)
        send_settings_menu(chat_id, user)
        return {"status": "ok"}

    # Handle /cancel command (exit any flow)
    if text in ("/cancel", "cancel"):
        clear_user_state(chat_id)
        send_message(settings.bot_token, chat_id, "❌ Cancelled. All progress cleared.")
        return {"status": "ok"}

    # ============================================
    # FLOW ROUTING
    # ============================================

    # Route to appropriate flow handler
    if state.flow_type == FlowType.NOTION:
        await handle_notion_flow(chat_id, text, user, state, db)
        return {"status": "ok"}

    elif state.flow_type == FlowType.SETTINGS:
        await handle_settings_flow(chat_id, text, user, state, db)
        return {"status": "ok"}

    elif state.flow_type == FlowType.REMINDER:
        await handle_reminder_flow(chat_id, text, state, db)
        return {"status": "ok"}

    # No active flow - show help
    else:
        send_message(
            settings.bot_token,
            chat_id,
            "I didn't understand that command. 🤔\n\n"
            "Try:\n"
            "• /start - Welcome message\n"
            "• /add - Create reminder\n"
            "• /list - View reminders\n"
            "• /notion - Notion integration\n"
            "• /settings - Configure settings\n"
            "• /help - Detailed help",
        )
        return {"status": "ok"}


# ============================================
# SETTINGS API ENDPOINTS
# ============================================


class SettingsPayload(BaseModel):
    chat_id: str
    notion_enabled: Optional[bool] = None
    notion_check_frequence: Optional[int] = None


@router.get("/settings/{chat_id}")
def get_settings(chat_id: str, db: Session = Depends(get_session)):
    """Get user settings."""
    try:
        user = db.get(Users, str(chat_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "chat_id": user.chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "notion_enabled": bool(user.notion_enabled),
            "notion_db_pages": user.notion_db_pages or [],
            "notion_db_mappings": user.notion_db_mappings or [],
            "notion_check_frequence": getattr(user, "notion_check_frequence", 12),
            "has_notion_token": bool(user.notion_api_key),
            "last_active_at": (
                user.last_active_at.isoformat() if user.last_active_at else None
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get settings for user {chat_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/settings")
def update_settings(payload: SettingsPayload, db: Session = Depends(get_session)):
    """Update user settings."""
    try:
        user = db.get(Users, str(payload.chat_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        changed = False

        if payload.notion_enabled is not None:
            user.notion_enabled = bool(payload.notion_enabled)
            changed = True

        if payload.notion_check_frequence is not None:
            if payload.notion_check_frequence not in (12, 24):
                raise HTTPException(
                    status_code=400, detail="Invalid frequency. Allowed values: 12, 24"
                )
            user.notion_check_frequence = int(payload.notion_check_frequence)
            changed = True

        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

        return {
            "status": "ok",
            "message": (
                "Settings updated successfully" if changed else "No changes made"
            ),
            "settings": {
                "notion_enabled": bool(user.notion_enabled),
                "notion_check_frequence": getattr(user, "notion_check_frequence", 12),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update settings for user {payload.chat_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/settings/{chat_id}/notion")
def reset_notion_integration(chat_id: str, db: Session = Depends(get_session)):
    """Reset Notion integration for a user."""
    try:
        user = db.get(Users, str(chat_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.notion_api_key = None
        user.notion_enabled = False
        user.notion_db_pages = []
        user.notion_db_mappings = []

        db.add(user)
        db.commit()

        return {"status": "ok", "message": "Notion integration reset successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset Notion integration for user {chat_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "notification-router",
        "timestamp": datetime.utcnow().isoformat(),
    }
