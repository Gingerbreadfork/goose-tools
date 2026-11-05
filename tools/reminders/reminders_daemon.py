# Reminder delivery daemon: every 10 s, deliver due reminders (NOTIFY_BACKEND: signal/ntfy/command) and reschedule repeats.
import datetime as dt, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import reminders_store as rs
import notifier


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def tick():
    now = dt.datetime.now(); items = rs.load(); changed = False; keep = []
    for it in items:
        when = dt.datetime.fromisoformat(it["when"])
        if when <= now:
            try:
                notifier.send(it["text"] + (f"\n\n(repeats {it['repeat']})" if it.get("repeat", "none") != "none" else ""), title="🔔 Reminder")
                log("sent", it["id"], it["text"][:60])
            except Exception as e:
                log("send failed, will retry:", e); keep.append(it); continue
            nxt = rs.next_occurrence(it, now)
            if nxt:
                it["when"] = nxt.isoformat(timespec="minutes"); keep.append(it)
            changed = True
        else:
            keep.append(it)
    if changed: rs.save(keep)


if __name__ == "__main__":
    log("reminders daemon up; store", rs.STORE)
    while True:
        try: tick()
        except Exception as e: log("tick error:", e)
        time.sleep(10)
