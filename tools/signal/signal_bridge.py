# Signal <-> Goose bridge. Listens for messages from the user's number, runs Goose, replies on Signal.
# Commands: /new (start a fresh conversation), /help
import asyncio, json, os, re, sqlite3, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signal_lib as sg
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "approvals"))
import approvals as ap
import websockets

import shutil
GOOSE = os.environ.get("GOOSE_BIN") or shutil.which("goose") or os.path.expanduser("~/.local/bin/goose")
STATE = os.path.expanduser("~/.config/goose/signal-bridge.state")
INBOX = os.path.join(os.path.expanduser(os.environ.get("GOOSE_WORK", "~/goose-work")), "signal-in")
WORKDIR = os.path.expanduser(os.environ.get("BRIDGE_WORKDIR", "~"))
TIMEOUT = int(os.environ.get("BRIDGE_TIMEOUT", "420"))
SESSIONS_DB = os.path.expanduser(os.environ.get("GOOSE_SESSIONS_DB", "~/.local/share/goose/sessions/sessions.db"))

def final_reply(name: str) -> str:
    """The assistant's final text after the last user message, read from Goose's session store (no thinking, no tool chatter)."""
    try:
        c = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True)
        row = c.execute("select id from sessions where name=? order by id desc limit 1", (name,)).fetchone()
        if not row: return ""
        rows = c.execute("select role, content_json from messages where session_id=? order by id", (row[0],)).fetchall()
        texts = []
        for role, cj in rows:
            parts = json.loads(cj)
            if role == "user" and any(p.get("type") == "text" and not p.get("text", "").startswith("<turn-context>") for p in parts):
                texts = []                                   # a new user turn: reset
            elif role == "assistant":
                for p in parts:
                    if p.get("type") == "text" and p.get("text", "").strip(): texts.append(p["text"].strip())
        return "\n\n".join(texts[-1:]) if texts else ""      # last text block = the answer
    except Exception as e:
        log("session read failed:", e); return ""

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

def session_name(new=False):
    if new or not os.path.exists(STATE):
        name = "signal-" + time.strftime("%Y%m%d-%H%M%S"); open(STATE, "w").write(name); return name, True
    return open(STATE).read().strip(), False

STEP_EMOJI = {"Searching the web": "🔍", "Reading a page": "📄", "Using the browser": "🌐", "Generating an image": "🎨",
              "Looking at an image": "🖼️", "Checking the weather": "🌦️", "Reading feeds": "📰", "Weighing options": "⚖️",
              "Updating notes": "📝", "Recalling past chats": "🧠", "Sending a message": "📨", "Running a command": "💻",
              "Working": "⚙️", "Editing a file": "✍️", "Writing a file": "✍️", "Planning": "📋"}
THINKING = "👀"

STEP_LABELS = [
    ("searxng", "Searching the web"), ("fetch", "Reading a page"), ("browser", "Using the browser"),
    ("imagegen", "Generating an image"), ("generate_image", "Generating an image"), ("vision", "Looking at an image"),
    ("read_image", "Looking at an image"), ("weather", "Checking the weather"), ("read_feed", "Reading feeds"),
    ("decisions", "Weighing options"), ("memory", "Updating notes"), ("chatrecall", "Recalling past chats"),
    ("notify", "Sending a message"), ("shell", "Running a command"), ("execute_javascript", "Working"),
    ("text_editor", "Editing a file"), ("write", "Writing a file"), ("edit", "Editing a file"), ("todo", "Planning"),
]

def progress_steps(name: str):
    """Friendly labels for the tool calls made so far in the current turn of session `name`."""
    try:
        c = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True)
        row = c.execute("select id from sessions where name=? order by id desc limit 1", (name,)).fetchone()
        if not row: return []
        steps = []
        for role, cj in c.execute("select role, content_json from messages where session_id=? order by id", (row[0],)):
            parts = json.loads(cj)
            if role == "user" and any(p.get("type") == "text" and not p.get("text", "").startswith("<turn-context>") for p in parts):
                steps = []
            for p in parts:
                if p.get("type") != "toolRequest": continue
                tc = p["toolCall"].get("value", {}); tool = tc.get("name", ""); args = json.dumps(tc.get("arguments", {}))
                if tool == "list_functions": continue
                hay = tool + " " + (args if tool == "execute_javascript" else "")
                label = next((lab for key, lab in STEP_LABELS if key in hay), "Working")
                if not steps or steps[-1][0] != label: steps.append([label, 1])
                else: steps[-1][1] += 1
        return steps
    except Exception:
        return []

def status_text(steps, done=False):
    lines = []
    for label, n in steps[:-1] if steps else []:
        lines.append(f"✓ {label}" + (f" ×{n}" if n > 1 else ""))
    if steps:
        label, n = steps[-1]; lines.append(f"⏳ {label}" + (f" ×{n}" if n > 1 else "") + "…")
    return "\n".join(lines[-4:])

