import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def get_current_time() -> dict:
        """The current time, in UTC and in the user's configured local timezone.

        Call this before computing a relative due_at/start/end (e.g. "in 20
        minutes", "tomorrow at 9am") instead of guessing the current time —
        estimates drift and cause notifications/events to fire at the wrong
        moment.
        """
        now_utc = datetime.now(timezone.utc)
        tz_name = os.environ.get("USER_TIMEZONE", "UTC")
        now_local = now_utc.astimezone(ZoneInfo(tz_name))
        return {
            "utc": now_utc.isoformat(),
            "local": now_local.isoformat(),
            "timezone": tz_name,
        }
