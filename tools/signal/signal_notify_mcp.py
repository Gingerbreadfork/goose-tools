# MCP server: send_notification over Signal (tool name/signature kept stable so recipes need no change).
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from typing import Optional
from mcp.server.fastmcp import FastMCP
import signal_lib as sg

mcp = FastMCP("notify")

@mcp.tool()
def send_notification(title: str, message: str, priority: int = 3, tags: Optional[str] = None, click_url: Optional[str] = None,
                      attachment_path: Optional[str] = None) -> str:
    """Send the user a Signal message on their phone. `title` short; `message` markdown (headings, bullets, links and bold are
    converted to Signal formatting). Images referenced by gallery URL or local path are attached automatically; `attachment_path`
    adds a specific file. `priority` 1-5 only affects the title (4-5 prefix it with a warning). `tags` and `click_url` are kept for
    compatibility: click_url is appended as a link."""
    head = ("⚠️ " if int(priority) >= 4 else "") + f"**{title.strip()}**"
    body = sg.md_to_signal(message)
    if click_url: body += f"\n\n{click_url}"
    atts = sg.find_images(message)
    if attachment_path and os.path.isfile(os.path.expanduser(attachment_path)): atts.append(os.path.expanduser(attachment_path))
    if not sg.BOT or not sg.USER: return "error: Signal not configured yet (SIGNAL_BOT_NUMBER / SIGNAL_USER_NUMBER empty)"
    r = sg.send(f"{head}\n\n{body}", attachments=atts)
    return f"sent via Signal (timestamp {r.get('timestamp')}, {len(body)} chars, {len(atts)} attachment(s))"

if __name__ == "__main__":
    mcp.run()
