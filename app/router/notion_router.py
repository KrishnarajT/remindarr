from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlmodel import select

from app.db.config_db import get_session
from app.db.models import Users
from app.services.telegram import send_message
from app.constants.constants import settings
from app.utils.logging_utils import logger

router = APIRouter(prefix="/notion", tags=["notion"])

# Temporary in-memory state store for ongoing conversations
notion_setup_states = {}

@router.post("/webhook")
async def notion_webhook(request: Request, db: Session = Depends(get_session)):
    try:
        data = await request.json()
        logger.info(f"Incoming Notion webhook data: {data}")
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return {"status": "error", "reason": "invalid JSON"}

    # Get or create state for this chat
    if chat_id not in notion_setup_states:
        notion_setup_states[chat_id] = {"step": 0}

    state = notion_setup_states[chat_id]

    # Initialize with /start command
    if text == "/start":
        send_message(
            settings.bot_token,
            chat_id,
            f"👋 Hi {data['message']['from'].get('first_name', 'there')}!\n\n"
            "I'm your reminder bot. I can:\n"
            "• Set one-time or recurring reminders (/add)\n"
            "• Connect to your Notion workspace (/notion)\n"
            "\nWhat would you like to do?"
        )
        return {"status": "ok"}

    # Start setup with /notion command
    if text == "/notion":
        send_message(
            settings.bot_token, 
            chat_id, 
            "Let's set up your Notion integration!\n\n"
            "1. Go to https://www.notion.so/my-integrations\n"
            "2. Click '+ New integration'\n"
            "3. Name it 'Remindarr' and select your workspace\n"
            "4. Copy the 'Internal Integration Token'\n"
            "5. Send it to me here\n\n"
            "Your token will be encrypted and stored securely."
        )
        state["step"] = 1
        return {"status": "ok"}

    # Get API key
    if state["step"] == 1:
        # Basic validation of Notion token format (starts with 'secret_')
        if not text.startswith("secret_"):
            send_message(
                settings.bot_token,
                chat_id,
                "That doesn't look like a valid Notion token. "
                "It should start with 'secret_'. Please try again or type /notion to restart."
            )
            return {"status": "ok"}

        try:
            # Get or create user
            user = db.get(Users, str(chat_id))
            if not user:
                logger.error(f"User {chat_id} not found during Notion setup")
                send_message(
                    settings.bot_token,
                    chat_id,
                    "❌ Error: Please start a conversation with me first using /start"
                )
                return {"status": "error", "reason": "user not found"}

            # Update Notion settings
            user.notion_api_key = text
            user.notion_enabled = True
            db.add(user)
            db.commit()

            # TODO: Validate the token by making a test API call to Notion
            # For now we just assume it works

            send_message(
                settings.bot_token,
                chat_id,
                "✅ Notion integration set up successfully!\n\n"
                "Your reminders will be synced with Notion. "
                "You can update this integration anytime with /notion"
            )

        except Exception as e:
            logger.error(f"Failed to save Notion settings: {e}")
            send_message(
                settings.bot_token,
                chat_id,
                "❌ Sorry, something went wrong saving your Notion integration. "
                "Please try again later or contact support."
            )

        # Clear setup state
        del notion_setup_states[chat_id]
        return {"status": "ok"}

    send_message(
        settings.bot_token,
        chat_id,
        "To set up Notion integration, send /notion"
    )
    return {"status": "ok"}