def run_goose(prompt: str) -> str:
    name, fresh = session_name()
    cmd = [GOOSE, "run", "-q", "--output-format", "text", "-n", name, "--max-turns", "40", "-t", prompt]
    if not fresh: cmd.insert(2, "-r")
    for attempt in range(2):
        try:
            p = subprocess.run(cmd, cwd=WORKDIR, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return "Sorry, that took too long and I stopped it. Try a smaller question, or /new."
        out = (p.stdout or "").strip()
        if p.returncode == 0:
            reply = final_reply(name)
            return reply or out or "Done."
        err = (p.stderr or "")[-600:]
        if "-r" in cmd and ("not found" in err.lower() or "no session" in err.lower()):
            cmd.remove("-r"); continue                       # session vanished: start fresh under the same name
        log("goose rc", p.returncode, err.replace("\n", " ")[-300:])
        return out or f"Goose hit an error: {err.strip().splitlines()[-1] if err.strip() else 'no output'}"
    return "Goose produced no reply."

def download(att_id: str, content_type: str) -> str:
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "audio/aac": ".aac",
           "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "application/pdf": ".pdf", "text/plain": ".txt"}.get(content_type, "")
    path = os.path.join(INBOX, re.sub(r"[^\w.-]", "_", att_id) + ext)
    with urllib.request.urlopen(f"{sg.API}/v1/attachments/{att_id}", timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return path

def handle(dm: dict):
    text = (dm.get("message") or "").strip()
    atts = dm.get("attachments") or []
    paths = []
    for a in atts:
        try: paths.append(download(a["id"], a.get("contentType", "")))
        except Exception as e: log("attachment download failed:", e)
    ans = ap.try_answer(text) if text and not paths else None
    if ans:
        item, decision = ans
        sg.send(f"{'✅' if decision == 'approved' else '⛔'} Noted: **{decision}** for \"{item['question'][:80]}\""); return
    if text.lower() in ("/new", "new chat", "/reset"):
        session_name(new=True); sg.send("Started a fresh conversation."); return
    if text.lower() == "/help":
        sg.send("Just message me. I can search the web, read pages, browse, check the weather and feeds, generate and look at images, and check the server.\n/new starts a fresh conversation."); return
    if not text and not paths: return
    prompt = text
    if paths:
        prompt += ("\n\n" if text else "") + "The user attached file(s): " + ", ".join(paths) + \
                  ". Images can be viewed with read_image or the vision tool."
    prompt += ("\n\n(You are replying over Signal on the user's phone: be concise, plain text with short paragraphs; "
               "no tables; links as plain URLs; if you created or looked at an image, mention its path or gallery URL so it can be attached.)")
    sg.typing()
    name, _ = session_name()
    msg_ts = dm.get("timestamp")
    current = None
    def set_reaction(emoji):
        nonlocal current
        if emoji == current or not msg_ts: return
        try: sg.react(emoji, msg_ts); current = emoji
        except Exception as e: log("reaction failed:", e)
    set_reaction(THINKING)
    import threading
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("reply", run_goose(prompt)), daemon=True); t.start()
    started = time.time()
    while t.is_alive():
        t.join(1.0)
        if not t.is_alive(): break
        steps = progress_steps(name)
        if steps: set_reaction(STEP_EMOJI.get(steps[-1][0], "⚙️"))
        if int(time.time() - started) % 8 == 0: sg.typing()
    reply = result.get("reply", "Done.")
    images = sg.find_images(reply)
    if current and msg_ts:
        try: sg.react(current, msg_ts, remove=True)
        except Exception as e: log("reaction remove failed:", e)
    sg.send(sg.md_to_signal(reply), attachments=images)
    log("replied", len(reply), "chars,", len(images), "images")

async def main():
    if not sg.BOT or not sg.USER:
        log("not configured: set SIGNAL_BOT_NUMBER and SIGNAL_USER_NUMBER in the .env"); await asyncio.sleep(3600); return
    url = sg.API.replace("http://", "ws://").replace("https://", "wss://") + f"/v1/receive/{sg.BOT}"
    log("bridge up, bot", sg.BOT, "user", sg.USER)
    while True:
        try:
            async with websockets.connect(url, ping_interval=30, max_size=20_000_000) as ws:
                log("connected to signal-api")
                async for raw in ws:
                    try: env = json.loads(raw).get("envelope", {})
                    except Exception: continue
                    src = env.get("sourceNumber") or env.get("source")
                    dm = env.get("dataMessage")
                    sent = (env.get("syncMessage") or {}).get("sentMessage")
                    if not dm and sent:                       # Note to Self: our own account's sends, synced to this device
                        dest = sent.get("destinationNumber") or sent.get("destination")
                        if dest not in (sg.USER, None): continue
                        dm = sent
                    if not dm: continue
                    if src != sg.USER:
                        log("ignored message from", src); continue
                    text = (dm.get("message") or "")
                    log("incoming", "sync" if sent else "direct", "ts", dm.get("timestamp"), "atts", len(dm.get("attachments") or []), repr(text[:80]))
                    if text.startswith("🪿") or sg.recently_sent(dm.get("timestamp")):
                        log("  -> ignored (own message)"); continue
                    try:
                        await asyncio.get_event_loop().run_in_executor(None, handle, dm)
                    except Exception as e:
                        log("handle error:", e)
                        try: sg.send(f"Something went wrong handling that: {e}")
                        except Exception: pass
        except Exception as e:
            log("websocket error:", e, "- reconnecting in 10s"); await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
