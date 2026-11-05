# Shared helpers for the Signal notify tool and the Signal bridge.
import base64, json, os, re, urllib.request

API = os.environ.get("SIGNAL_API", "http://127.0.0.1:8090").rstrip("/")
BOT = os.environ.get("SIGNAL_BOT_NUMBER", "")
USER = os.environ.get("SIGNAL_USER_NUMBER", "")
IMAGE_DIR = os.path.join(os.path.expanduser(os.environ.get("GOOSE_WORK", "~/goose-work")), "images")
GALLERY = (os.environ.get("GALLERY_URL", "").rstrip("/") + "/") if os.environ.get("GALLERY_URL") else "\x00nogallery/"
MAX_CHARS = 3500
MARK = "🪿\n\n"   # first line on its own, then a blank line, prefix on every bot message; the bridge ignores messages that start with it (Note to Self loop guard)
SENT_LOG = os.path.expanduser(os.environ.get("SIGNAL_SENT_LOG", "~/.config/goose/signal-sent.log"))

def md_to_signal(text: str) -> str:
    """Markdown -> Signal 'styled' text (**bold**, *italic*, `mono` survive; headings become bold; links become 'text: url')."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if m: line = f"**{m.group(1).strip()}**"
        line = re.sub(r"!\[[^\]]*\]\((\S+?)\)", "", line)                      # images handled as attachments
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1: \2", line)   # links
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)                           # bullets
        line = re.sub(r"^\|.*\|$", lambda mm: " | ".join(c.strip() for c in mm.group(0).strip("|").split("|")), line)  # tables
        if re.match(r"^\s*\|?\s*:?-{3,}", line): continue                        # table rules
        out.append(line)
    s = "\n".join(out)
    # Signal "styled" syntax: **bold**, *italic*, ~strike~, `mono`, ||spoiler||. Neutralise accidental markers.
    s = re.sub(r"~~(.+?)~~", "\x00\\1\x00", s)          # real markdown strikethrough -> placeholder
    s = s.replace("~", "≈")                                 # lone tildes ("~2%") would strike text out
    s = s.replace("\x00", "~")                              # restore intended strikethrough
    s = s.replace("||", "|")
    s = re.sub(r"(?<![*\w])\*(?![*\s])(?=[^*\n]*\d)", "×", s)   # a stray "*" used as multiply, not italics
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def find_images(text: str):
    """Local image files referenced in text (gallery URLs or paths) -> list of paths."""
    paths = []
    for url in re.findall(re.escape(GALLERY) + r"([\w./-]+\.(?:png|jpg|jpeg|webp|gif))", text):
        paths.append(os.path.join(IMAGE_DIR, url))
    for p in re.findall(re.escape(IMAGE_DIR) + r"(/[\w./-]+\.(?:png|jpg|jpeg|webp|gif))", text):
        p = IMAGE_DIR + p
        paths.append(p)
    seen, res = set(), []
    for p in paths:
        if p not in seen and os.path.isfile(p): seen.add(p); res.append(p)
    return res[:4]

def _post(path, body, timeout=90):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}

def send(text: str, attachments=(), to: str = None, styled=True, prefix=None):
    """Send to the user (chunked). Attachments: file paths."""
    to = to or USER
    chunks = [text[i:i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS)] or [""]
    b64 = []
    for p in attachments:
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(p.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        with open(p, "rb") as f:
            b64.append(f"data:{mime};filename={os.path.basename(p)};base64," + base64.b64encode(f.read()).decode())
    last = None
    for i, c in enumerate(chunks):
        body = {"number": BOT, "recipients": [to], "message": ((MARK if prefix is None else prefix) + c) if i == 0 else c,
                "text_mode": "styled" if styled else "normal", "notify_self": True}
        if i == len(chunks) - 1 and b64: body["base64_attachments"] = b64
        last = _post("/v2/send", body)
        if isinstance(last, list): last = last[0] if last else {}
        try:
            with open(SENT_LOG, "a") as f: f.write(f"{last.get('timestamp')}\n")
        except Exception: pass
    return last

def recently_sent(ts) -> bool:
    try:
        lines = open(SENT_LOG).read().split()[-200:]
        return str(ts) in lines
    except Exception:
        return False

def send_edit(text: str, edit_timestamp, to: str = None, attachments=(), prefix=None):
    """Replace an earlier message (by its timestamp) with new text. Returns the response dict."""
    to = to or USER
    body = {"number": BOT, "recipients": [to], "message": (MARK if prefix is None else prefix) + text[:MAX_CHARS], "text_mode": "styled",
            "notify_self": False, "edit_timestamp": int(edit_timestamp)}
    r = _post("/v2/send", body)
    if isinstance(r, list): r = r[0] if r else {}
    try:
        with open(SENT_LOG, "a") as f: f.write(f"{r.get('timestamp')}\n")
    except Exception: pass
    return r

def react(emoji: str, target_ts, to: str = None, remove=False):
    """Add (or remove) a reaction on the user's message with timestamp target_ts. A new reaction replaces the previous one."""
    to = to or USER
    body = {"reaction": emoji, "recipient": to, "target_author": to, "timestamp": int(target_ts)}
    req = urllib.request.Request(f"{API}/v1/reactions/{BOT}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="DELETE" if remove else "POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()

def typing(to: str = None):
    try:
        req = urllib.request.Request(f"{API}/v1/typing-indicator/{BOT}", data=json.dumps({"recipient": to or USER}).encode(),
                                     headers={"Content-Type": "application/json"}, method="PUT")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass
