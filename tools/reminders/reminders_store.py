# Shared reminder store (JSON file) used by the reminders MCP tools, the reminders daemon and the voice agent.
import datetime as dt, json, os, re, uuid

STORE = os.path.expanduser(os.environ.get("REMINDERS_STORE", "~/.config/goose/reminders.json"))
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load():
    try:
        return json.load(open(STORE))
    except Exception:
        return []


def save(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"; json.dump(items, open(tmp, "w"), indent=1); os.replace(tmp, STORE)


def parse_when(when: str, now: dt.datetime | None = None) -> dt.datetime:
    """'+20m', '+2h', '+1d', 'HH:MM' (next occurrence), 'YYYY-MM-DD HH:MM', 'YYYY-MM-DDTHH:MM', 'tomorrow 09:00',
    'mon 18:00' (next Monday)."""
    now = now or dt.datetime.now(); w = when.strip().lower()
    m = re.match(r"^\+?(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$", w)
    if m:
        n = float(m.group(1)); u = m.group(2)[0]
        return now + dt.timedelta(minutes=n) if u == "m" else now + dt.timedelta(hours=n) if u == "h" else now + dt.timedelta(days=n)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ t](\d{1,2}):(\d{2})$", w)
    if m: return dt.datetime.strptime(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}", "%Y-%m-%d %H:%M")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})$", w)
    if m: return dt.datetime.strptime(m.group(1) + " 09:00", "%Y-%m-%d %H:%M")
    m = re.match(r"^(today|tomorrow|tonight|" + "|".join(DAYS) + r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", w)
    if m:
        day, hh, mm, ap = m.group(1), int(m.group(2)), int(m.group(3) or 0), m.group(4)
        if ap == "pm" and hh < 12: hh += 12
        if ap == "am" and hh == 12: hh = 0
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if day in (None, "today", "tonight"):
            if t <= now and day is None: t += dt.timedelta(days=1)
            if day == "tonight" and hh < 12: t += dt.timedelta(hours=12)
        elif day == "tomorrow":
            t += dt.timedelta(days=1)
        else:
            target = DAYS.index(day[:3]); delta = (target - now.weekday()) % 7
            if delta == 0 and t <= now: delta = 7
            t += dt.timedelta(days=delta)
        return t
    raise ValueError(f"could not understand the time '{when}'; use e.g. '+20m', '18:30', 'tomorrow 09:00', 'fri 17:00', '2026-12-01 10:00'")


def next_occurrence(item: dict, after: dt.datetime) -> dt.datetime | None:
    """For repeating reminders: the next run strictly after `after`. None for one-off reminders."""
    rep = (item.get("repeat") or "none").lower(); base = dt.datetime.fromisoformat(item["when"])
    if rep in ("", "none"): return None
    t = base
    while t <= after:
        if rep == "daily": t += dt.timedelta(days=1)
        elif rep == "weekdays":
            t += dt.timedelta(days=1)
            while t.weekday() >= 5: t += dt.timedelta(days=1)
        elif rep == "weekly": t += dt.timedelta(days=7)
        elif rep == "monthly":
            mth = t.month % 12 + 1; yr = t.year + (t.month == 12)
            t = t.replace(year=yr, month=mth)
        elif rep == "hourly": t += dt.timedelta(hours=1)
        else: return None
    return t


def add(text: str, when: str, repeat: str | None = None, source: str = "chat") -> dict:
    t = parse_when(when)
    item = {"id": uuid.uuid4().hex[:6], "text": text.strip(), "when": t.replace(second=0, microsecond=0).isoformat(timespec="minutes"),
            "repeat": (repeat or "none").lower(), "created": dt.datetime.now().isoformat(timespec="minutes"), "source": source}
    items = load(); items.append(item); save(items); return item


def pending():
    return sorted(load(), key=lambda x: x["when"])


def remove(rid: str) -> bool:
    items = load(); new = [x for x in items if x["id"] != rid]
    if len(new) == len(items): return False
    save(new); return True


def describe(item: dict) -> str:
    t = dt.datetime.fromisoformat(item["when"]); rep = item.get("repeat", "none")
    return f"[{item['id']}] {t.strftime('%a %d %b %H:%M')}" + (f" ({rep})" if rep != "none" else "") + f": {item['text']}"
