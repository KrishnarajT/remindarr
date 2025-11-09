from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.config_db import get_session
from app.services.telegram import send_message
from app.constants.constants import settings
from app.utils.logging_utils import logger
router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("/test")
async def test_notification(db: Session = Depends(get_session)):
    try:
        send_message(settings.bot_token, settings.chat_id, "Hi from Remindarr!")
        return {"status": "success", "message": "Test notification sent"}
    except Exception as e:
        logger.info(f"Failed to send test notification: {e}")
        return {"status": "error", "message": str(e)}