# MCP server: page watchers. Goose stores "watch this page for X"; run_watchers (called hourly by a scheduled recipe)
# fetches each page, compares with the last snapshot, asks the NPU decider whether the condition happened, and notifies
# the user on Signal only when it did (or when the page changed, for change-watchers).
import datetime as dt, hashlib, html, json, os, re, sys, time, urllib.request, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
from typing import Optional
from mcp.server.fastmcp import FastMCP
import notifier
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY

STORE = os.path.expanduser(os.environ.get("WATCHERS_STORE", "~/.config/goose/watchers.json"))
SNAPS = STORE.rsplit(".", 1)[0] + "-snapshots"
HALOGEN = OPENAI_BASE_URL; KEY = OPENAI_API_KEY
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o-mini")
SYSTEMONE = os.environ.get("SYSTEMONE_URL", "")            # optional Jev-compatible decider; otherwise the chat model decides
SYSTEMONE_MODEL = os.environ.get("SYSTEMONE_MODEL", "d3-nano")
PW = os.environ.get("PLAYWRIGHT_URL", "http://127.0.0.1:8931/mcp")
UA = "Mozilla/5.0 (X11; Linux x86_64) goose-watcher/1.0"
mcp = FastMCP("watchers")


def load():
    try: return json.load(open(STORE))
    except Exception: return []


def save(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"; json.dump(items, open(tmp, "w"), indent=1); os.replace(tmp, STORE)


def _text_from_html(raw: str) -> str:
    t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\r\f\v]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def _fetch_plain(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-AU,en"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return _text_from_html(r.read().decode("utf-8", "replace"))


def _fetch_browser(url: str) -> str:
    """Render with the Playwright service (JavaScript pages) and return the page text."""
    sid = None
    def call(method, params=None, id_=1, notify=False):
        nonlocal sid
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None: body["params"] = params
        if not notify: body["id"] = id_
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if sid: h["mcp-session-id"] = sid
        with urllib.request.urlopen(urllib.request.Request(PW, data=json.dumps(body).encode(), headers=h), timeout=120) as r:
            sid = r.headers.get("mcp-session-id") or sid; raw = r.read().decode()
        if notify: return None
        for line in raw.splitlines():
            if line.startswith("data:"):
                d = json.loads(line[5:].strip())
                if d.get("id") == id_: return d
        return json.loads(raw)
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "goose-watcher", "version": "1"}})
    call("notifications/initialized", notify=True)
    call("tools/call", {"name": "browser_navigate", "arguments": {"url": url}}, 2)
    r = call("tools/call", {"name": "browser_evaluate", "arguments": {"function": "() => document.body.innerText"}}, 3)
    txt = r["result"]["content"][0]["text"]
    m = re.search(r"### Result\n(.*?)\n### Ran Playwright code", txt, re.S)
    out = m.group(1) if m else txt
    try:
        req = urllib.request.Request(PW, method="DELETE", headers={"mcp-session-id": sid}); urllib.request.urlopen(req, timeout=20).read()
    except Exception: pass
    return re.sub(r"\n\s*\n+", "\n", out.strip().strip('"').replace("\\n", "\n"))


def _focus(text: str, question: str, limit=6000) -> str:
    """Keep the parts of the page most related to the question (keyword windows), capped."""
    words = [w for w in re.findall(r"[a-z0-9$%.]{3,}", question.lower()) if w not in ("the", "and", "for", "has", "does", "when", "page", "this", "that", "with", "any")]
    lines = text.splitlines(); scored = []
    for i, ln in enumerate(lines):
        s = sum(1 for w in words if w in ln.lower())
        if s or re.search(r"\$\s?\d|\d+\.\d\d|in stock|out of stock|sold out|available", ln, re.I): scored.append((s, i))
    if not scored: return text[:limit]
    keep = set()
    for _, i in sorted(scored, reverse=True)[:40]:
        keep.update(range(max(0, i - 2), min(len(lines), i + 3)))
    out = "\n".join(lines[i] for i in sorted(keep))
    return out[:limit] if len(out) > 200 else text[:limit]


