"""Utility functions for handling time and interval inputs."""
from datetime import datetime, timedelta
from typing import Tuple, Optional


def parse_time_unit(unit_text: str) -> Tuple[Optional[int], Optional[str]]:
    """Convert user input time unit to multiplier and normalized unit name."""
    unit = unit_text.strip().lower()
    
    if unit in ("m", "min", "mins", "minute", "minutes"):
        return 1, "minutes"
    elif unit in ("h", "hr", "hrs", "hour", "hours"):
        return 60, "hours"
    elif unit in ("d", "day", "days"):
        return 60 * 24, "days"
    
    return None, None


def calculate_next_trigger(
    amount: int,
    multiplier: int,
    is_recurring: bool,
) -> Tuple[Optional[int], datetime]:
    """Calculate interval_minutes and next_trigger_at for a reminder.
    
    Args:
        amount: The number of units (e.g. 5 hours = amount 5)
        multiplier: Minutes per unit (e.g. 60 for hours)
        is_recurring: If True, sets up recurring interval
    
    Returns:
        Tuple of:
        - interval_minutes: Minutes between recurrences, or None for one-time
        - next_trigger_at: When to first trigger the reminder
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if multiplier <= 0:
        raise ValueError("Multiplier must be positive")

    total_minutes = amount * multiplier
    next_trigger_at = datetime.utcnow() + timedelta(minutes=total_minutes)
    
    # For one-time reminders, interval_minutes is None
    # For recurring, it's the same as the initial wait time
    interval_minutes = total_minutes if is_recurring else None
    
    return interval_minutes, next_trigger_at