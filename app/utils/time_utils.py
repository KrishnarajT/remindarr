"""Time utilities: parsing units, timezone helpers, and scheduling helpers.

This module combines time parsing and timezone helpers used across the app.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

try:
    # Preferred: use stdlib zoneinfo
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


def parse_time_unit(unit_text: str) -> Tuple[Optional[int], Optional[str]]:
    """Convert user input time unit to multiplier and normalized unit name.

    Returns (multiplier_in_minutes, normalized_unit_name) or (None, None) if
    the unit isn't recognized.
    """
    unit = unit_text.strip().lower()

    if unit in ("m", "min", "mins", "minute", "minutes"):
        return 1, "minutes"
    elif unit in ("h", "hr", "hrs", "hour", "hours"):
        return 60, "hours"
    elif unit in ("d", "day", "days"):
        return 60 * 24, "days"

    return None, None


def get_user_timezone(tz_name: Optional[str]):
    """Return a timezone object (ZoneInfo) or UTC on error/None."""
    if not tz_name:
        return ZoneInfo("UTC") if ZoneInfo else timezone.utc

    try:
        return ZoneInfo(tz_name) if ZoneInfo else timezone.utc
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC") if ZoneInfo else timezone.utc


def get_time_in_timezone(dt: datetime, tz_name: Optional[str]) -> datetime:
    """Convert a naive or UTC datetime to the user's timezone.

    The returned datetime will have tzinfo set to the user's tz.
    """
    if dt.tzinfo is None:
        # assume naive datetimes are UTC
        dt = dt.replace(tzinfo=timezone.utc)

    user_tz = get_user_timezone(tz_name)
    return dt.astimezone(user_tz)


def now_in_timezone(tz_name: Optional[str]) -> Tuple[datetime, datetime]:
    """Return (utc_now, local_now) where local_now is utc_now in user's tz."""
    utc_now = datetime.now(timezone.utc)
    user_tz = get_user_timezone(tz_name)
    local_now = utc_now.astimezone(user_tz)
    return utc_now, local_now


def format_datetime_for_user(dt: datetime, tz_name: Optional[str]) -> str:
    """Format datetime in user's timezone for display."""
    local_dt = get_time_in_timezone(dt, tz_name)
    tz_abbr = local_dt.tzname() or "UTC"
    return f"{local_dt.strftime('%Y-%m-%d %H:%M')} {tz_abbr}"


def calculate_next_trigger(
    amount: int,
    multiplier: int,
    is_recurring: bool,
    timezone: Optional[str] = None,
) -> Tuple[Optional[int], datetime]:
    """Calculate interval_minutes and next_trigger_at in UTC.

    - amount: numeric amount in the chosen unit
    - multiplier: minutes per unit (e.g. 60 for hours)
    - is_recurring: whether the reminder should repeat
    - timezone: optional user timezone (currently used only to determine "now")

    Returns (interval_minutes_or_None, next_trigger_at_utc)
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if multiplier <= 0:
        raise ValueError("Multiplier must be positive")

    total_minutes = amount * multiplier
    utc_now, _ = now_in_timezone(timezone)
    next_trigger_at = utc_now + timedelta(minutes=total_minutes)

    interval_minutes = total_minutes if is_recurring else None
    return interval_minutes, next_trigger_at