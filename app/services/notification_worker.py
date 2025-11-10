import asyncio
import datetime
from typing import Optional

from sqlmodel import select

from app.db import config_db
from app.db.models import Reminders
from app.constants.constants import settings
from app.services.telegram import send_message
from app.utils.logging_utils import logger


CHECK_INTERVAL_SECONDS = 60  # how often to poll for due reminders


async def _reminder_loop(app) -> None:
    """Background loop: query due reminders, send messages, reschedule."""
    engine = config_db.engine
    # use a stop event stored on the app state to allow graceful shutdown
    stop_event: asyncio.Event = app.state._reminder_stop

    while not stop_event.is_set():
        try:
            now = datetime.datetime.utcnow()
            # Use a DB session to select due reminders and lock rows to avoid double-processing
            with config_db.Session(engine) as db:
                stmt = (
                    select(Reminders)
                    .where(Reminders.active == True)
                    .where(Reminders.next_trigger_at != None)
                    .where(Reminders.next_trigger_at <= now)
                    .with_for_update(skip_locked=True)
                )

                results = db.exec(stmt).all()

                for r in results:
                    try:
                        target_chat: Optional[str] = r.chat_id or settings.chat_id
                        if not target_chat:
                            logger.error(f"No chat_id available for reminder {r.id}; skipping")
                            continue

                        send_message(settings.bot_token, target_chat, r.reminder_content)

                        # update last_triggered_at
                        r.last_triggered_at = now

                        # Handle one-time vs recurring reminders
                        if r.interval_minutes is None:
                            # One-time reminder: mark inactive after sending
                            r.active = False
                            r.next_trigger_at = None  # Clear next trigger time
                        elif r.interval_minutes > 0:
                            # Recurring reminder: schedule next occurrence
                            r.next_trigger_at = now + datetime.timedelta(minutes=r.interval_minutes)
                        else:
                            # Invalid interval (0 or negative): mark inactive
                            logger.warning(f"Reminder {r.id} has invalid interval_minutes: {r.interval_minutes}")
                            r.active = False
                            r.next_trigger_at = None

                        db.add(r)

                    except Exception as e:
                        logger.error(f"Failed to send reminder {r.id}: {e}")

                db.commit()

        except Exception as e:
            logger.error(f"Reminder worker error: {e}")

        # Sleep but wake earlier if stop signal set
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            # timeout expired, loop again
            continue


def start_worker(app) -> None:
    """Start the reminder background task. Call from an async startup handler."""
    # create stop event and background task
    app.state._reminder_stop = asyncio.Event()
    app.state._reminder_task = asyncio.create_task(_reminder_loop(app))


async def stop_worker(app) -> None:
    """Signal the worker to stop and await its completion. Call from async shutdown handler."""
    if not hasattr(app.state, "_reminder_stop"):
        return
    app.state._reminder_stop.set()
    # await task if present
    task = getattr(app.state, "_reminder_task", None)
    if task:
        await task
