#!/usr/bin/env bash
# Launch one of the MCP tool servers for Goose (or any MCP client) with the shared configuration loaded.
#   run-tool.sh <tool>        tools: decisions vision imagegen briefing places documents media lab remote-files
#                                    signal-notify approvals reminders watchers
# Configuration comes from <repo>/.env (copy config/example.env). Each tool runs via `uv run` in an isolated environment.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${1:?usage: run-tool.sh <tool>}"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
export GOOSE_TOOLS_DIR="$REPO/tools"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
case "$TOOL" in
  decisions)     exec "$UV" run --with "mcp<2" "$REPO/tools/decisions/decisions_mcp.py" ;;
  vision)        exec "$UV" run --with "mcp<2" "$REPO/tools/vision/vision_mcp.py" ;;
  imagegen)      exec "$UV" run --with "mcp<2" "$REPO/tools/imagegen/imagegen_mcp.py" ;;
  briefing)      exec "$UV" run --with "mcp<2" --with feedparser "$REPO/tools/briefing/briefing_mcp.py" ;;
  places)        exec "$UV" run --with "mcp<2" "$REPO/tools/places/places_mcp.py" ;;
  documents)     exec "$UV" run --with "mcp<2" "$REPO/tools/documents/documents_mcp.py" ;;
  media)         exec "$UV" run --with "mcp<2" "$REPO/tools/media/media_mcp.py" ;;
  lab)           exec "$UV" run --with "mcp<2" "$REPO/tools/lab/lab_mcp.py" ;;
  remote-files)  exec "$UV" run --with "mcp<2" "$REPO/tools/remote-files/remote_files_mcp.py" ;;
  signal-notify) exec "$UV" run --with "mcp<2" "$REPO/tools/signal/signal_notify_mcp.py" ;;
  approvals)     exec "$UV" run --with "mcp<2" "$REPO/tools/approvals/approvals_mcp.py" ;;
  reminders)     exec "$UV" run --with "mcp<2" "$REPO/tools/reminders/reminders_mcp.py" ;;
  watchers)      exec "$UV" run --with "mcp<2" "$REPO/tools/watchers/watchers_mcp.py" ;;
  *) echo "unknown tool: $TOOL" >&2; exit 2 ;;
esac
