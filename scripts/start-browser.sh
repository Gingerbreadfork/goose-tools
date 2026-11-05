#!/usr/bin/env bash
# Start (or restart) the Playwright MCP browser service for Goose: headless Chromium, isolated contexts (so several
# Goose sessions can browse at once), saved logins, screenshots/PDFs under GOOSE_WORK/images/browser (served by the
# gallery if configured). Listens on 127.0.0.1:8931 only. Register in Goose as a streamable_http extension:
#   uri: http://127.0.0.1:8931/mcp
# The output dir is ALSO mounted at the Goose working directory inside the container, because Playwright MCP resolves
# relative filenames against the MCP client's root (Goose's working dir) rather than --output-dir.
# Logins: after signing in to a site, the agent can persist cookies with browser_run_code_unsafe:
#   async (page) => { await page.context().storageState({ path: '/profile/logins.json' }); }
set -euo pipefail
WORK="${GOOSE_WORK:-$HOME/goose-work}"
GOOSE_WORKDIR="${GOOSE_WORKDIR:-$HOME}"          # the working directory Goose sessions use
mkdir -p "$WORK/browser-profile" "$WORK/images/browser"
[ -s "$WORK/browser-profile/logins.json" ] || echo '{"cookies":[],"origins":[]}' > "$WORK/browser-profile/logins.json"
docker rm -f goose-browser >/dev/null 2>&1 || true
docker run -d --name goose-browser --restart unless-stopped --init \
  --shm-size=1g -w /output \
  -p 127.0.0.1:8931:8931 \
  -v "$WORK/browser-profile:/profile" \
  -v "$WORK/images/browser:/output" \
  -v "$WORK/images/browser:$GOOSE_WORKDIR" \
  mcr.microsoft.com/playwright/mcp \
  --port 8931 --host 0.0.0.0 \
  --isolated --storage-state /profile/logins.json --output-dir /output \
  --caps vision,pdf --image-responses omit --allowed-hosts 127.0.0.1:8931,localhost:8931,127.0.0.1,localhost \
  --viewport-size 1280x900 --timeout-navigation 45000 >/dev/null
sleep 4
echo "container: $(docker inspect -f '{{.State.Status}}' goose-browser)"
docker logs goose-browser 2>&1 | tail -3
