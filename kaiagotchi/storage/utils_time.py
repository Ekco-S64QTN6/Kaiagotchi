# kaiagotchi/storage/utils_time.py
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

TZ = ZoneInfo("America/Chicago")


def now_cst_iso() -> str:
    """Return current time in America/Chicago as ISO string with offset."""
    return datetime.now(tz=TZ).isoformat()


def to_cst_iso(dt: datetime) -> str:
    """Convert a naive or timezone-aware datetime to CST ISO string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    else:
        dt = dt.astimezone(TZ)
    return dt.isoformat()
