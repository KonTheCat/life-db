from fastmcp import FastMCP

from services.graph import graph_request


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def list_calendars() -> list[dict]:
        """List the signed-in user's calendars."""
        return graph_request("GET", "/me/calendars").get("value", [])

    @mcp.tool
    def list_events(
        start: str, end: str, calendar_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """List events between two ISO 8601 UTC timestamps.

        calendar_id: omit for the default calendar.
        """
        base = f"/me/calendars/{calendar_id}" if calendar_id else "/me"
        params = {"startDateTime": start, "endDateTime": end, "$top": limit}
        return graph_request("GET", f"{base}/calendarView", params=params).get("value", [])

    @mcp.tool
    def create_event(
        subject: str,
        start: str,
        end: str,
        body: str | None = None,
        location: str | None = None,
        calendar_id: str | None = None,
        timezone: str = "UTC",
    ) -> dict:
        """Create a calendar event. start/end are ISO 8601 timestamps."""
        payload = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
        }
        if body:
            payload["body"] = {"contentType": "text", "content": body}
        if location:
            payload["location"] = {"displayName": location}
        path = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"
        return graph_request("POST", path, json=payload)

    @mcp.tool
    def update_event(event_id: str, fields: dict) -> dict:
        """Update an event. fields may include any of subject/start/end/body/location;
        start/end should be {"dateTime": ..., "timeZone": ...} objects if provided.
        """
        return graph_request("PATCH", f"/me/events/{event_id}", json=fields)

    @mcp.tool
    def delete_event(event_id: str) -> dict:
        """Delete a calendar event."""
        graph_request("DELETE", f"/me/events/{event_id}")
        return {"deleted": event_id}

    @mcp.tool
    def get_free_busy(start: str, end: str, emails: list[str] | None = None) -> dict:
        """Get free/busy schedule for the signed-in user (or other emails,
        if they've shared their calendar) between two ISO 8601 timestamps.
        """
        payload = {
            "schedules": emails or ["me"],
            "startTime": {"dateTime": start, "timeZone": "UTC"},
            "endTime": {"dateTime": end, "timeZone": "UTC"},
            "availabilityViewInterval": 30,
        }
        return graph_request("POST", "/me/calendar/getSchedule", json=payload)
