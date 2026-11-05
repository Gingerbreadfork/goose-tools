#!/usr/bin/env python3
"""Goose file agent. Run this on any computer where you use Goose Desktop against a remote Goose server.

It lets the Goose agent on the server read files you attach (they live on this computer), write results back into
allowed folders, and list the contents of a few allowed folders (no recursion, no hidden files). The server finds this machine by itself: it is the one connected to the Goose server,
so there is nothing to register and no polling. Works on Linux, macOS and Windows with a stock Python 3.8+.

Config file (JSON), created on first run with defaults:  ~/.config/goose-files-agent.json
  token      shared secret, same value as REMOTE_FILES_TOKEN on the server (required)
  server     address of the Goose server (required; also restricts who may connect)
  name       how this machine appears to Goose (default: hostname)
  port       port to listen on (default 8766)
  serves     folders Goose may read from (default ["/"] = anything this user can read)
  writable   folders Goose may write into (default ~/Downloads, ~/Desktop)
  listable   folders Goose may list, one level at a time (default ~/Downloads, ~/Documents, ~/Desktop, ~/Pictures)
  allow_peers IPs allowed to connect (default: the server's host only)
"""
import json, os, platform, socket, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = os.path.expanduser("~/.config/goose-files-agent.json")
HOME = os.path.expanduser("~")


def load_config():
    cfg = {"token": "", "server": "", "name": socket.gethostname(), "port": 8766,
           "serves": ["/"], "writable": [os.path.join(HOME, "Downloads"), os.path.join(HOME, "Desktop")],
           "listable": [os.path.join(HOME, d) for d in ("Downloads", "Documents", "Desktop", "Pictures")], "allow_peers": []}
    if os.path.exists(CONFIG):
        cfg.update(json.load(open(CONFIG)))
    else:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        json.dump(cfg, open(CONFIG, "w"), indent=2)
    if not cfg["token"] or not cfg["server"]:
        sys.exit(f"set 'token' (same value as REMOTE_FILES_TOKEN on the server) and 'server' (the Goose server's host/IP) in {CONFIG} and restart")
    if not cfg["allow_peers"]:
        host = urllib.parse.urlparse(cfg["server"]).hostname or cfg["server"]
        cfg["allow_peers"] = [host, "127.0.0.1"]
    cfg["serves"] = [os.path.realpath(os.path.expanduser(p)) for p in cfg["serves"]]
    cfg["writable"] = [os.path.realpath(os.path.expanduser(p)) for p in cfg["writable"]]
    cfg["listable"] = [os.path.realpath(os.path.expanduser(p)) for p in cfg.get("listable", [])]
    return cfg


CFG = load_config()


def under(path, roots):
    p = os.path.realpath(os.path.expanduser(path))
    return p if any(p == r or p.startswith(r.rstrip(os.sep) + os.sep) or r == os.sep for r in roots) else None


class H(BaseHTTPRequestHandler):
    def _deny(self, code, msg):
        self.send_response(code); self.end_headers(); self.wfile.write(msg.encode())

    def _auth(self):
        if self.client_address[0] not in CFG["allow_peers"]:
            self._deny(403, "peer not allowed"); return False
        if self.headers.get("X-Token") != CFG["token"]:
            self._deny(401, "bad token"); return False
        return True

    def _path(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        return u.path, (q.get("path") or [""])[0]

    def do_GET(self):
        if not self._auth(): return
        ep, raw = self._path(); p = under(raw, CFG["serves"])
        if not p: return self._deny(403, "path is outside the folders this machine serves")
        if ep == "/file":
            if not os.path.isfile(p): return self._deny(404, "no such file")
            try:
                f = open(p, "rb")
            except PermissionError:
                return self._deny(403, "not readable by this user")
            with f:
                self.send_response(200); self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(p))); self.end_headers()
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk: break
                    self.wfile.write(chunk)
            return
        if ep == "/ls":
            lp = under(raw, CFG["listable"])
            if not lp: return self._deny(403, "listing allowed only under: " + ", ".join(CFG["listable"]))
            if not os.path.isdir(lp): return self._deny(404, "no such directory")
            items = []
            for n in sorted(os.listdir(lp)):
                if n.startswith("."): continue
                fp = os.path.join(lp, n)
                if os.path.islink(fp) and not under(fp, CFG["listable"]): continue   # symlink escaping the allowed folders
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                items.append({"name": n, "dir": os.path.isdir(fp), "size": st.st_size if os.path.isfile(fp) else None,
                              "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
                if len(items) >= 500: items.append({"name": "... (truncated at 500 entries)", "dir": False, "size": None}); break
            body = json.dumps(items).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if ep == "/ping":
            body = json.dumps({"name": CFG["name"], "platform": platform.system(), "serves": CFG["serves"], "writable": CFG["writable"], "listable": CFG["listable"]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self._deny(404, "unknown endpoint")

    def do_PUT(self):
        if not self._auth(): return
        ep, raw = self._path()
        if ep != "/file": return self._deny(404, "unknown endpoint")
        p = under(raw, CFG["writable"])
        if not p: return self._deny(403, "writes allowed only under: " + ", ".join(CFG["writable"]))
        n = int(self.headers.get("Content-Length", "0")); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            while n > 0:
                chunk = self.rfile.read(min(n, 1 << 20)); f.write(chunk); n -= len(chunk)
        self.send_response(201); self.end_headers(); self.wfile.write(p.encode())

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.client_address[0], fmt % a))



if __name__ == "__main__":
    sys.stderr.write(f"goose-files-agent '{CFG['name']}' serving {CFG['serves']} on port {CFG['port']}\n")
    ThreadingHTTPServer(("0.0.0.0", CFG["port"]), H).serve_forever()
