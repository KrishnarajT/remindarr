from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.db.config_db import get_session
from app.db.models import Reminders, Users
from app.services.telegram import send_message
from app.constants.constants import settings
from app.utils.logging_utils import logger
from app.utils.time_utils import parse_time_unit, calculate_next_trigger
from datetime import datetime, timedelta
from sqlmodel import select

async def get_or_create_user(db: Session, telegram_data: dict) -> Users:
    """Get existing user or create new one from Telegram data."""
    message = telegram_data["message"]
    from_user = message["from"]
    chat = message["chat"]
    
    # Try to find existing user
    user = db.get(Users, str(chat["id"]))
    
    if not user:
        # Create new user
        user = Users(
            chat_id=str(chat["id"]),
            username=from_user.get("username"),
            first_name=from_user.get("first_name"),
            language_code=from_user.get("language_code"),
            is_bot=from_user.get("is_bot", False),
        )
        db.add(user)
    else:
        # Update user info if changed
        user.username = from_user.get("username", user.username)
        user.first_name = from_user.get("first_name", user.first_name)
        user.language_code = from_user.get("language_code", user.language_code)
        user.last_active_at = datetime.utcnow()
        db.add(user)
    
    db.commit()
    return user

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Temporary in-memory state store for ongoing conversations
user_states = {}

@router.get("/test")
async def test_notification(db: Session = Depends(get_session)):
    try:
        send_message(settings.bot_token, settings.chat_id, "Hi from Remindarr!")
        return {"status": "success", "message": "Test notification sent"}
    except Exception as e:
        logger.info(f"Failed to send test notification: {e}")
        return {"status": "error", "message": str(e)}
from fastapi.responses import JSONResponse

@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_session)):
    try:
        # Try to parse JSON body
        body = await request.body()
        if not body:
            logger.warning("Received empty webhook body")
            return JSONResponse(content={"status": "ignored", "reason": "empty body"})

        data = await request.json()
        logger.info(f"Incoming Telegram data: {data}")

        # Create or update user record
        user = await get_or_create_user(db, data)
        
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return JSONResponse(content={"status": "error", "reason": "invalid JSON"})

    # Ignore any non-message updates (edited, callback, etc.)
    if "message" not in data:
        return JSONResponse(content={"status": "ignored", "reason": "no message field"})

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip()

    # --- rest of your logic unchanged ---

    # Conversation state tracking
    if chat_id not in user_states:
        user_states[chat_id] = {"step": 0, "data": {}}

    state = user_states[chat_id]

    # Step 0: User starts with /add
    if text == "/add":
        send_message(settings.bot_token, chat_id, "Let's create a new reminder! What should I name it?")
        state["step"] = 1
        return {"status": "ok"}

    # Step 1: Get name
    if state["step"] == 1:
        state["data"]["name"] = text
        send_message(settings.bot_token, chat_id, "Should this be a one-time reminder or recurring? Reply with: once/recurring")
        state["step"] = 2
        return {"status": "ok"}

    # Step 2: Get reminder type (one-time vs recurring)
    if state["step"] == 2:
        reminder_type = text.strip().lower()
        if reminder_type in ("once", "one-time", "onetime", "one"):
            state["data"]["is_recurring"] = False
        elif reminder_type in ("recurring", "repeat", "repeating"):
            state["data"]["is_recurring"] = True
        else:
            send_message(settings.bot_token, chat_id, "Please reply with either 'once' or 'recurring'.")
            return {"status": "ok"}

        send_message(settings.bot_token, chat_id, "When should I remind you? Reply with one of: minutes/hours/days")
        state["step"] = 3
        return {"status": "ok"}

    # Step 3: Get time unit
    if state["step"] == 3:
        multiplier, unit = parse_time_unit(text)
        if not multiplier or not unit:
            send_message(settings.bot_token, chat_id, "Please reply with 'minutes', 'hours', or 'days'.")
            return {"status": "ok"}

        state["data"]["unit"] = unit
        state["data"]["multiplier"] = multiplier
        send_message(settings.bot_token, chat_id, f"How many {unit} until I should remind you?")
        state["step"] = 4
        return {"status": "ok"}

    # Step 4: Get numeric amount
    if state["step"] == 4:
        try:
            amount = int(text)
            state["data"]["amount"] = amount
            send_message(settings.bot_token, chat_id, "What message should I send when reminding you?")
            state["step"] = 5
        except ValueError:
            send_message(settings.bot_token, chat_id, "Please enter a valid whole number for the amount.")
        return {"status": "ok"}

    # Step 5: Get content and save
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
            interval_minutes=interval_minutes,  # None for one-time
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

        # Clear conversation
        del user_states[chat_id]
        return {"status": "ok"}

    send_message(settings.bot_token, chat_id, "Please send /add to start creating a new reminder.")
    return {"status": "ok"}
