# MCP server: files on the user's other computers (the machines running Goose Desktop against this server).
# No registry: the machine that attached a file is the one connected to the Goose server right now, and this host can
# see that connection. fetch_remote_file copies a file here to the SAME path so every other tool uses it unchanged.
import json, os, subprocess, urllib.error, urllib.parse, urllib.request
from typing import Optional
from mcp.server.fastmcp import FastMCP

TOKEN = os.environ["REMOTE_FILES_TOKEN"]
AGENT_PORT = int(os.environ.get("REMOTE_FILES_AGENT_PORT", "8766"))
GOOSE_PORT = os.environ.get("GOOSE_SERVER_PORT", "3000")
EXTRA = [h for h in os.environ.get("REMOTE_FILES_EXTRA_HOSTS", "").split(",") if h]   # optional fixed machines
mcp = FastMCP("remote_files")


def _connected_peers():
    """IPs currently connected to the Goose server, most connections first."""
    try:
        out = subprocess.run(["ss", "-tn", "state", "established", f"( sport = :{GOOSE_PORT} )"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        out = ""
    counts = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            ip = parts[-1].rsplit(":", 1)[0].strip("[]")
            if ip not in ("127.0.0.1", "::1"):
                counts[ip] = counts.get(ip, 0) + 1
    peers = sorted(counts, key=lambda k: -counts[k]) + [h for h in EXTRA if h not in counts]
    return peers


def _ping(ip, timeout=4):
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://{ip}:{AGENT_PORT}/ping", headers={"X-Token": TOKEN}), timeout=timeout) as r:
            info = json.load(r); info["ip"] = ip; return info
    except Exception:
        return None


def _machines(online_only=True):
    found = []
    for ip in _connected_peers():
        info = _ping(ip)
        if info: found.append(info)
        elif not online_only: found.append({"ip": ip, "name": None, "agent": "not running"})
    return found


def _pick(machine):
    ms = _machines()
    if machine:
        m = next((x for x in ms if (x.get("name") or "").lower() == machine.lower() or x["ip"] == machine), None)
        if not m: raise RuntimeError(f"machine '{machine}' has no reachable file agent; reachable: {[x.get('name') for x in ms]}")
        return [m]
    if not ms:
        peers = _connected_peers()
        if not peers: raise RuntimeError("no other computer is connected to the Goose server right now")
        raise RuntimeError(f"the connected computer(s) {peers} are not running the Goose file agent (port {AGENT_PORT})")
    return ms


def _req(c, method, endpoint, path, data=None, timeout=300):
    url = f"http://{c['ip']}:{AGENT_PORT}{endpoint}?{urllib.parse.urlencode({'path': path})}"
    return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers={"X-Token": TOKEN}), timeout=timeout)


@mcp.tool()
def fetch_remote_file(path: str, machine: Optional[str] = None) -> str:
    """Copy a file from the user's computer (the one running Goose Desktop) to this machine at the same absolute path,
    so it can then be read, viewed or processed with the normal tools. Use whenever a file path the user gave (an
    attachment, a path on their computer) does not exist here. Returns the local path (identical to the input)."""
    path = path.replace("file://", "")
    local = os.path.abspath(os.path.expanduser(path))
    errors = []
    for c in _pick(machine):
        try:
            with _req(c, "GET", "/file", path) as r:
                os.makedirs(os.path.dirname(local), exist_ok=True)
                with open(local, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
            return f"{local} ({os.path.getsize(local)} bytes) fetched from {c.get('name') or c['ip']}; use this path normally now."
        except urllib.error.HTTPError as e:
            errors.append(f"{c.get('name') or c['ip']}: {e.code} {e.read().decode(errors='replace')[:120]}")
        except Exception as e:
            errors.append(f"{c.get('name') or c['ip']}: {e}")
    raise RuntimeError("could not fetch " + path + " - " + "; ".join(errors))


@mcp.tool()
def send_file_to_machine(local_path: str, machine: Optional[str] = None, dest_path: Optional[str] = None) -> str:
    """Copy a file from this machine to the user's computer, into dest_path or, by default, its Downloads folder.
    Only folders that machine allows are writable."""
    local_path = os.path.expanduser(local_path)
    if not os.path.isfile(local_path):
        raise RuntimeError(f"no such local file: {local_path}")
    c = _pick(machine)[0]
    dest = dest_path or (c.get("writable") or ["~/Downloads"])[0].rstrip("/") + "/" + os.path.basename(local_path)
    with open(local_path, "rb") as f:
        data = f.read()
    try:
        with _req(c, "PUT", "/file", dest, data=data) as r:
            return f"saved on {c.get('name') or c['ip']} as {r.read().decode()}"
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{c.get('name') or c['ip']} refused: {e.code} {e.read().decode(errors='replace')[:200]}")




@mcp.tool()
def list_remote_dir(path: str = "~/Downloads", machine: Optional[str] = None) -> list:
    """List one folder on the user's computer (name, dir flag, size, modified). Only a few folders are listable there
    (by default Downloads, Documents, Desktop, Pictures); anything else is refused. No recursion, hidden files omitted."""
    c = _pick(machine)[0]
    try:
        with _req(c, "GET", "/ls", path, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{c.get('name') or c['ip']} refused: {e.code} {e.read().decode(errors='replace')[:200]}")


@mcp.tool()
def list_machines() -> list:
    """The user's computers currently connected to the Goose server, and whether each has the file agent running."""
    return _machines(online_only=False)


if __name__ == "__main__":
    mcp.run()
