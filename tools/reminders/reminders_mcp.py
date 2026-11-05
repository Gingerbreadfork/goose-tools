# MCP server: reminders and timers delivered to the user's phone via Signal.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from typing import Optional
from mcp.server.fastmcp import FastMCP
import reminders_store as rs

mcp = FastMCP("reminders")


@mcp.tool()
def set_reminder(text: str, when: str, repeat: Optional[str] = None) -> str:
    """Set a reminder; it is delivered to the user (via the configured notifier) at the time. `when` accepts '+20m', '+2h', '+1d', '18:30',
    '7am', 'tomorrow 09:00', 'fri 17:00', 'tonight 8pm', '2026-12-01 10:00' (server local time). `repeat`: none, daily,
    weekdays, weekly, monthly, hourly. Convert what the user said into one of these forms; use the current time from the
    context for relative requests. Returns the reminder with its id."""
    try:
        item = rs.add(text, when, repeat)
    except ValueError as e:
        return f"error: {e}"
    return "Set: " + rs.describe(item)


@mcp.tool()
def list_reminders() -> str:
    """All pending reminders, soonest first, with ids."""
    items = rs.pending()
    return "\n".join(rs.describe(i) for i in items) if items else "No reminders set."


@mcp.tool()
def cancel_reminder(reminder_id: str) -> str:
    """Cancel a reminder by id (from list_reminders). Use 'all' to clear every reminder."""
    if reminder_id == "all":
        n = len(rs.load()); rs.save([]); return f"Cancelled {n} reminder(s)."
    return "Cancelled." if rs.remove(reminder_id) else f"No reminder with id {reminder_id}."


if __name__ == "__main__":
    mcp.run()
