"""Datetime utilities with timezone support."""
from datetime import datetime, timedelta, timezone

# UTC+8 timezone object
UTC_PLUS_8 = timezone(timedelta(hours=8))


def now_with_tz() -> datetime:
    """Get current datetime in UTC+8 (Asia/Shanghai) timezone.

    Returns:
        datetime: Current datetime with UTC+8 timezone info
    """
    return datetime.now(UTC_PLUS_8)


def utc_to_china(dt: datetime) -> datetime:
    """Convert UTC datetime to China timezone (UTC+8).

    Args:
        dt: datetime object (can be naive or timezone-aware)

    Returns:
        datetime: datetime in UTC+8 timezone
    """
    if dt.tzinfo is None:
        # If naive, assume it's UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(UTC_PLUS_8)
