#!/usr/bin/env bash
# Install the Goose file agent on THIS computer (Linux, systemd user service, no sudo). Re-run to update.
#   bash install-goose-files-agent.sh <goose-server-host>          (run from a copy of this folder)
# You will be asked for the shared token: on the Goose server it is REMOTE_FILES_TOKEN in the tools .env
set -euo pipefail
SERVER_HOST="${1:?usage: install-goose-files-agent.sh <goose-server-host-or-ip>}"
mkdir -p ~/.local/bin ~/.config/systemd/user
cp "$(dirname "$0")/goose-files-agent.py" ~/.local/bin/goose-files-agent.py
chmod 700 ~/.local/bin/goose-files-agent.py
CFG=~/.config/goose-files-agent.json
if [ ! -s "$CFG" ] || ! grep -Eq '"token": "[A-Za-z0-9]{16,}"' "$CFG"; then
  TOKEN=""
  until [[ "$TOKEN" =~ ^[A-Za-z0-9]{16,}$ ]]; do
    read -rp "Paste the REMOTE_FILES_TOKEN from the Goose server: " TOKEN < /dev/tty
    TOKEN="${TOKEN#REMOTE_FILES_TOKEN=}"; TOKEN="${TOKEN//[[:space:]]/}"
    [[ "$TOKEN" =~ ^[A-Za-z0-9]{16,}$ ]] || echo "  that doesn't look right (got ${#TOKEN} characters); it should be letters and digits only"
  done
  python3 - "$CFG" "$TOKEN" "$SERVER_HOST" <<'PY'
import json, os, socket, sys
p, token, host = sys.argv[1:]
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg.update({"token": token, "server": host, "name": cfg.get("name") or socket.gethostname(), "port": cfg.get("port", 8766),
            "serves": cfg.get("serves", ["/"]),
            "writable": cfg.get("writable", [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]),
            "listable": cfg.get("listable", [os.path.expanduser("~/" + d) for d in ("Downloads", "Documents", "Desktop", "Pictures")])})
os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(cfg, open(p, "w"), indent=2)
PY
  chmod 600 "$CFG"
fi
python3 - "$CFG" <<'PY'
import json, os, sys
p = sys.argv[1]; cfg = json.load(open(p))
cfg.setdefault("listable", [os.path.expanduser("~/" + d) for d in ("Downloads", "Documents", "Desktop", "Pictures")])
json.dump(cfg, open(p, "w"), indent=2)
PY
cat > ~/.config/systemd/user/goose-files-agent.service <<'UNIT'
[Unit]
Description=Goose file agent (lets the Goose server read files attached from this computer)
After=network-online.target
[Service]
ExecStart=/usr/bin/python3 %h/.local/bin/goose-files-agent.py
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable goose-files-agent.service >/dev/null
systemctl --user restart goose-files-agent.service
sleep 2
if systemctl --user is-active --quiet goose-files-agent.service; then
  echo "agent running as '$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.config/goose-files-agent.json")))["name"])')' on port 8766"
else
  echo "agent failed to start:"; journalctl --user -u goose-files-agent -n 5 --no-pager
fi
echo "Firewall? allow the server in:  sudo ufw allow from $SERVER_HOST to any port 8766 proto tcp"
echo "Edit ~/.config/goose-files-agent.json to change the name, served or writable folders, then: systemctl --user restart goose-files-agent"