def _decide(previous: str, current: str, question: str) -> tuple[float, str]:
    state = f"WATCH QUESTION: {question}\n\n=== PREVIOUS CHECK (older) ===\n{previous or '(none yet)'}\n\n=== CURRENT PAGE ===\n{current}"
    if SYSTEMONE:   # fast calibrated decision model
        body = {"model": SYSTEMONE_MODEL, "state": state[:12000], "questions": {
            "happened": {"type": "noul", "instructions": f"Based on the CURRENT page (and the change from the previous check), is this now true: {question}?"}}}
        req = urllib.request.Request(SYSTEMONE, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["answers"]["happened"]["noul"], ""
    body = {"model": CHAT_MODEL, "max_tokens": 5, "temperature": 0, "messages": [
        {"role": "system", "content": "Answer with a single number between 0 and 1: the probability that the statement is now true given the page text."},
        {"role": "user", "content": state[:12000] + f"\n\nStatement: {question}\nProbability:"}]}
    req = urllib.request.Request(HALOGEN + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = json.load(r)["choices"][0]["message"]["content"]
    m = re.search(r"[01](?:\.\d+)?", txt)
    return (float(m.group(0)) if m else 0.0), ""


def _summarise(current: str, question: str) -> str:
    body = {"model": CHAT_MODEL, "max_tokens": 120, "messages": [
        {"role": "system", "content": "You write one or two plain sentences for a phone notification. No markdown."},
        {"role": "user", "content": f"The user is watching a web page for: {question}\nThe condition now appears to be true. From this page text, state the key fact (e.g. the price, the status) in one or two sentences:\n\n{current[:5000]}"}]}
    req = urllib.request.Request(HALOGEN + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


@mcp.tool()
def add_watcher(name: str, url: str, question: str, interval_min: int = 60, use_browser: bool = False, notify_on_any_change: bool = False) -> str:
    """Watch a web page and alert the user (via the configured notifier) when something happens. `question` is the condition to test each time,
    e.g. "the price of the Framework 13 drops below $1500", "the product is back in stock", "a new episode is listed",
    "the job ad is gone". `use_browser` renders JavaScript pages with the real browser (slower). `notify_on_any_change`
    alerts on any text change instead of a condition. Checks run every `interval_min` (minimum 15) by the hourly watcher job."""
    item = {"id": uuid.uuid4().hex[:5], "name": name.strip(), "url": url.strip(), "question": question.strip(), "interval_min": max(15, int(interval_min)),
            "use_browser": bool(use_browser), "any_change": bool(notify_on_any_change), "created": dt.datetime.now().isoformat(timespec="minutes"),
            "last_checked": None, "last_hash": None, "last_result": None, "triggered": 0}
    items = load(); items.append(item); save(items)
    try:   # take the first snapshot now so the next check has something to compare with
        txt = _fetch_browser(url) if use_browser else _fetch_plain(url)
        os.makedirs(SNAPS, exist_ok=True); open(os.path.join(SNAPS, item["id"] + ".txt"), "w").write(txt)
        item["last_hash"] = hashlib.sha1(txt.encode()).hexdigest(); item["last_checked"] = dt.datetime.now().isoformat(timespec="minutes"); save(load()[:-1] + [item])
        note = f" First snapshot taken ({len(txt)} chars)."
    except Exception as e:
        note = f" Warning: first fetch failed ({str(e)[:80]}); will retry on the next run."
    return f"Watching [{item['id']}] {item['name']} every {item['interval_min']} min: {item['question']}." + note


@mcp.tool()
def list_watchers() -> list:
    """All watchers with their last check time and result."""
    return [{k: v for k, v in x.items() if k != "last_hash"} for x in load()]


@mcp.tool()
def remove_watcher(watcher_id: str) -> str:
    """Stop a watcher by id."""
    items = load(); new = [x for x in items if x["id"] != watcher_id]
    if len(new) == len(items): return f"no watcher {watcher_id}"
    save(new)
    try: os.remove(os.path.join(SNAPS, watcher_id + ".txt"))
    except OSError: pass
    return "removed"


@mcp.tool()
def run_watchers(force: bool = False) -> str:
    """Check every watcher that is due (or all, with force), compare with the previous snapshot, decide with the NPU model
    whether the condition is met, and notify the user when it is. Returns a short report. Called by the hourly
    'watchers' schedule; can also be run on demand."""
    items = load(); now = dt.datetime.now(); report = []; os.makedirs(SNAPS, exist_ok=True)
    for it in items:
        due = force or not it.get("last_checked") or (now - dt.datetime.fromisoformat(it["last_checked"])).total_seconds() >= it["interval_min"] * 60 - 30
        if not due: report.append(f"[{it['id']}] {it['name']}: not due"); continue
        try:
            txt = _fetch_browser(it["url"]) if it["use_browser"] else _fetch_plain(it["url"])
        except Exception as e:
            it["last_checked"] = now.isoformat(timespec="minutes"); it["last_result"] = f"fetch failed: {str(e)[:80]}"; report.append(f"[{it['id']}] {it['name']}: fetch failed"); continue
        h = hashlib.sha1(txt.encode()).hexdigest(); snap = os.path.join(SNAPS, it["id"] + ".txt")
        prev = open(snap).read() if os.path.exists(snap) else ""
        changed = h != it.get("last_hash")
        fired, why = False, ""
        if it["any_change"]:
            fired = changed and bool(it.get("last_hash")); why = "page changed"
        elif changed or it.get("last_result") in (None, "") or "failed" in str(it.get("last_result")):
            p, _ = _decide(_focus(prev, it["question"]), _focus(txt, it["question"]), it["question"])
            now_true = p >= 0.7
            fired = now_true and not it.get("cond_true")          # alert only when the condition becomes true
            it["cond_true"] = True if now_true else (False if p < 0.5 else it.get("cond_true", False))
            why = f"decider {p:.2f}" + (" (still true, no repeat alert)" if now_true and not fired else "")
        else:
            why = "unchanged"
        if fired:
            try: fact = _summarise(_focus(txt, it["question"]), it["question"])
            except Exception: fact = "(could not summarise)"
            notifier.send(f"{fact}\n\n{it['url']}", title=f"👀 {it['name']}")
            it["triggered"] = it.get("triggered", 0) + 1
            if not it["any_change"]: it["last_result"] = "TRIGGERED " + now.strftime("%d %b %H:%M")
        else:
            it["last_result"] = why
        it["last_hash"] = h; it["last_checked"] = now.isoformat(timespec="minutes"); open(snap, "w").write(txt)
        report.append(f"[{it['id']}] {it['name']}: {'ALERT SENT' if fired else why}")
    save(items)
    return "\n".join(report) if report else "no watchers"


if __name__ == "__main__":
    mcp.run()
