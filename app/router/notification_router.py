from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlmodel import select
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
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

# In-memory state stores
user_states = {}  # Reminder creation flow
notion_setup_states = {}  # Notion setup flow


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
    else:
        user.username = from_user.get("username", user.username)
        user.first_name = from_user.get("first_name", user.first_name)
        user.language_code = from_user.get("language_code", user.language_code)
        user.last_active_at = datetime.utcnow()
        db.add(user)

    db.commit()
    return user


@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_session)):
    try:
        body = await request.body()
        if not body:
            logger.warning("Received empty webhook body")
            return JSONResponse(content={"status": "ignored", "reason": "empty body"})

        data = await request.json()
        logger.info(f"Incoming Telegram data: {data}")

        if "message" not in data:
            return JSONResponse(
                content={"status": "ignored", "reason": "no message field"}
            )

        # Create or update user record
        user = await get_or_create_user(db, data)
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()

    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return JSONResponse(content={"status": "error", "reason": "invalid JSON"})

    # --------------------------
    # NOTION INTEGRATION FLOW
    # --------------------------
    if chat_id in notion_setup_states:
        state = notion_setup_states[chat_id]

        # STEP 0: user already has a token; handle option commands
        if state.get("step") == 0:
            cmd = text.strip().lower()
            if cmd in ("add", "add db", "add database"):
                state["step"] = 2
                notion_setup_states[chat_id] = state
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Send the Notion database ID or the database URL you want me to monitor.",
                )
                return {"status": "ok"}

            if cmd.startswith("http") or re.search(r"[0-9a-fA-F\-]{32,36}", cmd):
                state["step"] = 2
                notion_setup_states[chat_id] = state

            if cmd in ("remove", "remove db", "remove database"):
                pages = user.notion_db_pages or []
                if not pages:
                    send_message(
                        settings.bot_token,
                        chat_id,
                        "You don't have any Notion databases saved.",
                    )
                    del notion_setup_states[chat_id]
                    return {"status": "ok"}
                listing = "\n".join([f"{i+1}. {p}" for i, p in enumerate(pages)])
                send_message(
                    settings.bot_token,
                    chat_id,
                    f"Your monitored databases:\n{listing}\n\nReply with the number of the database you want to remove.",
                )
                state["step"] = 6
                notion_setup_states[chat_id] = state
                return {"status": "ok"}

            if cmd in ("change token", "change api", "change notion token"):
                state["step"] = 1
                notion_setup_states[chat_id] = state
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Please send the new Notion integration token (starts with 'secret_' or 'ntn_').",
                )
                return {"status": "ok"}

            if cmd.startswith("freq"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1] in ("12", "24"):
                    user.notion_check_frequence = int(parts[1])
                    db.add(user)
                    db.commit()
                    send_message(
                        settings.bot_token,
                        chat_id,
                        f"Notion refresh frequency set to {parts[1]} hours.",
                    )
                    del notion_setup_states[chat_id]
                    return {"status": "ok"}
                else:
                    send_message(
                        settings.bot_token,
                        chat_id,
                        "To change frequency reply with 'freq 12' or 'freq 24'.",
                    )
                    return {"status": "ok"}

            if cmd in ("toggle", "enable", "disable"):
                user.notion_enabled = not bool(user.notion_enabled)
                db.add(user)
                db.commit()
                send_message(
                    settings.bot_token,
                    chat_id,
                    f"Notion integration enabled: {user.notion_enabled}",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

            if cmd == "done":
                del notion_setup_states[chat_id]
                send_message(settings.bot_token, chat_id, "Exited Notion settings.")
                return {"status": "ok"}

        # STEP 1: token submission
        if state.get("step") == 1:
            if not text.startswith(("secret_", "ntn_")):
                send_message(
                    settings.bot_token,
                    chat_id,
                    "That doesn't look like a valid Notion token. It should start with 'secret_' or 'ntn_'.",
                )
                return {"status": "ok"}

            headers = {
                "Authorization": f"Bearer {text}",
                "Notion-Version": "2022-06-28",
            }
            resp = requests.get("https://api.notion.com/v1/users/me", headers=headers)
            if resp.status_code != 200:
                logger.error(
                    f"Notion token validation failed for user {chat_id}: {resp.text}"
                )
                send_message(
                    settings.bot_token,
                    chat_id,
                    "❌ That Notion token seems invalid or expired. Please double-check and send the correct one.",
                )
                return {"status": "ok"}

            try:
                user.notion_api_key = text
                user.notion_enabled = True
                db.add(user)
                db.commit()
                user_info = resp.json()
                notion_user_name = user_info.get("name") or user_info.get(
                    "owner", {}
                ).get("user", {}).get("name", "your Notion account")
                send_message(
                    settings.bot_token,
                    chat_id,
                    f"✅ Notion integration verified successfully! Connected as: {notion_user_name}\n\n"
                    "Now send a Notion database ID/URL to add it, or send 'done' to finish.",
                )
                notion_setup_states[chat_id] = {"step": 2}
                return {"status": "ok"}
            except Exception as e:
                logger.error(f"Failed to save Notion settings: {e}")
                send_message(
                    settings.bot_token,
                    chat_id,
                    "❌ Sorry, something went wrong saving your Notion integration. Please try again later.",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

        # STEP 2: Accept Notion DB IDs (or 'done')
        if state.get("step") == 2:
            if text.strip().lower() == "done":
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Notion database setup complete. You can add more databases later with /notion.",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

            # extract db id from URL or raw id
            m = re.search(r"[0-9a-fA-F\\-]{32,36}", text)
            db_id = m.group(0) if m else text.strip()

            headers = {
                "Authorization": f"Bearer {user.notion_api_key}",
                "Notion-Version": "2022-06-28",
            }
            resp = requests.get(
                f"https://api.notion.com/v1/databases/{db_id}", headers=headers
            )

            if resp.status_code != 200:
                logger.error(
                    f"Failed to fetch database {db_id} for user {chat_id}: {resp.text}"
                )
                send_message(
                    settings.bot_token,
                    chat_id,
                    "❌ Couldn't load that Notion database. Please ensure the integration has access and the ID/URL is correct.",
                )
                return {"status": "ok"}

            db_info = resp.json()
            properties = db_info.get("properties", {})
            prop_names = list(properties.keys())

            state.update({"current_db_id": db_id, "properties": prop_names})
            notion_setup_states[chat_id] = state

            props_text = (
                "\n".join([f"• {p}" for p in prop_names]) or "(no properties found)"
            )
            send_message(
                settings.bot_token,
                chat_id,
                f"Found the following properties in database {db_id}:\n{props_text}\n\n"
                "Please reply with the property name to use as the TASK NAME (the column that contains the task title).",
            )
            state["step"] = 3
            notion_setup_states[chat_id] = state
            return {"status": "ok"}

        # STEP 3: Expecting property name for task name
        if state.get("step") == 3:
            prop = text.strip()
            properties = state.get("properties", [])
            if prop not in properties:
                send_message(
                    settings.bot_token,
                    chat_id,
                    "That property wasn't in the list. Please reply with an exact property name from the list above.",
                )
                return {"status": "ok"}

            state["name_prop"] = prop
            state["step"] = 4
            notion_setup_states[chat_id] = state
            send_message(
                settings.bot_token,
                chat_id,
                "Great — now reply with the property name that contains the TASK TIME (a Date property).",
            )
            return {"status": "ok"}

        # STEP 4: Expecting time/date property
        if state.get("step") == 4:
            prop = text.strip()
            properties = state.get("properties", [])
            if prop not in properties:
                send_message(
                    settings.bot_token,
                    chat_id,
                    "That property wasn't in the list. Please reply with an exact property name from the list above.",
                )
                return {"status": "ok"}

            state["time_prop"] = prop
            state["step"] = 5
            notion_setup_states[chat_id] = state
            send_message(
                settings.bot_token,
                chat_id,
                "Mapping saved. Reply 'yes' to import reminders from this database now, or 'no' to skip importing but keep the mapping.",
            )
            return {"status": "ok"}

        # STEP 5: Confirm import
        if state.get("step") == 5:
            choice = text.strip().lower()
            if choice not in ("yes", "no"):
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Please reply 'yes' or 'no'.",
                )
                return {"status": "ok"}

            db_id = state.get("current_db_id")
            name_prop = state.get("name_prop")
            time_prop = state.get("time_prop")

            # persist db id and mapping on the user (avoid duplicates)
            try:
                pages = user.notion_db_pages or []
                if db_id not in pages:
                    user.notion_db_pages = pages + [db_id]
                mappings = user.notion_db_mappings or []
                mapping = {
                    "db_id": db_id,
                    "name_prop": name_prop,
                    "time_prop": time_prop,
                }
                # replace existing mapping for same db_id if present
                mappings = [m for m in mappings if m.get("db_id") != db_id] + [mapping]
                user.notion_db_mappings = mappings
                db.add(user)
                db.commit()
            except Exception as e:
                logger.error(f"Failed to save notion mapping for user {chat_id}: {e}")
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Failed to save database mapping to your account. Please try again later.",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

            if choice == "no":
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Mapping saved. I won't import now. You can add more DBs or finish by sending 'done'.",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

            # perform import
            headers = {
                "Authorization": f"Bearer {user.notion_api_key}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            }
            qresp = requests.post(
                f"https://api.notion.com/v1/databases/{db_id}/query", headers=headers
            )
            if qresp.status_code != 200:
                logger.error(
                    f"Failed to query database {db_id} for user {chat_id}: {qresp.text}"
                )
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Failed to query the database. Mapping is saved but import failed.",
                )
                del notion_setup_states[chat_id]
                return {"status": "ok"}

            imported = 0
            for page in qresp.json().get("results", []):
                props = page.get("properties", {})
                name_val = None
                time_val = None

                p = props.get(name_prop)
                if p and p.get("type") == "title":
                    arr = p.get("title", [])
                    if arr:
                        name_val = "".join(
                            [t.get("plain_text", "") for t in arr]
                        ).strip()
                elif p:
                    name_val = str(p)

                tp = props.get(time_prop)
                if tp and tp.get("type") == "date":
                    dt = tp.get("date")
                    if dt:
                        time_val = dt.get("start")

                try:
                    reminder = Reminders(
                        reminder_name=(name_val or "(no title)"),
                        reminder_content=(name_val or ""),
                        chat_id=chat_id,
                        source=("notion" if time_val else "user"),
                        notion_page_id=page.get("id"),
                    )
                    if time_val:
                        try:
                            parsed = datetime.fromisoformat(time_val.rstrip("Z"))
                            reminder.next_trigger_at = parsed
                        except Exception:
                            pass

                    db.add(reminder)
                    imported += 1
                except Exception as e:
                    logger.error(
                        f"Failed to create reminder from Notion page for user {chat_id}: {e}"
                    )

            db.commit()
            send_message(
                settings.bot_token,
                chat_id,
                f"Import complete. Created/updated {imported} reminders (source set to 'notion' when a date was present).",
            )

            del notion_setup_states[chat_id]
            return {"status": "ok"}

        # STEP 6: Removal selection
        if state.get("step") == 6:
            pages = user.notion_db_pages or []
            try:
                idx = int(text.strip()) - 1
                if idx < 0 or idx >= len(pages):
                    raise ValueError()
                removed = pages.pop(idx)
                # remove mapping for that db
                mappings = user.notion_db_mappings or []
                mappings = [m for m in mappings if m.get("db_id") != removed]
                user.notion_db_pages = pages
                user.notion_db_mappings = mappings
                db.add(user)
                db.commit()
                send_message(
                    settings.bot_token,
                    chat_id,
                    f"Removed monitoring for database: {removed}",
                )
            except Exception:
                send_message(
                    settings.bot_token,
                    chat_id,
                    "Invalid selection. Please reply with the number of the database to remove.",
                )
                return {"status": "ok"}

            del notion_setup_states[chat_id]
            return {"status": "ok"}
    # --------------------------
    # REMINDER CREATION FLOW
    # --------------------------
    if chat_id not in user_states:
        user_states[chat_id] = {"step": 0, "data": {}}

    state = user_states[chat_id]

    # Step 0: Start
    if text == "/add":
        send_message(
            settings.bot_token,
            chat_id,
            "Let's create a new reminder! What should I name it?",
        )
        state["step"] = 1
        return {"status": "ok"}

    # Step 1: Name
    if state["step"] == 1:
        state["data"]["name"] = text
        send_message(
            settings.bot_token,
            chat_id,
            "Should this be a one-time reminder or recurring? Reply with: once/recurring",
        )
        state["step"] = 2
        return {"status": "ok"}

    # Step 2: Reminder type
    if state["step"] == 2:
        reminder_type = text.strip().lower()
        if reminder_type in ("once", "one-time", "onetime", "one"):
            state["data"]["is_recurring"] = False
        elif reminder_type in ("recurring", "repeat", "repeating"):
            state["data"]["is_recurring"] = True
        else:
            send_message(
                settings.bot_token,
                chat_id,
                "Please reply with either 'once' or 'recurring'.",
            )
            return {"status": "ok"}

        send_message(
            settings.bot_token,
            chat_id,
            "When should I remind you? Reply with one of: minutes/hours/days",
        )
        state["step"] = 3
        return {"status": "ok"}

    # Step 3: Time unit
    if state["step"] == 3:
        multiplier, unit = parse_time_unit(text)
        if not multiplier or not unit:
            send_message(
                settings.bot_token,
                chat_id,
                "Please reply with 'minutes', 'hours', or 'days'.",
            )
            return {"status": "ok"}

        state["data"]["unit"] = unit
        state["data"]["multiplier"] = multiplier
        send_message(
            settings.bot_token, chat_id, f"How many {unit} until I should remind you?"
        )
        state["step"] = 4
        return {"status": "ok"}

    # Step 4: Numeric value
    if state["step"] == 4:
        try:
            amount = int(text)
            state["data"]["amount"] = amount
            send_message(
                settings.bot_token,
                chat_id,
                "What message should I send when reminding you?",
            )
            state["step"] = 5
        except ValueError:
            send_message(
                settings.bot_token,
                chat_id,
                "Please enter a valid whole number for the amount.",
            )
        return {"status": "ok"}

    # Step 5: Save reminder
    if state["step"] == 5:
        is_recurring = state["data"]["is_recurring"]
        interval_minutes, next_trigger_at = calculate_next_trigger(
            amount=state["data"]["amount"],
            multiplier=state["data"]["multiplier"],
            is_recurring=is_recurring,
        )

        reminder = Reminders(
            reminder_name=state["data"]["name"],
            reminder_content=text,
            interval_minutes=interval_minutes,
            next_trigger_at=next_trigger_at,
            chat_id=chat_id,
        )
        db.add(reminder)
        db.commit()

        type_str = "recurring" if is_recurring else "one-time"
        send_message(
            settings.bot_token,
            chat_id,
            f"✅ {type_str.title()} reminder created!\n\n"
            f"Name: {reminder.reminder_name}\n"
            f"In: {state['data']['amount']} {state['data']['unit']}\n"
            f"Message: {reminder.reminder_content}",
        )

        del user_states[chat_id]
        return {"status": "ok"}

    send_message(
        settings.bot_token,
        chat_id,
        "Please send /add to start creating a new reminder.",
    )
    return {"status": "ok"}


# --------------------------
# SETTINGS API
# --------------------------


class SettingsPayload(BaseModel):
    chat_id: str
    notion_enabled: Optional[bool] = None
    notion_check_frequence: Optional[int] = None


@router.get("/settings/{chat_id}")
def get_settings(chat_id: str, db: Session = Depends(get_session)):
    user = db.get(Users, str(chat_id))
    if not user:
        return JSONResponse(content={"status": "not_found"}, status_code=404)

    return {
        "chat_id": user.chat_id,
        "notion_enabled": bool(user.notion_enabled),
        "notion_db_pages": user.notion_db_pages or [],
        "notion_check_frequence": getattr(user, "notion_check_frequence", 12),
    }


@router.post("/settings")
def update_settings(payload: SettingsPayload, db: Session = Depends(get_session)):
    user = db.get(Users, str(payload.chat_id))
    if not user:
        return JSONResponse(content={"status": "not_found"}, status_code=404)

    changed = False
    if payload.notion_enabled is not None:
        user.notion_enabled = bool(payload.notion_enabled)
        changed = True
    if payload.notion_check_frequence is not None:
        if payload.notion_check_frequence in (12, 24):
            user.notion_check_frequence = int(payload.notion_check_frequence)
            changed = True
        else:
            return JSONResponse(
                content={"status": "invalid_frequency", "allowed": [12, 24]},
                status_code=400,
            )

    if changed:
        db.add(user)
        db.commit()

    return {"status": "ok"}
