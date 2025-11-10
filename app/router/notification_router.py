from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.db.config_db import get_session
from app.db.models import Reminders
from app.services.telegram import send_message
from app.constants.constants import settings
from app.utils.logging_utils import logger
from datetime import datetime, timedelta

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
        send_message(settings.bot_token, chat_id, "How many hours until I should remind you?")
        state["step"] = 2
        return {"status": "ok"}

    # Step 2: Get interval hours
    if state["step"] == 2:
        try:
            hours = int(text)
            state["data"]["interval_hours"] = hours
            send_message(settings.bot_token, chat_id, "What message should I send when reminding you?")
            state["step"] = 3
        except ValueError:
            send_message(settings.bot_token, chat_id, "Please enter a valid number of hours.")
        return {"status": "ok"}

    # Step 3: Get content and save
    if state["step"] == 3:
        reminder = Reminders(
            reminder_name=state["data"]["name"],
            reminder_content=text,
            interval_hours=state["data"]["interval_hours"],
            next_trigger_at=datetime.utcnow() + timedelta(hours=state["data"]["interval_hours"]),
        )
        db.add(reminder)
        db.commit()

        send_message(
            settings.bot_token,
            chat_id,
            f"✅ Reminder created!\n\n"
            f"Name: {reminder.reminder_name}\n"
            f"In: {reminder.interval_hours} hours\n"
            f"Message: {reminder.reminder_content}",
        )

        # Clear conversation
        del user_states[chat_id]
        return {"status": "ok"}

    send_message(settings.bot_token, chat_id, "Please send /add to start creating a new reminder.")
    return {"status": "ok"}
