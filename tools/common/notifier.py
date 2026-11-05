"""Outbound notifications with pluggable backends, chosen by NOTIFY_BACKEND:
  signal   signal-cli-rest-api (SIGNAL_API, SIGNAL_BOT_NUMBER, SIGNAL_USER_NUMBER)   -- also used by the two-way bridge
  ntfy     ntfy server (NTFY_URL, NTFY_TOPIC)
  command  run NOTIFY_COMMAND with the message on stdin (e.g. a script that posts to Telegram/Discord)
  stdout   print (default; useful for testing)
"""
import json, os, subprocess, sys, urllib.request

BACKEND = os.environ.get("NOTIFY_BACKEND", "stdout").lower()


def send(text: str, title: str | None = None, attachments: list[str] | None = None) -> str:
    if BACKEND == "signal":
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal"))
        import signal_lib as sg
        body = (f"**{title}**\n\n" if title else "") + text
        r = sg.send(body, attachments=attachments or [])
        return f"sent via Signal ({r.get('timestamp')})"
    if BACKEND == "ntfy":
        url = os.environ["NTFY_URL"].rstrip("/") + "/" + os.environ["NTFY_TOPIC"]
        headers = {"Markdown": "yes"}
        if title: headers["Title"] = title.encode("ascii", "ignore").decode()
        req = urllib.request.Request(url, data=text.encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return "sent via ntfy (" + json.load(r).get("id", "?") + ")"
    if BACKEND == "command":
        p = subprocess.run(os.environ["NOTIFY_COMMAND"], shell=True, input=((title + "\n\n") if title else "") + text, text=True, capture_output=True, timeout=60)
        return "sent via command" if p.returncode == 0 else f"command failed: {p.stderr[-200:]}"
    print(((title + "\n") if title else "") + text, flush=True)
    return "printed (NOTIFY_BACKEND=stdout)"
