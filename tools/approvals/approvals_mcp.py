# MCP server: ask the user for a yes/no decision over Signal and wait for the reply.
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal"))
from mcp.server.fastmcp import FastMCP
import approvals as ap
import signal_lib as sg

mcp = FastMCP("approvals")


@mcp.tool()
def ask_approval(question: str, timeout_min: int = 60, details: str = "") -> str:
    """Ask the user a yes/no question on their phone (Signal) and wait for the answer. Use before anything irreversible,
    costly or surprising: deleting files, sending messages on their behalf, upgrades, purchases, long jobs. `question` is
    one clear sentence; `details` optional context. Returns 'approved', 'denied' or 'no answer' (after timeout_min, max 180).
    If denied or unanswered, do not proceed; say so."""
    timeout_min = max(1, min(int(timeout_min), 180))
    item = ap.create(question, timeout_min)
    msg = f"❓ **Approval needed** [{item['id']}]\n\n{question.strip()}" + (f"\n\n{details.strip()}" if details.strip() else "") + \
          f"\n\nReply **yes** or **no** (within {timeout_min} min)."
    sg.send(msg)
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        time.sleep(3)
        cur = ap.get(item["id"])
        if cur and cur["status"] in ("approved", "denied"):
            return f"{cur['status']} (user replied: {cur['answer']!r})"
    cur = ap.get(item["id"])
    if cur and cur["status"] == "pending":
        cur["status"] = "expired"; items = ap.load()
        for x in items:
            if x["id"] == cur["id"]: x["status"] = "expired"
        ap.save(items)
    return "no answer (timed out)"


@mcp.tool()
def pending_approvals() -> list:
    """Approval questions still waiting for the user's reply."""
    return [{"id": x["id"], "question": x["question"], "minutes_left": int((x["expires"] - time.time()) / 60)} for x in ap.pending()]


if __name__ == "__main__":
    mcp.run()
