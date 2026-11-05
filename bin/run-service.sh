#!/usr/bin/env bash
# Launch one of the long-running helpers with the shared configuration loaded (used by the systemd units in config/systemd).
#   run-service.sh signal-bridge | reminders
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SVC="${1:?usage: run-service.sh <signal-bridge|reminders>}"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
export GOOSE_TOOLS_DIR="$REPO/tools"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
case "$SVC" in
  signal-bridge) exec "$UV" run --with websockets "$REPO/tools/signal/signal_bridge.py" ;;
  reminders)     exec python3 "$REPO/tools/reminders/reminders_daemon.py" ;;
  *) echo "unknown service: $SVC" >&2; exit 2 ;;
esac
