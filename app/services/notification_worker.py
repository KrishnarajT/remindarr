import asyncio
import datetime
from typing import Optional
import pytz

from sqlmodel import select

from app.db import config_db
from app.db.models import Reminders, Users
from app.constants.constants import settings
from app.services.telegram import send_message
from app.utils.logging_utils import logger
from app.utils.time_utils import format_datetime_for_user


CHECK_INTERVAL_SECONDS = 60  # how often to poll for due reminders


async def _reminder_loop(app) -> None:
    """Background loop: query due reminders, send messages, reschedule."""
    engine = config_db.engine
    # use a stop event stored on the app state to allow graceful shutdown
    stop_event: asyncio.Event = app.state._reminder_stop

    while not stop_event.is_set():
        try:
            utc_now = datetime.datetime.now(pytz.UTC)
            
            # Use a DB session to select due reminders and lock rows to avoid double-processing
            with config_db.Session(engine) as db:
                # Get all due reminders with user info for timezone handling
                stmt = (
                    select(Reminders, Users)
                    .join(Users, Reminders.chat_id == Users.chat_id)
                    .where(Reminders.active == True)
                    .where(Reminders.next_trigger_at != None)
                    .where(Reminders.next_trigger_at <= utc_now)
                    .with_for_update(skip_locked=True)
                )

                results = db.exec(stmt).all()

                for reminder, user in results:
                    try:
                        target_chat = reminder.chat_id or settings.chat_id
                        if not target_chat:
                            logger.error(f"No chat_id available for reminder {reminder.id}; skipping")
                            continue

                        # Format the reminder time in user's timezone
                        local_time = format_datetime_for_user(utc_now, user.timezone)
                        
                        # Add timezone context to the message
                        message = (
                            f"{reminder.reminder_content}\n\n"
                            f"⏰ Triggered at: {local_time}"
                        )
                        send_message(settings.bot_token, target_chat, message)

                        # update last_triggered_at
                        reminder.last_triggered_at = utc_now

                        # Handle one-time vs recurring reminders
                        if reminder.interval_minutes is None:
                            # One-time reminder: mark inactive after sending
                            reminder.active = False
                            reminder.next_trigger_at = None  # Clear next trigger time
                        elif reminder.interval_minutes > 0:
                            # Recurring reminder: schedule next occurrence
                            reminder.next_trigger_at = utc_now + datetime.timedelta(minutes=reminder.interval_minutes)

                            # Log next trigger time in user's timezone
                            next_local = format_datetime_for_user(reminder.next_trigger_at, user.timezone)
                            logger.info(
                                f"Scheduled next reminder {reminder.id} for {next_local} "
                                f"(User: {user.first_name or user.chat_id})"
                            )
                        else:
                            # Invalid interval (0 or negative): mark inactive
                            logger.warning(f"Reminder {reminder.id} has invalid interval_minutes: {reminder.interval_minutes}")
                            reminder.active = False
                            reminder.next_trigger_at = None

                        db.add(reminder)

                    except Exception as e:
                        logger.error(f"Failed to send reminder {reminder.id}: {e}")

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
