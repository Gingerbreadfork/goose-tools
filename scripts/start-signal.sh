#!/usr/bin/env bash
# Start (or restart) the Signal REST bridge (signal-cli daemon). Loopback only; state in ~/signal-api (keep it: it holds the account).
# First time: run with MODE=normal (edit below or: SIGNAL_MODE=normal bash start-signal.sh), link or register, then restart in json-rpc mode.
set -euo pipefail
docker rm -f signal-api >/dev/null 2>&1 || true
docker run -d --name signal-api --restart unless-stopped \
  -p 127.0.0.1:8090:8080 \
  -v "$HOME/signal-api:/home/.local/share/signal-cli" \
  -e MODE="${SIGNAL_MODE:-json-rpc}" -e JSON_RPC_RECEIVE_MODE=manual -e DEFAULT_SIGNAL_TEXT_MODE=styled \
  bbernhard/signal-cli-rest-api:latest >/dev/null
for i in $(seq 1 30); do curl -sf -m 3 http://127.0.0.1:8090/v1/about >/dev/null 2>&1 && break; sleep 2; done
echo "container: $(docker inspect -f '{{.State.Status}}' signal-api)"
echo "about: $(curl -s -m 5 http://127.0.0.1:8090/v1/about | head -c 200)"
echo "accounts: $(curl -s -m 5 http://127.0.0.1:8090/v1/accounts)"
