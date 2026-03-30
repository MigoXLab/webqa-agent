"""Cron expression utilities."""
from datetime import datetime
from typing import List, Optional, Tuple

import pytz
from croniter import croniter


def validate_cron_expression(cron_expression: str) -> Tuple[bool, Optional[str]]:
    """Validate cron expression.

    Args:
        cron_expression: Cron expression string (e.g., "0 8 * * *")

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Check if expression is valid
        if not croniter.is_valid(cron_expression):
            return False, 'Invalid cron expression format'

        # Try to create croniter instance
        croniter(cron_expression, datetime.now())
        return True, None
    except Exception as e:
        return False, str(e)


def get_next_run_times(cron_expression: str, count: int = 5) -> List[datetime]:
    """Get next N run times for a cron expression in UTC+8 timezone.

    Args:
        cron_expression: Cron expression string
        count: Number of next run times to return (default: 5)

    Returns:
        List of next run times in UTC+8 timezone
    """
    try:
        # Use UTC+8 timezone
        tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz)

        # Create croniter instance
        cron = croniter(cron_expression, now)

        # Get next N run times
        next_times = []
        for _ in range(count):
            next_time = cron.get_next(datetime)
            next_times.append(next_time)

        return next_times
    except Exception:
        return []


def get_next_run_time(cron_expression: str, base_time: Optional[datetime] = None) -> Optional[datetime]:
    """Get the next run time for a cron expression.

    Args:
        cron_expression: Cron expression string
        base_time: Base time to calculate from (default: now in UTC+8)

    Returns:
        Next run time in UTC+8 timezone, or None if invalid
    """
    try:
        # Use UTC+8 timezone
        tz = pytz.timezone('Asia/Shanghai')
        if base_time is None:
            base_time = datetime.now(tz)
        elif base_time.tzinfo is None:
            # Add timezone if not present
            base_time = tz.localize(base_time)

        # Create croniter instance
        cron = croniter(cron_expression, base_time)

        # Get next run time
        next_time = cron.get_next(datetime)
        return next_time
    except Exception:
        return None
