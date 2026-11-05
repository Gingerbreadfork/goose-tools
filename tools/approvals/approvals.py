# Approval requests over Signal: Goose asks a yes/no question, the user replies "yes"/"no" in Signal, the bridge records it.
import datetime as dt, json, os, re, time, uuid

STORE = os.path.expanduser("~/.config/goose/approvals.json")
YES = re.compile(r"^\s*(yes|y|yep|yeah|ok|okay|approve|approved|go|do it|sure)\b", re.I)
NO = re.compile(r"^\s*(no|n|nope|deny|denied|stop|don't|dont|cancel)\b", re.I)


def load():
    try: return json.load(open(STORE))
    except Exception: return []


def save(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"; json.dump(items, open(tmp, "w"), indent=1); os.replace(tmp, STORE)


def create(question: str, timeout_min: int) -> dict:
    item = {"id": uuid.uuid4().hex[:4], "question": question.strip(), "status": "pending", "created": time.time(),
            "expires": time.time() + timeout_min * 60, "answer": None}
    items = [x for x in load() if x["status"] == "pending" and x["expires"] > time.time()]
    items.append(item); save(items); return item


def pending():
    return [x for x in load() if x["status"] == "pending" and x["expires"] > time.time()]


def get(aid: str):
    return next((x for x in load() if x["id"] == aid), None)


def try_answer(text: str):
    """If `text` is a yes/no reply to a pending approval, record it and return (item, decision). Else None."""
    items = load(); open_ = [x for x in items if x["status"] == "pending" and x["expires"] > time.time()]
    if not open_: return None
    t = text.strip()
    decision = "approved" if YES.match(t) else "denied" if NO.match(t) else None
    if not decision: return None
    m = re.search(r"\b([0-9a-f]{4})\b", t.lower()); target = None
    if m: target = next((x for x in open_ if x["id"] == m.group(1)), None)
    if target is None:
        if len(open_) == 1 or not m: target = open_[-1]
        else: return None
    target["status"] = decision; target["answer"] = t; target["answered"] = time.time(); save(items)
    return target, decision
