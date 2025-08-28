from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.telegram import send_message
from ..config import settings

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("/test")
async def test_notification(db: Session = Depends(get_db)):
    try:
        await send_message(settings.bot_token, settings.chat_id, "Hi from Remindarr!")
        return {"status": "success", "message": "Test notification sent"}
    except Exception as e:
        return {"status": "error", "message": str(e)}